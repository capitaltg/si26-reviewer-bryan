# AI Proposal Review Board — System Design

**Date:** 2026-07-02
**Status:** Approved
**Source requirements:** [`GOALS.md`](../../../GOALS.md)

## Summary

An advisory-only web tool that reviews a GovCon oral-proposal package (PowerPoint deck + optional per-slide narration script) against the actual solicitation and produces grounded, citation-backed findings from three specialized AI reviewers. It never edits or generates proposal content. This document covers the engineering design; product requirements, scope cuts, and success criteria live in `GOALS.md` and are not restated here.

## Locked decisions

| Decision | Choice |
| --- | --- |
| Stack | Next.js frontend + Python worker |
| Hosting | Vercel (web) + Railway (worker, Postgres), deployed from day one |
| Auth | Company Keycloak via `getgaleo.com`; every analysis is tied to an authenticated user |
| LLM | Claude API only — `claude-opus-4-8`, adaptive thinking, structured outputs |
| Job orchestration | Postgres job table, worker polls (no Redis/Celery) |
| File storage | Vercel Blob, private |
| Timeline | ~6 weeks, solo + Claude Code, ending in demo day |

## 1. System shape

Core pieces:

- **`web/` — Next.js app (Vercel).** Three screens: upload → status → report. API routes read/write Postgres via Drizzle ORM. Issues scoped tokens for direct browser-to-Blob uploads.
- **`worker/` — Python service (Railway, Docker).** A plain poller with no HTTP surface. Claims queued analyses from Postgres, runs the pipeline, writes progress and results back. Container image includes LibreOffice headless for PPTX→PDF conversion.
- **Postgres (Railway).** Single source of truth: job state, documents, extracted requirements, traceability matrix, findings. The `analyses` row doubles as the progress feed the status screen polls.
- **Vercel Blob (private).** Uploaded originals, converted PDFs, rendered per-page PNG images. The worker downloads and uploads blobs with server-side credentials; the browser never receives private Blob URLs directly.
- **Auth boundary.** The web app authenticates users through the company Keycloak at `getgaleo.com`. API routes enforce analysis ownership before returning status, report data, upload tokens, or rendered source pages. The worker authenticates to Blob with server-side credentials only.

Claude API usage: `claude-opus-4-8` for all passes (extraction, per-slide vision, reviewers, orchestration), adaptive thinking, structured outputs via `client.messages.parse()` with Pydantic models, streaming for long outputs. The solicitation text is placed as a cached prompt prefix (`cache_control`) so the three reviewer calls reuse it at cache-read pricing.

### Data flow

1. Authenticated browser uploads a solicitation package (base PDF plus optional amendments/Q&A/attachments), deck (PPTX or PDF), and optional narration script (TXT) directly to Vercel Blob using a scoped token from a Next.js route.
2. Next.js inserts an `analyses` row (`status=queued`) tied to the authenticated user, persisted consent/distribution-marking attestations, and the uploaded blob pathnames.
3. Worker claims the job in a transaction using a CTE/subquery: select one queued row `FOR UPDATE SKIP LOCKED`, update it to `running`, and return the claimed analysis. This avoids duplicate claims across worker instances.
4. On completion (`status=complete`) the report screen reads the matrix and findings from Postgres after ownership checks; citation clicks call a protected API route that streams private Blob images/documents through the web app rather than exposing direct Blob URLs.

## 2. Pipeline stages (worker)

Each stage writes `analyses.stage` + `stage_detail` (e.g. "extracting requirements… 12/34 mapped"). This is both the status UI and the demo's progress narration.

1. **Ingest.** Download files. PPTX→PDF via `libreoffice --headless --convert-to pdf` (the text layer must survive — verified against a real export in week 1; if a real export arrives rasterized, the vision pass already covers every slide, so degradation is graceful). Render every page of the solicitation package and deck to PNG (PyMuPDF) at a pinned ~150 DPI, keeping each image comfortably under the ~4.5 MB Vercel function response cap the protected source-render route must fit within. Extract native per-page text (PyMuPDF). Upload page images to Blob. One slide = one page = one citation anchor; solicitation citations include document kind/name plus page so amendments and attachments remain distinguishable.
2. **Vision pass.** Every deck slide is sent to Claude with its rendered image + native text; output is an enriched slide description capturing what text extraction cannot (org-chart relationships, schedule bars, architecture diagrams). Every slide goes through — no routing heuristic, per GOALS.
3. **Script alignment.** Parse the narration file on explicit `Slide N:` markers; attach the dense prose to each slide record. Unmarked scripts are rejected with a clear error (auto-alignment is out of scope).
4. **Requirement extraction.** One structured pass over the full solicitation package (1M context accommodates whole documents) producing: Section L requirements, Section M evaluation factors with stated weights, slide/page/formatting limits, SOW/PWS scope statements, amendments/Q&A changes, and FAR/DFARS clauses incorporated by reference. Every record carries a document+page citation and, where applicable, a supersedes/amends relationship.
5. **Traceability mapping.** Only *effective* requirements enter the mapping — a requirement with a successor (something whose `supersedes_requirement_id` points at it) is stored and displayed as superseded, linked to its replacement, but generates no coverage row and no gap findings. Each effective requirement is mapped against slide content + script: `covered / partial / missing`, with slide citations and a short rationale. Persisted as its own table — this is the anchor feature.
6. **Three reviewers.** Three separate calls, each grounded in distinct data (not just distinct personas):
   - **Compliance Officer:** extracted Section L requirements, limits/formatting rules, cited FAR/DFARS clauses + the matrix.
   - **Technical/SME:** SOW/PWS scope + the deck's technical content (vision-enriched) + script + the matrix.
   - **Government Evaluator:** Section M factors with weights, solicitation-specific rating definitions when present, public adjectival rating definitions only as fallback + the matrix.
   Findings are schema-enforced (Pydantic → `messages.parse`): reviewer, severity, confidence, two-sided evidence citation (solicitation section+page, deck slide/script location), description, suggested improvement.
7. **Citation verification (non-LLM).** Every finding's cited solicitation document/page and proposal slide/script location must exist. Quoted requirement text must appear on the cited solicitation page (normalized string match against extracted text), and quoted proposal evidence must appear in native slide text, aligned script text, or the persisted vision summary for that slide. Each finding records its evidence **provenance** (`native_text` / `script` / `vision_summary`): vision summaries are themselves LLM output, so evidence that only verifies against one is weaker grounding — it is accepted (diagram content has no native text) but visibly tagged rather than treated as equivalent. Missing/partial findings use a different evidence shape: requirement citation plus the searched proposal scope and rationale, never a fake proposal citation. Failures are dropped or flagged `unverified`. This is the concrete mechanism behind "grounded or nothing"; the eval reports solicitation-side and proposal-side pass rates separately, with the proposal side broken out by provenance.
8. **Orchestrate.** LLM clustering pass over finding summaries for semantic dedupe (cluster ids persisted; findings retain reviewer of origin). Priority ordering by Section M weighting. Cross-reviewer disagreement detection — surfaced as a signal, never silently resolved. Executive summary generated last.

## 3. Data model (Postgres)

Essential tables (columns abridged):

- `users` — id, keycloak_sub, email, created_at
- `analyses` — id, user_id, status (`queued/running/complete/failed`), stage, stage_detail, error, consent_llm_transit, distribution_attestation, locked_by, locked_at, created_at, expires_at
- `documents` — analysis_id, kind (`solicitation_base/solicitation_amendment/solicitation_q_and_a/solicitation_attachment/deck/script`), display_name, blob_pathname, pdf_blob_pathname, page_count
- `pages` — document_id, page_no, text, image_blob_pathname, vision_summary
- `requirements` — analysis_id, document_id, source (`L/M/SOW/FAR/limits/amendment`), ref (e.g. "L.3.2"), text, page_no, weight, supersedes_requirement_id
- `mappings` — requirement_id, status (`covered/partial/missing`), slide_refs (jsonb), rationale
- `findings` — analysis_id, reviewer, severity, confidence, requirement_id (nullable), evidence (jsonb: solicitation citation + proposal citation), evidence_provenance (`native_text/script/vision_summary`), description, suggestion, cluster_id, verification (`verified/unverified/dropped`)
- `summaries` — analysis_id, executive summary text, disagreement notes (jsonb)

## 4. Web app

- **Auth** — all screens require login through the company Keycloak at `getgaleo.com`. API routes validate the session and enforce `analysis.user_id` ownership.
- **`/` Upload** — solicitation package uploader (base solicitation required; amendments/Q&A/attachments optional), deck dropzone, optional script dropzone; the data-handling sign-off checklist (owner consent to LLM transit; distribution-markings confirmation — Proprietary / SSS / CUI / ITAR = stop) must be checked before submit and is persisted on the analysis.
- **`/analysis/[id]` Status** — polls an API route (~2s) for stage + stage_detail after ownership check; renders the running narration.
- **`/analysis/[id]/report`** — traceability matrix (requirement rows × coverage status), findings grouped by reviewer with severity/confidence chips, an evidence-provenance badge on vision-grounded findings, disagreement callouts, executive summary. The killer interaction: click any citation → modal calls a protected source-render route that streams the rendered page/slide image from private Blob.
- **Retention** — Vercel cron hits a cleanup route that deletes expired analyses (rows + blobs). Default retention 7 days, configurable.

UI: App Router, Tailwind + shadcn/ui. Auth is in MVP because proposal drafts are sensitive; unguessable URLs are not an acceptable access-control boundary.

## 5. Eval harness (`eval/`, built week 1)

- Ground truth in-repo as YAML: hand-extracted Section L/M from one real unclassified SAM.gov solicitation; authored deck + script fixtures with 8–10 seeded, labeled defects.
- A CLI (`python -m eval.run`) imports the pipeline as a library (same code the worker runs, no HTTP) and reports:
  - extraction precision/recall vs. hand-extracted requirements
  - finding precision/recall vs. seeded defects
  - solicitation-side and proposal-side citation-verification pass rates (proposal side broken out by evidence provenance)
- Results appended to a tracked log so precision/recall trends across iterations — presented as an eval at demo day, not a vibe.

## 6. Error handling & testing

- Stage-level try/except → `status=failed` + failing stage + error message; UI shows exactly where it died.
- LLM calls: SDK auto-retries for 429/5xx; explicit handling for `refusal` and `max_tokens` stop reasons; `messages.parse` schema-validation retry loop.
- Worker crash mid-job: jobs stuck in `running` past a timeout are re-queued once, then failed. Claiming uses a transactional `FOR UPDATE SKIP LOCKED` pattern and records `locked_by`/`locked_at` so retries are auditable.
- Pytest for deterministic units: script parser, citation verifier, PDF text extraction on fixtures, coverage-status logic. The eval harness serves as the integration test. No browser-automation tests for MVP.

## 7. Six-week arc

| Week | Focus |
| --- | --- |
| 1 | Repo scaffold, deploys live (Vercel + Railway), Keycloak auth (Auth.js provider + ownership middleware) so every later feature lands behind it, ingestion pipeline (PPT→PDF→images→text), eval ground truth authored |
| 2 | Requirement extraction + traceability mapping; first extraction precision/recall numbers |
| 3 | Three reviewers + citation verification; first finding precision/recall numbers |
| 4 | Web app end-to-end: upload → status → report with click-to-source |
| 5 | Orchestrator (dedupe, prioritization, disagreement, exec summary); retention/cleanup; deploy hardening |
| 6 | Eval iteration, messy-solicitation stress test (amendments, cross-references), demo prep |

Detailed task breakdown lives in the implementation plan (next step), not here.

## Key risks carried into implementation

- **Extraction quality is the make-or-break** (per GOALS) — weeks 2–3 get the most slack; orchestration cleverness is cut first if behind.
- **LibreOffice text-layer fidelity** on real exports — verified week 1; vision pass is the fallback.
- **Persona theater** — if reviewer grounding converges, collapse to one structured reviewer and reinvest in extraction (explicit GOALS mitigation).
- **Severity/confidence labels are uncalibrated** — displayed as reviewer opinion; never presented as measured probabilities.
