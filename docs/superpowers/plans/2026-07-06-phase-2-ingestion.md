# Phase 2: Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the stub `ingest` stage in `worker/src/worker/pipeline.py` with the real ingestion pipeline (design spec stages 1–3): convert/render every solicitation and deck page to a per-page record (native text + image), run every deck page through Claude vision for an enriched description, and align an optional narration script to its slides on explicit `Slide N:` markers. `review` and `report` remain stub stages — Phase 3/4 replace them next.

**Architecture:** No shape change from Phase 1 — `web/` still owns auth/uploads/reads, `worker/` still polls and claims `analyses` rows. This phase only fills in the worker's `ingest` stage body and adds one table (`pages`). One addition to the Phase 1 contract: `documents`/`uploads` gain a stored `blob_url` (not just `blob_pathname`) so the worker never has to guess the Blob CDN hostname, and `documents` gains a nullable `pdf_blob_url` alongside the existing `pdf_blob_pathname` for converted/render-source PDFs. The worker gets its own Blob credential — a static `BLOB_READ_WRITE_TOKEN` (Railway env var), separate from and unrelated to the web app's OIDC-based Blob access. The worker downloads over plain HTTPS (documented, static-token-friendly) but uploads through a small Node helper script that shells out to the real `@vercel/blob` `put()` — the only Blob write path that is actually documented/supported, since there is no official Python Blob SDK.

**Tech Stack:** Phase 1 stack plus PyMuPDF (`pymupdf`) for PDF rendering/text extraction; `httpx` for Blob downloads; `anthropic` Python SDK + Pydantic v2 for the vision pass; Node.js + `@vercel/blob` (npm) inside the worker image, invoked via subprocess, for Blob uploads; LibreOffice headless (system package) for PPTX→PDF conversion.

**Spec:** `docs/superpowers/specs/2026-07-02-ai-proposal-review-board-design.md`, stages 1–3. This is plan 2 of 5 (Foundation → **Ingestion** → Extraction/Matrix → Reviewers → Report UI).

## Global Constraints

- Everything in Phase 1's Global Constraints still applies (advisory-only, private Blob, ownership checks, `FOR UPDATE SKIP LOCKED`, fixed enums, 7-day retention, Node ≥ 20 / Python ≥ 3.12 / Postgres 16).
- One slide = one page = one citation anchor. Every `pages` row must be traceable to `document_id` + `page_no`; solicitation citations remain distinguishable by document kind/name + page (already satisfied by the existing `documents.kind`/`display_name` columns — no extra column needed).
- Rendered page images: PyMuPDF at a pinned **150 DPI**, and each image must fit comfortably under Vercel's **~4.5 MB** function response cap (the eventual protected source-render route reads through this limit in Phase 5). Assert on image size in the ingest stage; fail loudly rather than silently truncate.
- Vision pass runs on **every** deck page — no routing heuristic, per `GOALS.md`.
- Script alignment only accepts scripts with explicit `Slide N:` markers on every referenced slide; an unmarked or partially-marked script fails the stage with a specific error (auto-alignment is out of scope, per spec).
- LibreOffice conversion must preserve a real text layer; if a real deck ever arrives already rasterized (no extractable text), that's degrade-gracefully territory — the vision pass still covers it. Don't special-case it in code; the redline/text-fidelity and PPTX conversion tests in Task 5 are what actually verify this assumption.
- Worker's Blob credential (`BLOB_READ_WRITE_TOKEN`, static) is a Railway-only secret. It is unrelated to the web app's `VERCEL_OIDC_TOKEN`/`BLOB_STORE_ID` pair — don't conflate the two or try to share one across services.
- The two real fixture documents (SA5 RFQ, CTG oral deck) are committed into the repo under `worker/tests/fixtures/` per explicit confirmation — this is a private repo and that's an accepted tradeoff for reproducible tests.

---

### Task 1: Store Blob URLs and content type alongside pathnames

**Why:** The worker needs the full Blob URL to download originals (the CDN hostname isn't derivable from `BLOB_STORE_ID` alone), and needs to know each document's content type to decide whether it needs PPTX→PDF conversion. Both are already known at upload time and are currently discarded.

**Files:**

- Modify: `web/src/db/schema.ts` (add `uploads.blobUrl`, `documents.blobUrl`, `documents.contentType`, `documents.pdfBlobUrl`)
- Modify: `web/src/app/api/upload/route.ts` (persist `blob.url`)
- Modify: `web/src/app/api/analyses/route.ts` (copy `blobUrl`/`contentType` from `uploads` into `documents` at creation time — never trust a client-supplied URL)
- Generated: `web/drizzle/0001_*.sql`

**Interfaces:**

- Consumes: existing `uploads`/`documents` tables from Phase 1.
- Produces: every `documents` row now carries `blob_url` (full Blob CDN URL, e.g. `https://<host>.private.blob.vercel-storage.com/<pathname>`) and `content_type`, both readable by the worker without additional API calls. `documents.pdf_blob_url` is available for the worker to populate when it records the canonical PDF for a document.

- [ ] **Step 1: Schema changes**

`web/src/db/schema.ts` — add to `uploads`:

```ts
blobUrl: text("blob_url").notNull(),
```

and to `documents`:

```ts
blobUrl: text("blob_url").notNull(),
contentType: text("content_type").notNull(),
pdfBlobUrl: text("pdf_blob_url"),
```

Run `cd web && npm run db:generate` (or the project's equivalent Drizzle-generate script) to produce `0001_*.sql`, then `npm run db:migrate` against the dev DB.

- [ ] **Step 2: Persist `blob.url` on upload**

In `web/src/app/api/upload/route.ts`, inside `onUploadCompleted`, add `blobUrl: blob.url` to the `db.insert(uploads).values({...})` call.

- [ ] **Step 3: Carry URL + content type into `documents`**

In `web/src/app/api/analyses/route.ts`, replace the count-only lookup with a helper that returns owned upload metadata:

```ts
async function listOwnedUploads(userId: string, pathnames: string[]) {
  return db
    .select({
      blobPathname: uploads.blobPathname,
      blobUrl: uploads.blobUrl,
      contentType: uploads.contentType,
    })
    .from(uploads)
    .where(and(eq(uploads.userId, userId), inArray(uploads.blobPathname, pathnames)));
}
```

Update `waitForOwnedUploads` to return those rows when `rows.length === pathnames.length` and `null` otherwise. Inside the transaction, build a `Map` by `blobPathname` and change the `tx.insert(documents)` call to copy `blobUrl` and `contentType` from the matching upload row. Never trust a client-supplied URL. If a pathname has no matching upload row, return the existing 400 response before inserting the analysis.

- [ ] **Step 4: Test**

Add an API route or DB-focused test confirming a created analysis's `documents` rows have non-null `blob_url`/`content_type` sourced from the corresponding `uploads` row, not from client input. Do not put this in `web/src/lib/validation.test.ts`; that file only exercises Zod validation and cannot prove DB persistence.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(web): persist blob url + content type from uploads through to documents"
```

---

### Task 2: Worker Blob access (static token, Node upload helper)

**Files:**

- Create: `worker/blob_helper/package.json`
- Create: `worker/blob_helper/put.mjs`
- Create: `worker/src/worker/blob.py`
- Create: `worker/tests/test_blob.py`
- Modify: `worker/pyproject.toml` (add `httpx`)

**Interfaces:**

- Consumes: `BLOB_READ_WRITE_TOKEN` env var (Railway secret, generated from the Vercel dashboard's Storage → store → Tokens tab).
- Produces: `worker.blob.download(url: str) -> bytes` and `worker.blob.upload(pathname: str, local_path: str, content_type: str) -> BlobResult` (`BlobResult` = `{url, pathname}`), usable by the ingest stage without knowing REST/SDK details.

- [ ] **Step 1: Node upload helper**

`worker/blob_helper/package.json`:

```json
{
  "name": "blob-helper",
  "private": true,
  "type": "module",
  "dependencies": {
    "@vercel/blob": "^2.5.0"
  }
}
```

`worker/blob_helper/put.mjs`:

```js
import { readFile } from "node:fs/promises";
import { put } from "@vercel/blob";

const [, , pathname, localPath, contentType] = process.argv;
const body = await readFile(localPath);
const blob = await put(pathname, body, {
  access: "private",
  contentType,
  addRandomSuffix: false,
  allowOverwrite: true,
  token: process.env.BLOB_READ_WRITE_TOKEN,
});
process.stdout.write(JSON.stringify({ url: blob.url, pathname: blob.pathname }));
```

Run `cd worker/blob_helper && npm install` to produce a checked-in `package-lock.json`.

- [ ] **Step 2: Python wrapper**

`worker/src/worker/blob.py`:

```python
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import httpx

HELPER_DIR = Path(__file__).parents[2] / "blob_helper"


@dataclass
class BlobResult:
    url: str
    pathname: str


def download(url: str) -> bytes:
    token = os.environ["BLOB_READ_WRITE_TOKEN"]
    resp = httpx.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=60)
    resp.raise_for_status()
    return resp.content


def upload(pathname: str, local_path: str, content_type: str) -> BlobResult:
    result = subprocess.run(
        ["node", "put.mjs", pathname, local_path, content_type],
        cwd=HELPER_DIR,
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ},
    )
    data = json.loads(result.stdout)
    return BlobResult(url=data["url"], pathname=data["pathname"])
```

- [ ] **Step 3: Add `httpx` dependency**

`worker/pyproject.toml` — add `"httpx>=0.27"` to `dependencies`.

- [ ] **Step 4: Test**

`worker/tests/test_blob.py` — include deterministic unit tests that do not need network access:

- monkeypatch `httpx.get` and assert `download()` sends `Authorization: Bearer <token>` and returns response bytes after calling `raise_for_status()`
- monkeypatch `subprocess.run` and assert `upload()` invokes `node put.mjs <pathname> <local_path> <content_type>` in `HELPER_DIR`, parses stdout JSON, and returns `BlobResult(url=..., pathname=...)`

Also add an optional integration test marked with `skipif` when `BLOB_READ_WRITE_TOKEN` is unset; when the token is present, round-trip a small temp file through `upload()` then `download()` and assert byte equality. CI/local dev without the secret must still pass the deterministic tests.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(worker): add Blob download/upload wrapper (static token + Node put helper)"
```

---

### Task 3: Docker image — LibreOffice, PyMuPDF, Node, Anthropic SDK

**Files:**

- Modify: `worker/Dockerfile`
- Modify: `worker/pyproject.toml` (add `pymupdf`, `anthropic`, `pydantic`)

**Interfaces:**

- Consumes: nothing new.
- Produces: a worker image that can run `libreoffice --headless --convert-to pdf`, import `fitz` (PyMuPDF), call the Anthropic API, and shell out to `node worker/blob_helper/put.mjs`.

- [ ] **Step 1: Add dependencies**

`worker/pyproject.toml` — add to `dependencies`: `"pymupdf>=1.24"`, `"anthropic>=0.40"`, `"pydantic>=2"`.

- [ ] **Step 2: Update Dockerfile**

```dockerfile
FROM python:3.12-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY blob_helper ./blob_helper
RUN cd blob_helper && npm install --omit=dev

COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

CMD ["python", "-m", "worker.main"]
```

- [ ] **Step 3: Verify locally**

```bash
cd worker
docker build -t agentic-review-worker .
docker run --rm agentic-review-worker python -c "import fitz, anthropic, pydantic; print('ok')"
docker run --rm agentic-review-worker libreoffice --headless --version
docker run --rm agentic-review-worker node --version
docker run --rm agentic-review-worker test -f blob_helper/node_modules/@vercel/blob/package.json
```

Expected: no import errors; LibreOffice reports a version; Node reports v20+; `@vercel/blob` is installed in `blob_helper/node_modules`.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore(worker): add LibreOffice, PyMuPDF, Node, Anthropic SDK to worker image"
```

---

### Task 4: `pages` table

**Files:**

- Modify: `web/src/db/schema.ts`
- Generated: `web/drizzle/0002_*.sql`

**Interfaces:**

- Consumes: `documents` table.
- Produces: `pages` table the ingest/vision/script-alignment stages write into and later phases (matrix, findings) read from.

- [ ] **Step 1: Add the table**

`web/src/db/schema.ts` — add `uniqueIndex` to the existing `drizzle-orm/pg-core` import:

```ts
import {
  boolean,
  integer,
  pgEnum,
  pgTable,
  text,
  timestamp,
  uniqueIndex,
  uuid,
} from "drizzle-orm/pg-core";
```

Then add the table:

```ts
export const pages = pgTable(
  "pages",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    documentId: uuid("document_id")
      .notNull()
      .references(() => documents.id, { onDelete: "cascade" }),
    pageNo: integer("page_no").notNull(),
    text: text("text").notNull(),
    imageBlobPathname: text("image_blob_pathname").notNull(),
    imageBlobUrl: text("image_blob_url").notNull(),
    visionSummary: text("vision_summary"),
    scriptText: text("script_text"),
  },
  (table) => [
    uniqueIndex("pages_document_id_page_no_unique").on(
      table.documentId,
      table.pageNo,
    ),
  ],
);
```

`scriptText` isn't in the spec's abridged column list but is required by stage 3 ("attach the dense prose to each slide record") — it lives on the deck's page rows, nullable, populated only when a script is present.
The unique `(document_id, page_no)` index makes "one slide = one page = one citation anchor" enforceable and keeps script alignment updates unambiguous.

- [ ] **Step 2: Generate + apply migration**

```bash
cd web && npm run db:generate && npm run db:migrate
```

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "feat(web): add pages table for per-page text/image/vision/script data"
```

---

### Task 5: Ingest stage — convert, render, extract

**Files:**

- Create: `worker/src/worker/ingest.py`
- Create: `worker/tests/test_ingest.py`
- Create: `worker/tests/fixtures/sa5_rfq.pdf` (copy of `Amendment 4_Attachment 5 - SA5 Instructions and Evaluation Process.pdf`)
- Create: `worker/tests/fixtures/ctg_deck.pdf` (copy of `SA5_Phase2_Orals_CTG_v1 - draft template (2).pdf`)

**Interfaces:**

- Consumes: `documents` rows for one analysis (`blob_url`, `content_type`, `kind`), `worker.blob`.
- Produces: one `pages` row per page for every non-script document; `documents.pdf_blob_pathname`/`pdf_blob_url`/`page_count` populated.

- [ ] **Step 1: Implement `ingest_document`**

`worker/src/worker/ingest.py` — for each non-`script` document of an analysis:

1. Download original via `blob.download(document.blob_url)` to a temp file.
2. If `content_type` is the PPTX MIME type, run `libreoffice --headless --convert-to pdf --outdir <tmpdir> <file>` (subprocess, check return code, fail the stage with the captured stderr on non-zero exit) to get a local PDF; otherwise the downloaded file already is the PDF.
3. Open the PDF with PyMuPDF (`fitz.open(path)`). For each page: render to PNG at 150 DPI (`page.get_pixmap(dpi=150)`), extract native text (`page.get_text()`).
4. Assert each rendered PNG is under ~4 MB (headroom below the 4.5 MB cap); raise a clear error naming the offending page if not.
5. Upload the page PNG via `blob.upload(f"analyses/{analysis_id}/pages/{document_id}/{page_no}.png", ...)`; insert a `pages` row with the native text + returned pathname/url.
6. Record the canonical PDF for the document: if conversion happened, upload the converted PDF via `blob.upload(f"analyses/{analysis_id}/converted/{document_id}.pdf", ...)` and update `documents.pdf_blob_pathname`/`pdf_blob_url` from the returned Blob result; if the original was already a PDF, set `documents.pdf_blob_pathname = documents.blob_pathname` and `documents.pdf_blob_url = documents.blob_url`. Always update `documents.page_count`.

- [ ] **Step 2: Copy real PDF fixtures**

```bash
mkdir -p worker/tests/fixtures
cp "/Users/bryandang/Downloads/Amendment 4_Attachment 5 - SA5 Instructions and Evaluation Process.pdf" worker/tests/fixtures/sa5_rfq.pdf
cp "/Users/bryandang/Downloads/SA5_Phase2_Orals_CTG_v1 - draft template (2).pdf" worker/tests/fixtures/ctg_deck.pdf
```

These fixtures are required before writing the redline/text-fidelity and reading-order tests below; do not defer the copy to Task 9.

- [ ] **Step 3: Redline / text-fidelity test**

`worker/tests/test_ingest.py` — using `worker/tests/fixtures/sa5_rfq.pdf`, assert the extracted text for the page(s) containing Amendment 4's tracked-changes redlines does **not** interleave strikethrough and inserted text in a way that garbles requirement numbering (assert specific known substrings from the redlined section appear intact and in the right relative order). If PyMuPDF's default extraction does interleave them, this test is what catches it — don't pre-guess a fix, let the test drive whether one is needed.

- [ ] **Step 4: Reading-order test**

Using `worker/tests/fixtures/ctg_deck.pdf`, assert the page containing the "Tooling & Access" / "GATE 3-4" card pair extracts with those two strings adjacent (not interleaved with the neighboring card's text) — this is the concrete multi-column layout regression test flagged during design review.

- [ ] **Step 5: PPTX conversion test**

Author a minimal synthetic `.pptx` fixture (2–3 slides, plain text) — the two real fixtures are already PDF exports, so this is the only fixture that actually exercises the LibreOffice conversion path. Assert conversion produces a PDF with an extractable (non-empty) text layer per slide.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(worker): ingest stage — pptx conversion, page rendering, native text extraction"
```

---

### Task 6: Vision pass

**Files:**

- Create: `worker/src/worker/vision.py`
- Create: `worker/tests/test_vision.py`

**Interfaces:**

- Consumes: `pages` rows for `deck` documents, `ANTHROPIC_API_KEY` env var.
- Produces: `pages.vision_summary` populated for every deck page.

- [ ] **Step 1: Implement**

`worker/src/worker/vision.py` — for each `deck` document's page rows, call `claude-opus-4-8` with the page image (base64, fetched via `blob.download(image_blob_url)`) and native text, prompting for an enriched description capturing what text extraction misses (org charts, schedule bars, diagrams). Use `client.messages.parse()` with a small Pydantic model (`class VisionSummary(BaseModel): summary: str`) per the locked structured-output decision. Write the result to `pages.vision_summary`.

- [ ] **Step 2: Handle SDK edge cases**

Per spec §6: rely on SDK auto-retry for 429/5xx; explicitly handle `refusal` and `max_tokens` stop reasons by failing that page's vision call with a clear message rather than silently storing a truncated/empty summary.

- [ ] **Step 3: Test**

Mock the Anthropic client in `worker/tests/test_vision.py`; assert every deck page gets a call (no routing heuristic — this is a hard product requirement worth a direct assertion, not just a happy-path check), and that a `refusal` stop reason surfaces as a stage failure rather than a silently-empty summary.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "feat(worker): vision pass over every deck page"
```

---

### Task 7: Script alignment

**Files:**

- Create: `worker/src/worker/script_align.py`
- Create: `worker/tests/test_script_align.py`
- Create: `worker/tests/fixtures/script_marked.txt`
- Create: `worker/tests/fixtures/script_unmarked.txt`

**Interfaces:**

- Consumes: the `script` document (if present) for an analysis, `worker.blob.download(script.blob_url)`, already-ingested `pages` rows for the `deck` document.
- Produces: `pages.script_text` populated on matching deck pages; a clear stage failure if the script has any unmarked section.

- [ ] **Step 1: Parser**

`worker/src/worker/script_align.py` — split the downloaded script text on a `Slide N:` marker regex (case-insensitive, tolerant of a little surrounding whitespace/punctuation but not silently fuzzy — this must fail loud, not guess). Return `dict[int, str]` (slide number → prose). If the text contains any non-whitespace content before the first marker, the parse finds zero markers, a marker is duplicated, or a marker's prose section is empty, raise a `ScriptAlignmentError` with a message identifying what's wrong (spec: "auto-alignment is out of scope").

- [ ] **Step 2: Attach to pages**

For each `(slide_no, text)`, find the deck's `pages` row with matching `page_no` and update `script_text`. If a marker references a slide number with no corresponding page, raise `ScriptAlignmentError` (this indicates a script/deck mismatch — a real product risk given the CTG deck's own internal slide numbering plus an appendix/backup section, worth failing loudly on rather than silently dropping).

- [ ] **Step 3: Test**

`script_marked.txt` — a small valid fixture with 3 `Slide N:` sections; assert clean parse and correct attachment. `script_unmarked.txt` — plain prose with no markers; assert `ScriptAlignmentError` is raised with a message a user could act on (not a stack trace). Add a duplicate-marker test (`Slide 2:` appears twice) and an out-of-range-marker test (`Slide 99:` with a three-page deck) so the parser cannot silently overwrite or drop narration.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "feat(worker): script alignment on explicit Slide N: markers"
```

---

### Task 8: Wire the real ingest stage into the pipeline

**Files:**

- Modify: `worker/src/worker/pipeline.py`
- Modify: `worker/tests/test_main.py` (or add `worker/tests/test_pipeline.py`)

**Interfaces:**

- Consumes: `ingest.py`, `vision.py`, `script_align.py`.
- Produces: `analyses.stage` progresses through `ingest` → `vision` → `script_align` → `review` (stub) → `report` (stub); `stage_detail` carries live progress (e.g. `"page 4/18"`).

- [ ] **Step 1: Replace the stub `ingest` entry**

In `worker/src/worker/pipeline.py`, replace the first `STUB_STAGES` tuple with real calls: fetch the analysis's `documents` rows, call `ingest.ingest_document(...)` per document with `jobs.update_stage(conn, analysis_id, "ingest", f"page {i}/{n} — {doc.display_name}")` progress calls; then `vision.run_vision_pass(...)` under stage `"vision"`; then, if a `script` document exists, `script_align.align_script(...)` under stage `"script_align"` (skip this stage entirely — don't emit it — if no script was uploaded, since script is optional per the upload schema). Leave the `("review", ...)` and `("report", ...)` stub entries untouched.

- [ ] **Step 2: Failure surfacing**

Confirm (per Phase 1's existing `main.tick` try/except) that any `ScriptAlignmentError`, LibreOffice non-zero exit, or oversized-image assertion propagates up as a caught `Exception` and lands in `analyses.error`. The failed stage is represented by the existing `analyses.stage` value from the last `jobs.update_stage(...)` call, so each real stage must call `update_stage` before doing work that can fail; no new exception handling is needed in `pipeline.py` itself if the lower-level modules raise clearly-named exceptions.

- [ ] **Step 3: Integration test**

Using the real `worker/tests/fixtures/ctg_deck.pdf` as the `deck` document and `worker/tests/fixtures/sa5_rfq.pdf` as `solicitation_base` (mocking the Anthropic vision call), run `pipeline.run_pipeline` end-to-end against a test-DB analysis and assert: `pages` rows exist for both documents with non-empty `text`, `image_blob_pathname` set, and `vision_summary` set only for the deck's pages.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "feat(worker): wire ingest/vision/script-alignment into the pipeline"
```

---

### Task 9: Fixture verification + full test sweep

**Files:**

- Verify: `worker/tests/fixtures/sa5_rfq.pdf`, `worker/tests/fixtures/ctg_deck.pdf` (added in Task 5)
- Modify: `.gitattributes` (optional: mark PDFs as binary to avoid line-ending mangling)

**Interfaces:**

- Consumes: nothing new.
- Produces: a green `pytest` run covering every module added in Tasks 2–8, using the real fixtures for the two regression tests called out in Task 5.

- [ ] **Step 1: Verify fixtures are present**

```bash
test -s worker/tests/fixtures/sa5_rfq.pdf
test -s worker/tests/fixtures/ctg_deck.pdf
```

- [ ] **Step 2: Full sweep**

```bash
cd worker && pytest -v
```

Expected: every test from Tasks 2–8 passes, including the redline-fidelity and reading-order tests against the real fixtures.

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "test(worker): commit real SA5/CTG fixtures for ingestion regression tests"
```

---

### Task 10: Deploy and ingestion smoke test

**Files:**

- Modify: `web/.env.production.notes.md` (add the two new env vars)

**Interfaces:**

- Consumes: everything above.
- Produces: a live Railway worker that can actually ingest a real upload, verified end-to-end.

- [ ] **Step 1: Railway env vars**

Add to the Railway worker service: `BLOB_READ_WRITE_TOKEN` (the static token generated for this store), `ANTHROPIC_API_KEY`.

- [ ] **Step 2: Update env var matrix**

Add both to the table in `web/.env.production.notes.md`, noting `BLOB_READ_WRITE_TOKEN` is Railway-only (worker), not shared with the Vercel web app.

- [ ] **Step 3: Redeploy**

Push the updated `worker/Dockerfile` and code; confirm the Railway build succeeds (LibreOffice + Node install steps add real build time — expect several minutes).

- [ ] **Step 4: Production smoke test**

1. Upload a small real solicitation PDF + deck (PPTX or PDF) + optionally a marked script through the production web app.
2. Watch `/analysis/<id>`: stage should progress `ingest` → `vision` → (`script_align` if a script was included) → `review` (stub) → `report` (stub) → `complete`.
3. Query the Railway Postgres directly (`psql`) to confirm `pages` rows exist with non-null `text` and `image_blob_pathname`, and `vision_summary` populated for deck pages.
4. Spot-check one `image_blob_url` by curling it with the static token to confirm the image is fetchable and under the size cap.

- [ ] **Step 5: Commit**

```bash
git add web/.env.production.notes.md
git commit -m "docs: add BLOB_READ_WRITE_TOKEN and ANTHROPIC_API_KEY to production env matrix"
```

---

## Phase 2 exit criteria

- All worker tests green (`cd worker && pytest`), including the two real-fixture regression tests (redline text fidelity, multi-column reading order).
- A real analysis run in production progresses through `ingest` → `vision` → (optional `script_align`) → stub `review`/`report` → `complete`, with `pages` rows fully populated.
- Phase 3 (Extraction/Matrix) starts by reading `documents`/`pages` as its input and replacing the stub `review` stage's first half (requirement extraction + traceability mapping) — no other Phase 2 surface changes.
