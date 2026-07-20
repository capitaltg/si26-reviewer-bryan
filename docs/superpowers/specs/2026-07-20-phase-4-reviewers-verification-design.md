# Phase 4: Reviewers and Citation Verification Design

## Goal

Replace the worker's stub `review` stage with three grounded AI reviewers and a
non-LLM citation verifier that persist verified findings to a new `findings`
table. This phase stops before orchestration (semantic dedupe, prioritization,
cross-reviewer disagreement, executive summary), the report UI, and the
evaluation harness — those remain later phases. After Phase 4 the only stub
stage left is `report`.

## Scope

The worker reads the Phase-3 outputs (persisted `requirements`, `mappings`) and
the ingested `pages` (native text, vision summaries, aligned script) and runs
the `review` stage in three ordered steps within one job:

1. **Run reviewers.** Three forced-tool Anthropic Bedrock calls, one per
   reviewer, sharing a single call/validation engine parameterized by a
   reviewer spec. Each reviewer is grounded in *distinct* data, not just a
   distinct persona:
   - **Compliance Officer** — effective `L` requirements, `limit` and `FAR`
     records, and the matrix (mappings).
   - **Technical/SME** — `SOW` requirements, deck native text, vision summaries,
     aligned script, and the matrix.
   - **Government Evaluator** — `M` factors with weights and the matrix.
2. **Verify.** A pure, LLM-free function tags every proposed finding
   `verified`, `unverified`, or `dropped` and resolves its evidence provenance.
3. **Persist.** In one transaction, delete any existing findings for the
   analysis, then insert every finding (including `dropped` ones for the audit
   trail). The report layer surfaces only non-`dropped` findings; this phase
   builds no report layer.

Each reviewer runs only if its primary grounding set is non-empty. With no
Section M records, for example, the Government Evaluator is skipped rather than
asked to review nothing; a skipped reviewer produces zero findings and no error.

Reviewers run sequentially and any reviewer failure fails the whole `review`
stage — no partial finding set is treated as complete, mirroring `extract`.

Prompt caching (a cached solicitation prefix shared across reviewer calls,
mentioned in the system design) is **deferred**. Each reviewer is grounded in
different structured data rather than a shared raw-solicitation blob, so the
shared prefix is small, and the classic Bedrock `InvokeModel` path this
deployment uses does not cache anywhere in the worker yet. Correctness comes
first; caching is revisited as a cost optimization only if warranted.

## Data Model

Add a `findings` table linked to an analysis, with:

- `reviewer` (enum `compliance` / `technical` / `evaluator`),
- `severity` (enum `high` / `medium` / `low`) and `confidence` (enum `high` /
  `medium` / `low`), both stored and later displayed as **reviewer opinion**,
  never as measured probabilities,
- `requirement_id` (nullable fk to `requirements`, `ON DELETE SET NULL`) — a
  general observation may tie to no single requirement,
- `evidence` (jsonb, polymorphic — see below),
- `evidence_provenance` (nullable enum `native_text` / `script` /
  `vision_summary`) — which proposal source verified the evidence,
- `description` and `suggestion` (text),
- `cluster_id` (nullable uuid) — remains null until Phase 5 orchestration,
- `verification` (enum `verified` / `unverified` / `dropped`).

The `evidence` jsonb is **two-sided for observation findings** —
`{ solicitation: {ref, page, quote}, proposal: {slide | script, quote} }` — and
**one-sided for gap findings** (`missing` / `partial`-type observations) —
`{ solicitation: {ref, page, quote}, searched_scope: "…" }` with no fabricated
proposal citation. Missing/partial findings never carry a proposal quote.

Database constraints preserve referential integrity: deleting an analysis
cascades to its findings, and deleting a requirement nulls the finding's
`requirement_id` rather than deleting the finding.

## Reviewer Calls

One engine in `reviewers.py`, three specs. Each spec supplies a reviewer id, a
grounding loader (SQL over the Phase-3 tables and `pages`), and a prompt
preamble. All three use the same structured-output mechanism established for the
vision, extraction, and mapping passes: a single forced tool call
(`record_findings`) whose arguments the worker reads and validates against a
Pydantic schema client-side. The classic Bedrock `InvokeModel` path rejects
`messages.parse()` / `output_config.format` and `strict` tools, so schema
enforcement is client-side. A `refusal` or `max_tokens` stop reason is treated
as untrusted and fails the stage rather than persisting a truncated or empty
finding list.

Findings cite by **handle, never by UUID** — echoing long UUIDs per record is
error-prone and one slip fails an all-or-nothing stage. The prompt presents each
effective requirement as `[req N] source ref — text` and each deck page as
`slide K`. A proposed finding cites its requirement by the integer handle `N`
(nullable) and its proposal evidence by slide number or script marker. The
worker resolves handles back to database UUIDs after validation; an out-of-range
requirement handle fails the stage.

The proposed-finding schema carries: `requirement_handle` (nullable int),
`severity`, `confidence`, `finding_kind` (`gap` or `observation`, which
determines the evidence shape), `solicitation_ref`, `solicitation_page`,
`solicitation_quote`, the proposal citation and `proposal_quote` (omitted for
gaps), `description`, and `suggestion`. `MAX_TOKENS` is generous (16_384). There
is **no output chunking**: unlike mapping, the finding count is open-ended and
unpredictable, so there is no fixed batch to split on; a `max_tokens` stop is
untrusted and fails the stage.

## Citation Verification

`verify.py` is a pure function over the proposed findings and the analysis's
persisted requirement and page text — normalized string matching
(whitespace-collapsed, case-folded), no LLM, no DB writes, no network. Per
finding:

- **Structural failure → `dropped`.** The cited solicitation ref/page does not
  exist, or (for observations) the cited slide/script location does not exist.
  A fabricated location is dropped and never surfaced.
- **Solicitation-side quote.** The quoted requirement text must appear in the
  cited solicitation page's extracted text. Not found → `unverified`.
- **Proposal-side quote (observations only).** The quoted evidence must appear
  in the cited slide's native text, its aligned script, or its vision summary,
  checked in that priority order. The first source it matches sets
  `evidence_provenance`; a match only against `vision_summary` carries the
  weaker-grounding badge because vision summaries are themselves LLM output.
  Found in none → `unverified` with null provenance.
- **Gap findings** (`missing` / `partial`). Solicitation-side only; there is no
  proposal quote to check and provenance stays null. A gap finding that carries
  a proposal citation is a structural violation → `dropped`.
- Passing every applicable check → `verified`.

The solicitation-side and proposal-side pass rates (proposal broken out by
provenance) that the eval harness will later report are a direct consequence of
these tags, but the harness that reports them is out of scope for Phase 4.

## Pipeline and Failure Behavior

`run_pipeline` gains a real `review` stage after `map`, updating
`analyses.stage` / `stage_detail` with human-readable progress before running
the three reviewers and the verifier. `STUB_STAGES` shrinks to `[report]` only,
keeping the Phase 5 contract unchanged.

The stage is idempotent under retry. A worker requeue re-runs the pipeline from
the start, so persistence first deletes any existing findings for the analysis
before inserting, mirroring the ingest, extract, and map stages.

Invalid schemas, untrusted stop reasons, and out-of-range handles fail the
current stage and let the existing job-failure handling report the error; no
partial finding set is treated as complete.

## Testing

- `test_findings_schema.py` — inserts a finding; asserts delete-cascade from the
  analysis, `requirement_id` set-null on requirement delete, and enum/nullability
  constraints.
- `test_reviewers.py` — fake Anthropic message/tool-use classes matching
  `test_vision.py` / `test_extract.py`: requirement-handle resolution to UUIDs,
  reviewer gating (Government Evaluator skipped when no `M` records exist),
  `refusal` and `max_tokens` each raising and leaving no findings, an
  out-of-range handle raising, and an idempotent re-run replacing rather than
  duplicating prior rows.
- `test_verify.py` — the deterministic verifier with no fakes: each drop rule,
  each unverified rule, each provenance tier (native / script / vision), gap vs
  observation evidence shapes, and normalized-matching edge cases.
- `test_pipeline.py` — extends the ordered-stage assertion to include `review`
  after `map` and before the `report` stub.

Phase 4 deliberately omits orchestration (semantic dedupe, prioritization,
cross-reviewer disagreement detection, executive summary), the report UI,
ground-truth fixtures, and finding precision/recall reporting.
