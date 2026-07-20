# Phase 4: Reviewers and Citation Verification Design

## Goal

Replace the worker's stub `review` stage with three grounded AI reviewers and a
non-LLM citation verifier, persisting citation-classified findings to a new
`findings` table. This phase stops before orchestration (semantic dedupe,
prioritization, cross-reviewer disagreement, executive summary), the report UI,
and the evaluation harness — those remain later phases. After Phase 4 the only
stub stage left is `report`.

## Scope

The worker reads the Phase-3 outputs (persisted `requirements`, `mappings`) and
the ingested `pages` (native text, vision summaries, aligned script) and runs
the `review` stage in three ordered steps within one job:

1. **Run reviewers.** Up to three forced-tool Anthropic Bedrock calls, one per
   reviewer, sharing a single call/validation engine parameterized by a
   reviewer spec. Each reviewer is grounded in *distinct* data, not just a
   distinct persona:
   - **Compliance Officer** — effective `L`, `limit`, and `FAR` records, the `L`
     rows of the matrix, and proposal page evidence.
   - **Technical/SME** — effective `SOW` requirements, deck native text, vision
     summaries, aligned script, and the `SOW` rows of the matrix.
   - **Government Evaluator** — effective `M` factors with weights, the full
     matrix, and proposal page evidence, so scoring considerations can be
     compared with actual proposal content.
2. **Verify.** A pure, LLM-free function tags every proposed finding
   `verified`, `unverified`, or `dropped` and resolves its evidence provenance.
3. **Persist.** In one transaction, delete any existing findings for the
   analysis, then insert every finding (including `dropped` ones for the audit
   trail). The later report layer surfaces only `verified` findings;
   `unverified` and `dropped` rows exist for audit and evaluation. This phase
   builds no report layer.

Each reviewer runs only if its primary grounding set is non-empty. With no
Section M records, for example, the Government Evaluator is skipped rather than
asked to review nothing; a skipped reviewer produces zero findings and no error.

For every solicitation record in a reviewer's primary set, its loader also
includes the native text of the cited source document/page. Every reviewer gets
each deck page's native text, aligned script, and vision summary. This supporting
text is necessary to emit exact quotes that the deterministic verifier can
match; grounding remains distinct because each reviewer receives a different
effective solicitation record set and matrix view.

Reviewers run sequentially and any reviewer failure fails the whole `review`
stage — no partial finding set is treated as complete, mirroring `extract`.

Prompt caching (a cached solicitation prefix shared across reviewer calls,
mentioned in the system design) is **deferred**. Each reviewer is grounded in
different structured data rather than a shared raw-solicitation blob, so the
reusable prefix is small, and the worker has no prompt-caching implementation
yet. Correctness comes first; caching is revisited as a cost optimization only
if warranted.

## Data Model

Add a `findings` table linked to an analysis, with:

- `reviewer` (enum `compliance` / `technical` / `evaluator`),
- `finding_kind` (enum `gap` / `observation`),
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
- `solicitation_verified` (boolean) and `proposal_verified` (nullable boolean;
  null only for gap findings), so later evaluation can measure the two citation
  sides independently,
- `verification` (enum `verified` / `unverified` / `dropped`) — the aggregate
  display/filter status derived by the verifier.

The `evidence` jsonb is **two-sided for observation findings** —
`{ solicitation: {document_id, document_name, ref, page, quote}, proposal:
{slide, quote} }` — and **one-sided for gap findings** — `{ solicitation:
{document_id, document_name, ref, page, quote}, searched_scope: "…" }`. A gap
claims that all or part of the cited obligation is absent and therefore carries
no fabricated proposal citation. The worker resolves `document_id` and
`document_name` from an analysis-scoped document handle; the model never emits
database UUIDs. Proposal evidence always cites the deck slide number. Whether
the quote matched native slide text, aligned script, or a vision summary is
represented by `evidence_provenance`, not by three competing citation shapes.
`searched_scope` is a deterministic description generated by the worker from
the sources actually supplied to the reviewer, not free-form model output.

Database constraints preserve referential integrity: deleting an analysis
cascades to its findings, and deleting a requirement nulls the finding's
`requirement_id` rather than deleting the finding. Check constraints require
`proposal_verified` and `evidence_provenance` to be null for gaps, require
`proposal_verified` for observations, require provenance exactly when proposal
verification passes, and prevent `verification = 'verified'` unless every
applicable side passed. The Pydantic discriminated union remains responsible
for validating the two JSON evidence shapes before persistence.

## Reviewer Calls

One engine in `reviewers.py`, three specs. Each spec supplies a reviewer id, a
grounding loader (SQL over the Phase-3 tables and `pages`), and a prompt
preamble. Every loader excludes a record that has a successor via
`supersedes_requirement_id`; reviewers never reason over obsolete requirements.
All three use the same structured-output mechanism established for the vision,
extraction, and mapping passes: a single forced tool call
(`record_findings`) whose arguments the worker reads and validates against a
Pydantic schema client-side. The classic Bedrock `InvokeModel` path rejects
`messages.parse()` / `output_config.format` and `strict` tools, so schema
enforcement is client-side. The request also disables parallel tool use. The
only trusted stop reason is `tool_use`, accompanied by exactly one
`record_findings` block; `end_turn`, `refusal`, `max_tokens`, or any other stop
reason fails the stage rather than persisting a truncated or ambiguous finding
list.

All document-derived text is untrusted data. The common prompt places it in
clearly delimited sections and tells the model to analyze embedded instructions
as proposal/solicitation content, never to follow instructions that attempt to
change the reviewer role, tool, schema, or evidence rules. Forced tool use and
client-side validation remain the enforcement boundary; the prompt wording is
defense in depth.

Findings cite by **handle, never by UUID** — echoing long UUIDs per record is
error-prone and one slip fails an all-or-nothing stage. The prompt presents each
effective requirement as `[req N] [doc D] source ref, page P — text`, each
solicitation document with a stable per-call `[doc D]` handle, and each deck
page as `slide K`. A proposed finding cites its requirement by integer handle
`N` (nullable for a general observation), its solicitation document by handle
`D`, and its proposal evidence by slide number. The worker resolves handles to
analysis-scoped database records after validation. An out-of-range requirement
or document handle fails the stage. A valid non-null requirement handle paired
with a different document/ref/page is a structural citation failure classified
by the verifier as `dropped`.

The proposed-finding schema carries: `requirement_handle` (nullable int),
`severity`, `confidence`, `finding_kind` (`gap` or `observation`, which
determines the evidence shape), `solicitation_document_handle`,
`solicitation_ref`, `solicitation_page`, `solicitation_quote`,
`proposal_slide` and `proposal_quote` (both required for observations and both
omitted for gaps), `description`, and `suggestion`. Quotes, descriptions, and
suggestions must remain non-empty after trimming; prompts require short,
contiguous, verbatim quotes rather than ellipses or paraphrases.

`MAX_TOKENS` is 16,384, `MAX_FINDINGS_PER_REVIEWER` is 25, and
`MAX_REVIEW_INPUT_CHARS` is 400,000. The finding limit is enforced in both the
tool JSON schema (`maxItems`) and Pydantic model. Reviewers inspect their
complete grounding set but return only the most material distinct findings;
the exhaustive requirement-by-requirement status remains in the matrix. There
is no output chunking in this phase. The input-size guard is measured before
each call using the same conservative character approach as extraction and
fails with an actionable error rather than relying on an upstream context-window
error. A `max_tokens` stop remains untrusted and fails the stage.

## Citation Verification

`verify.py` is a pure function over the proposed findings and the analysis's
persisted requirement, document, and page text — normalized string matching
(whitespace-collapsed, case-folded), no LLM, no DB writes, no network. Empty
normalized quotes are invalid rather than matching every string. Per finding:

- **Structural failure → `dropped`.** The cited page does not exist in the
  resolved solicitation document, the echoed document/ref/page contradicts a
  non-null requirement handle, the finding's evidence fields violate its kind,
  or (for observations) the cited deck slide does not exist. A fabricated or
  ambiguous location is dropped and never surfaced.
- **Solicitation-side quote.** The quoted requirement text must appear in the
  resolved solicitation document/page's extracted text. The result is stored in
  `solicitation_verified`.
- **Proposal-side quote (observations only).** The quoted evidence must appear
  in the cited slide's native text, its aligned script, or its vision summary,
  checked in that priority order. The first source it matches sets
  `evidence_provenance`; a match only against `vision_summary` carries the
  weaker-grounding badge because vision summaries are themselves LLM output.
  The result is stored in `proposal_verified`; a miss leaves provenance null.
- **Gap findings** (`missing` / `partial`). Solicitation-side only; there is no
  proposal quote to check, `proposal_verified` and provenance stay null, and a
  gap that carries proposal evidence is a structural violation → `dropped`.
- **Aggregate status.** After structural checks, the two applicable sides are
  evaluated independently rather than short-circuiting. Passing every
  applicable check → `verified`; any quote miss → `unverified`.

`verified` means that the emitted citations resolve and the quoted text matches;
it does **not** prove that a reviewer's substantive judgment is correct. In
particular, solicitation-side verification of a gap cannot mechanically prove
absence from the searched proposal scope. The later evaluation harness uses the
two stored booleans and provenance to report solicitation-side and proposal-side
pass rates, but that harness is out of scope for Phase 4.

## Pipeline and Failure Behavior

`run_pipeline` gains a real `review` stage after `map`, updating
`analyses.stage` / `stage_detail` with human-readable progress before running
the three reviewers and the verifier. `STUB_STAGES` shrinks to `[report]` only,
keeping the Phase 5 contract unchanged.

The stage is idempotent under retry. A worker requeue re-runs the pipeline from
the start. Only after every reviewer call and verification step succeeds does
one transaction delete the analysis's previous findings and insert the complete
replacement set. A failure before that transaction writes no new findings and
does not partially replace the previous set. Failed analyses are not reportable,
so retained rows from an earlier attempt cannot be mistaken for a successful
current result.

Invalid schemas, untrusted stop reasons, and out-of-range handles fail the
current stage and let the existing job-failure handling report the error; no
partial finding set is treated as complete.

## Testing

- `test_findings_schema.py` — inserts a finding; asserts delete-cascade from the
  analysis, `requirement_id` set-null on requirement delete, independent
  verification flags, and enum/nullability constraints.
- `test_reviewers.py` — fake Anthropic message/tool-use classes matching
  `test_vision.py` / `test_extract.py`: requirement-handle resolution to UUIDs,
  reviewer gating (Government Evaluator skipped when no `M` records exist),
  every stop reason other than `tool_use` raising, exact-one-tool validation,
  input and finding-count guardrails, out-of-range handles raising, failure
  preserving the previous complete set, and a successful idempotent re-run
  replacing rather than duplicating prior rows.
- `test_verify.py` — the deterministic verifier with no fakes: each drop rule,
  each side-specific unverified rule (including both sides failing at once),
  each provenance tier (native / script / vision), gap vs observation evidence
  shapes, requirement/citation contradictions, document identity across
  same-numbered pages, empty quotes, and normalized-matching edge cases.
- `test_pipeline.py` — extends the ordered-stage assertion to include `review`
  after `map` and before the `report` stub.

Phase 4 deliberately omits orchestration (semantic dedupe, prioritization,
cross-reviewer disagreement detection, executive summary), the report UI,
ground-truth fixtures, and finding precision/recall reporting.
