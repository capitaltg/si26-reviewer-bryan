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
within one job, then the existing finalize path marks the analysis
`complete`. The web app gains the terminal report screen and a protected
source-render route that powers click-to-source.

## Worker: `orchestrate` stage (replaces the `report` stub)

The stub `("report", "assembling report (stub)")` entry in
`worker/src/worker/pipeline.py` is removed. A real `orchestrate` stage runs
after `review`, updating `analyses.stage`/`stage_detail` like every other
stage. The stage lives in a new `worker/src/worker/orchestrate.py` with a
`run_orchestrate(conn, analysis_id)` entry point, mirroring how
`reviewers.run_review` is structured and called.

### Inputs

All persisted `findings` for the analysis (with `reviewer`, `finding_kind`,
`severity`, `confidence`, `requirement_id`, `evidence`, `description`,
`suggestion`, `verification`), joined to `requirements` (for the Section M
`weight`) and `mappings` (for the matrix view). Findings whose
`verification = 'dropped'` are excluded from orchestration; `unverified`
findings are included but retain their tag.

### One structured orchestration call

A single forced-tool call returns, in one pass:

- **cluster assignments** — a `cluster_id` per finding, grouping semantic
  duplicates across reviewers. Findings keep their reviewer of origin; only
  `findings.cluster_id` is written.
- **disagreement notes** — cross-reviewer conflicts, surfaced as a signal and
  never silently resolved.
- **executive summary** — generated with the full deduped picture in view.

All findings fit comfortably in context, so a single call is used rather than
separate dedupe / summary calls — it is cheaper and avoids cross-call ordering
fragility. The call **reuses the reviewers' existing Bedrock forced-tool
engine** (the `reviewers.py` call/validation pattern with a Pydantic-backed
tool schema), not `messages.parse`: the worker talks to Anthropic Bedrock via
classic `InvokeModel`, which is how the reviewers already run. Response
validation follows the same schema-enforced, retry-on-invalid pattern as the
reviewers.

### Deterministic priority ordering

Priority ordering is computed in code, not by the LLM: after clustering,
findings are ordered by Section M `weight` (from the linked requirement) and
then by `severity`. Requirements carry `weight` as free text, so ordering
parses a numeric weight where present and falls back to a stable, deterministic
order (severity, then a fixed tiebreaker) when a weight is absent or
unparseable. Ordering is applied at read time by the web app rather than
persisted, so it stays auditable and re-derivable.

### Persistence and retry-safety

The stage is idempotent, matching Phase 3/4. On every run it, within the job's
transaction scope:

1. clears prior `cluster_id`s for the analysis (`SET cluster_id = NULL`),
2. writes the new cluster assignments, and
3. upserts the single `summaries` row for the analysis
   (`ON CONFLICT (analysis_id) DO UPDATE`).

A re-run therefore fully replaces prior orchestration output with no
duplication. The existing `jobs.py` finalize (`status = 'complete',
stage = 'done', stage_detail = NULL`) is unchanged and runs after
`orchestrate` returns.

## Data model delta

One new table (columns abridged), anticipated by the master design's §3
`summaries`:

- `summaries` — `id`, `analysis_id` (unique, FK → `analyses`, `ON DELETE
  CASCADE`), `summary_text` (text), `disagreement_notes` (jsonb),
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

It reads the analysis, `requirements`, `mappings`, `findings`, and the
`summaries` row, and renders:

- **Traceability matrix** — one row per *effective* requirement (a requirement
  with a successor is shown as superseded and linked to its replacement, and
  generates no coverage row), with coverage status (`covered` / `partial` /
  `missing`), slide references, and rationale.
- **Findings grouped by reviewer**, priority-ordered per the deterministic
  ordering above, with severity and confidence chips, visual grouping of
  findings that share a `cluster_id`, and an **evidence-provenance badge** on
  findings grounded only in a vision summary.
- **Disagreement callouts** from `summaries.disagreement_notes`.
- The **executive summary** from `summaries.summary_text`.

UI follows the existing App Router + Tailwind + shadcn/ui conventions already in
`web/`.

## Web: click-to-source

- **`GET /api/analyses/[id]/source`** (new route under
  `web/src/app/api/analyses/[id]/`) — takes the citation target (document +
  page for a solicitation page, or the deck document + slide/page) as query
  parameters, performs the same ownership check as the sibling analysis routes,
  looks up the target `pages` row's `image_blob_pathname`, and streams the
  pre-rendered PNG from private Blob. Images are already uploaded during ingest,
  so no rendering happens here. The streamed response stays under the ~4.5 MB
  Vercel function response cap the images are pinned below.
- Citation chips on matrix rows and on findings open a **modal** that calls this
  route and displays the rendered source page/slide. A citation whose target
  cannot be resolved renders as static (non-clickable) text rather than a broken
  link.

## Error handling and testing

Consistent with the master design's §6 and the Phase 3/4 approach:

- The `orchestrate` stage is wrapped by the same stage-level try/except as every
  other stage; a failure sets `status = 'failed'` with the failing stage and
  error message, and the report screen is unreachable until a re-run succeeds.
- The orchestration LLM call uses the reviewers' existing retry / schema-
  validation handling (SDK retries for transient errors; explicit handling for
  refusal / truncation; validation retry on an invalid tool response).
- **Pytest** covers the worker's deterministic pieces: orchestrate idempotency
  (a second run clears and replaces cluster assignments and the summary with no
  duplication) and cluster write-back. The orchestration call is mocked at the
  Bedrock-engine boundary, exactly as the reviewer tests mock theirs.
- **Web tests** cover the priority-ordering logic (weighted, and the
  no-/unparseable-weight fallback) — which lives in the web layer since ordering
  is applied at read time — the source route's ownership / authorization
  behavior (matching the existing `route.test.ts` pattern), and a report-page
  render smoke test.
- No browser-automation tests, per the master design.

## Out of scope (Phase 6)

Evaluation harness (`eval/` does not yet exist; fixtures and ground-truth
authoring are their own track), retention / cleanup cron, deploy hardening,
messy-solicitation stress test, and demo prep.
