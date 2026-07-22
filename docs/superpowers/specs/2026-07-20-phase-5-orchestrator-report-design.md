# Phase 5: Orchestrator, Report Finalization, and Report Screen Design

## Goal

Replace the worker's stub `report` stage with the real stage-8 orchestrator,
persist an executive summary and cross-reviewer disagreement notes to a new
`summaries` table, and build the `/analysis/[id]/report` screen with
click-to-source. This closes the loop: upload → status → report becomes fully
walkable and demoable. After Phase 5 there are no stub stages left in the
pipeline.

Explicitly deferred to Phase 6: the evaluation harness (`eval/`), retention /
cleanup cron, deploy hardening, the messy-solicitation stress test, and demo
prep.

## Scope

The worker reads the Phase-4 output (persisted `findings`, plus their
`requirements` and `mappings`) and runs the `orchestrate` stage in three steps
within one job: load and filter the inputs, make and validate one structured
call, then persist the complete replacement atomically. The existing finalize
path marks the analysis `complete` only after that stage returns. The web app
gains the terminal report screen, links the completed status view to it, and
adds a protected source-render route that powers click-to-source.

## Worker: `orchestrate` stage (replaces the `report` stub)

The stub `("report", "assembling report (stub)")` entry in
`worker/src/worker/pipeline.py` is removed and `STUB_STAGES` becomes empty. A
real `orchestrate` stage runs after `review`, with
`jobs.update_stage(conn, analysis_id, "orchestrate", "deduplicating findings and assembling report")`
immediately before the call. The stage lives in a new
`worker/src/worker/orchestrate.py` with a `run_orchestrate(conn, analysis_id)`
entry point, mirroring how `reviewers.run_review` is structured and called.

### Inputs

The worker loads all persisted `findings` for the analysis (with `reviewer`,
`finding_kind`, `severity`, `confidence`, `requirement_id`, `evidence`,
`description`, `suggestion`, and `verification`), joined to `requirements` (for
the Section M `weight`) and `mappings` (for the matrix view). Only findings
whose `verification = 'verified'` enter orchestration or the report. This
preserves Phase 4's grounded-or-nothing contract: `unverified` and `dropped`
rows remain audit data, are not clustered, are not summarized, and are not
shown by the report. On every orchestration run their `cluster_id` is cleared
and left null.

### One structured orchestration call

A single forced-tool call, named `record_orchestration`, returns in one pass:

- **cluster assignments** — one positive integer `cluster_key` for every
  verified finding handle, grouping semantic duplicates across reviewers.
  Findings keep their reviewer of origin; only `findings.cluster_id` is
  written. The database column is UUID, so the worker maps each distinct
  `cluster_key` to a freshly generated UUID for this run. The UUID is an
  internal run-local grouping key, not a stable identity across retries; all
  verified findings receive one, including singleton clusters, while
  unverified/dropped findings remain null.
- **disagreement notes** — cross-reviewer conflicts, surfaced as a signal and
  never silently resolved. A note is required when findings in one cluster
  from different reviewers materially disagree on finding kind, severity, or
  substantive assessment; identical conclusions do not create a note.
- **executive summary** — generated with the full deduped picture in view.

The Pydantic-backed tool schema is:

```json
{
  "cluster_assignments": [{ "finding_handle": 1, "cluster_key": 1 }],
  "disagreement_notes": [{ "finding_handles": [1, 2], "note": "..." }],
  "summary": "..."
}
```

`cluster_assignments` must contain exactly one assignment for every input
finding handle and no unknown or duplicate handles. `disagreement_notes` may
be empty; every note must reference at least two findings from the same
cluster and at least two distinct reviewers. The worker resolves handles to
finding UUIDs before persistence and stores notes as JSON objects with
`finding_ids`, `reviewers`, and `note`, for example:
`[{"finding_ids":["...","..."],"reviewers":["compliance","evaluator"],"note":"..."}]`.
The `summary` and each note string must be non-empty after trimming; the notes
array itself may be empty. Bound the schema with
`MAX_DISAGREEMENT_NOTES = 50`, `MAX_NOTE_CHARS = 2_000`, and
`MAX_SUMMARY_CHARS = 12_000`. Invalid, incomplete, or contradictory
assignments fail the stage rather than being partially persisted.

The prompt assigns deterministic 1-based finding handles in `findings.id`
order and includes each finding's reviewer, kind, severity, confidence,
requirement ref/weight, evidence citations, description, and suggestion.
Document-derived strings are delimited as untrusted content and are never
allowed to override the orchestration instructions. The input is measured
before the call with `MAX_ORCHESTRATE_INPUT_CHARS = 400_000`; the stage fails
with an actionable error if that guardrail is exceeded. There is no output
chunking in this phase.

The call **reuses the reviewers' existing Bedrock forced-tool engine** (the
`reviewers.py` call/validation pattern with a Pydantic-backed tool schema), not
`messages.parse`: the worker talks to Anthropic Bedrock via classic
`InvokeModel`, which is how the reviewers already run. Use
`MAX_TOKENS = 16_384`, force `record_orchestration`, disable parallel tool
use, and trust only a single matching tool-use block with `stop_reason =
'tool_use'`. The current reviewers engine validates once and raises on invalid
tool input; Phase 5 does not claim a validation-retry loop that does not yet
exist. SDK transient retries remain in effect, while refusal, truncation, an
invalid schema, or any other stop reason fails the stage.

### Deterministic priority ordering

Priority ordering is computed in code, not by the LLM: after clustering, each
finding is sorted by this key, in descending priority:

1. parseable numeric Section M weight first, with the numeric value highest
   first;
2. findings with no requirement, no weight, or an unparseable weight after
   weighted findings;
3. severity rank `high`, then `medium`, then `low`;
4. the finding UUID in ascending lexical order as the final tiebreaker.

Weight parsing extracts the first percentage token when one is present;
otherwise it extracts the first numeric token, preserving decimal values. It
does not ask the LLM to rank. The same key is applied within each reviewer
group in the report. Ordering is applied at read time by the web app rather
than persisted, so it stays auditable and re-derivable.

### Persistence and retry-safety

The stage is idempotent, matching Phase 3/4. On every run it, within the job's
transaction scope:

1. clears prior `cluster_id`s for the analysis (`SET cluster_id = NULL`),
2. writes the new cluster assignments, and
3. upserts the single `summaries` row for the analysis
   (`ON CONFLICT (analysis_id) DO UPDATE`).

A re-run therefore fully replaces prior orchestration output with no
duplication. Because the worker connection is autocommit and the three writes
run inside one explicit `conn.transaction()` block, a failure rolls back both
cluster write-back and the summary upsert. The existing `jobs.py` finalize
(`status = 'complete', stage = 'done', stage_detail = NULL`) is unchanged and
runs after `orchestrate` returns.

## Data model delta

One new table (columns abridged), anticipated by the master design's §3
`summaries`:

- `summaries` — `id`, `analysis_id` (unique, FK → `analyses`, `ON DELETE
  CASCADE`), `summary_text` (non-empty text), `disagreement_notes` (non-null
  jsonb array of the resolved `{finding_ids, reviewers, note}` objects),
  `created_at`.

`findings.cluster_id` already exists in the schema — no migration needed there.
A single new Drizzle migration adds `summaries`, and the Drizzle schema in
`web/src/db/schema.ts` gains the matching table definition. The worker reads and
writes `summaries` / `findings.cluster_id` directly via SQL, consistent with how
it already reads and writes the other tables.

## Web: `/analysis/[id]/report` screen

A new route `web/src/app/analysis/[id]/report/page.tsx`, rendered as a server
component. Unlike the status view it is a **terminal state — it reads once and
does not poll**. It performs the same session + `analysis.user_id` ownership
check as the existing routes. If the analysis status is not `complete` it
redirects back to `/analysis/[id]` (the status screen).

It reads the analysis, `documents` (including the single deck document),
`requirements`, `mappings`, `findings`, and the `summaries` row, and renders:

- **Traceability matrix** — one row per *effective* requirement (a requirement
  with a successor is shown as superseded and linked to its replacement, and
  generates no coverage row), with coverage status (`covered` / `partial` /
  `missing`), slide references, and rationale.
- **Verified findings grouped by reviewer**, priority-ordered per the
  deterministic ordering above, with severity and confidence chips, visual
  grouping of findings that share a `cluster_id`, and an
  **evidence-provenance badge** on findings grounded only in a vision summary.
  `unverified` and `dropped` findings are intentionally absent from this
  screen; exposing their audit rows is deferred with the evaluation harness.
- **Disagreement callouts** from `summaries.disagreement_notes`.
- The **executive summary** from `summaries.summary_text`.

The server page owns the authenticated data load; it may pass the prepared
report model to a small client component for modal open/close and image
loading. UI follows the existing App Router + Tailwind conventions in `web/`;
there is no existing shadcn dependency, so Phase 5 does not add one solely for
this screen.

The completed state in `web/src/app/analysis/[id]/status-view.tsx` links to
`/analysis/[id]/report`; it does not auto-navigate, so a user can still inspect
the terminal status.

## Web: click-to-source

- **`GET /api/analyses/[id]/source`** (new route under
  `web/src/app/api/analyses/[id]/`) — takes the citation target (document +
  page for a solicitation page, or the deck document + slide/page) as query
  parameters named `documentId` and `page`. It validates the UUID and positive
  page number, authenticates the session, verifies `analyses.user_id`, and
  queries `pages JOIN documents` with both `documents.id = documentId` and
  `documents.analysis_id = analyses.id`. The route accepts no pathname or URL
  from the client. It permits only solicitation documents and the deck, looks
  up the matched `image_blob_pathname`, and calls the server-side private Blob
  SDK (`get(pathname, { access: "private" })`) to stream the PNG. A missing or
  cross-analysis target returns 404; a Blob fetch failure returns 502. Images
  are already uploaded during ingest, so no rendering happens here. The
  streamed response stays under the ~4.5 MB Vercel function response cap
  enforced by `ingest.MAX_PAGE_PNG_BYTES`.
- Citation chips on matrix rows and on findings open a **modal** that calls this
  route and displays the rendered source page/slide. A citation whose target
  cannot be resolved renders as static (non-clickable) text rather than a broken
  link. Solicitation evidence supplies its persisted document id and page;
  matrix slide references and finding proposal slides use the analysis's
  persisted deck document id, never a client-supplied blob URL.

## Error handling and testing

Consistent with the master design's §6 and the Phase 3/4 approach:

- The `orchestrate` stage uses the existing `main.tick` pipeline failure
  boundary. Because `pipeline.py` writes `stage = 'orchestrate'` immediately
  before calling `run_orchestrate`, `jobs.fail_job` leaves that failing stage in
  place while setting `status = 'failed'` and recording the error. The report
  screen is unreachable until a re-run succeeds.
- The orchestration LLM call uses the reviewers' existing forced-tool and
  schema-validation handling (SDK retries for transient errors; explicit
  handling for refusal / truncation; invalid tool input fails the stage). Do
  not describe validation retries unless the shared engine implements and tests
  them.
- **Pytest** covers the worker's deterministic pieces: orchestrate idempotency
  (a second run clears and replaces cluster assignments and the summary with no
  duplication), verified-only filtering, exact handle/cluster validation,
  disagreement-note resolution, rollback on a persistence failure, and cluster
  write-back. The orchestration call is mocked at the Bedrock-engine boundary,
  exactly as the reviewer tests mock theirs.
- **Web tests** cover the priority-ordering logic (weighted, and the
  no-/unparseable-weight fallback) — which lives in the web layer since ordering
  is applied at read time — the report route's complete/incomplete state and
  verified-only filtering, the source route's ownership, cross-analysis target,
  parameter validation, and Blob-streaming behavior (matching the existing
  `route.test.ts` pattern), and a report-page render smoke test.
- No browser-automation tests, per the master design.

## Out of scope (Phase 6)

Evaluation harness (`eval/` does not yet exist; fixtures and ground-truth
authoring are their own track), retention / cleanup cron, deploy hardening,
messy-solicitation stress test, and demo prep.
