# Extraction Evidence-Quote Grounding Design

## Goal

Make requirement extraction robust to the extraction model's normal behavior of
paraphrasing solicitation text, while preserving an auditable source-provenance
check. Today `extract._validate_result` requires each requirement's `text`
to be a verbatim substring of its cited page and aborts the entire extraction on
any mismatch. In practice the model summarizes most requirements (observed: 51 of
60 requirements paraphrased in one real SA5 run), so extraction fails
non-deterministically on whichever paraphrase happens to be validated first. This
blocks the pipeline loop.

Replace the verbatim-`text` contract with a two-field contract: `text` stays the
readable paraphrase consumed downstream, and a new required `evidence_quote`
holds a short exact span the model copies from the cited page. Extraction
validates the span rather than `text`, and degrades a bad span to a
`grounding_verified = false` flag instead of aborting.

`grounding_verified` has deliberately narrow semantics: it proves only that the
normalized `evidence_quote` occurs on the cited page. It does not prove that the
paraphrased `text` is entailed by that quote. The prompt instructs the model to
choose supporting evidence, but semantic entailment remains model behavior rather
than a deterministic guarantee.

## Scope

Worker + database only. No web UI changes; surfacing `grounding_verified` in the
web app is a separate follow-up. The change touches the `requirements` table
schema and generated Drizzle migration artifacts, the extraction tool schema,
the `ExtractedRequirement` model, the extraction prompt, `_validate_result`,
`run_extraction` persistence, and the extraction and requirements-schema test
suites.

Two independent fixes already landed and are unrelated to this contract change
(kept regardless): zero-width / Unicode-format-character stripping in
`extract._normalize_quote` and `verify._normalize`, and `extra="ignore"` on the
three extraction Pydantic models so model-invented stray fields are dropped
rather than aborting extraction.

## Data model / migration

Update `web/src/db/schema.ts`, then generate and commit the corresponding Drizzle
migration and metadata. The migration adds two columns to `requirements`:

- `evidence_quote text NOT NULL DEFAULT ''` — the exact span the model copied
  from the cited page to ground the requirement.
- `grounding_verified boolean NOT NULL DEFAULT false` — whether that span passed
  validation (normalized, ≥ 20 chars, and a substring of the cited page).

The defaults keep the migration safe against any pre-existing rows. New
extractions always set both columns explicitly on insert. Existing rows are
intentionally marked unverified because no trustworthy evidence quote can be
reconstructed from the paraphrased `text`. No index is needed because this
change does not introduce a query that filters or joins on either column.

## Extraction contract (`extract.py`)

### Tool schema (`EXTRACTION_TOOL`)

Add `evidence_quote` to `requirements.items.properties` and to the `items`
`required` list. Description: a verbatim span of at least 20 characters copied
from the cited page that supports this requirement. Add/clarify the `text`
description so the model understands `text` is a concise paraphrased statement
of the requirement (used downstream), distinct from the source
`evidence_quote`.
`additionalProperties: false` stays (advisory to the model; Bedrock classic does
not enforce it, which is why `extra="ignore"` handles stray fields).

### `ExtractedRequirement` model

Add `evidence_quote: str` as a required field, run through the existing
`_trimmed` non-blank validator (alongside `text`, `key`, `ref`,
`classification_rationale`). It is required: a missing or blank `evidence_quote`
is malformed tool output and fails like a missing `text` does today.

### Prompt (`_build_prompt`)

Add one paragraph distinguishing the two fields: `text` is a concise paraphrase
of the requirement in the model's own words; `evidence_quote` is a span of at
least 20 characters copied verbatim from the cited page that supports the
requirement. Validation tolerates only the transformations already performed by
`_normalize_quote`: Unicode format-character removal, whitespace collapsing,
and case folding.

## Validation (`_validate_result`) — key behavior change

- **Remove** the current hard `text`-versus-page substring check (the check that
  fails on paraphrased requirements).
- For each requirement, compute `grounding_verified`:
  `normalized_quote = _normalize_quote(evidence_quote)` (the existing
  ZWSP-aware normalizer), then require `len(normalized_quote) >= 20` **and**
  `normalized_quote` to be a substring of the cited page's normalized text. On
  failure, set `grounding_verified = false` — do **not** raise. The requirement
  is still persisted. (Chosen behavior: keep the requirement, flag it, lose no
  compliance coverage.) The length floor therefore counts normalized Python
  string characters, not bytes or raw input characters.
- **Unchanged hard errors:** duplicate requirement keys, supersession cycles and
  self-reference, and structural citation errors — a requirement citing an
  out-of-range `[doc N]` handle or a page number that does not exist. A fabricated
  citation *location* is rarer and more serious than a text mismatch, so it
  remains a hard `ExtractionError`.
- The 20-character floor and the substring check both feed the same
  `grounding_verified` flag; a present-but-too-short span is treated as
  not grounded, not as a hard error.

The function returns
`tuple[dict[str, str | None], dict[str, bool]]`: the existing
`supersedes_by_key` mapping followed by `grounding_by_key`, so
`run_extraction` can persist the per-requirement flag without re-normalizing.

## Persistence (`run_extraction`)

The `INSERT INTO requirements` statement gains `evidence_quote` and
`grounding_verified` columns, populated from each `ExtractedRequirement` and the
computed grounding result. The existing delete-then-insert, supersession
back-fill, and transactional atomicity are unchanged.

Because the Pydantic validator uses `_trimmed`, persistence stores the trimmed
`evidence_quote`, just as it stores trimmed `text`, `key`, `ref`, and
`classification_rationale` values.

## Downstream behavior

This change is intentionally fail-open for requirement coverage. Mapping,
reviewer, orchestrator, and report loaders continue consuming requirements
regardless of `grounding_verified`; they do not need query or prompt changes in
this scope. The flag is provenance metadata for later inspection, not an
admission gate. Consequently an unverified requirement can still influence the
traceability matrix and reviewer context until the deferred UI/policy work
decides how to present or filter it. Reviewer findings remain subject to their
independent two-sided citation verification in `verify.py`.

## Testing

New and updated tests in `worker/tests/test_extract.py`:

- A paraphrased `text` that is absent from the page plus a matching
  `evidence_quote` → `grounding_verified = true`; the stored span equals the
  trimmed model `evidence_quote`. This is the primary regression case.
- A non-matching or sub-20-character `evidence_quote` → `grounding_verified =
  false`, and the requirement row is still persisted (not dropped, no raise).
- A missing/blank `evidence_quote` → `ExtractionError` (required-field contract).
- The tool schema requires `evidence_quote`, and the generated prompt explains
  the distinct paraphrase and evidence roles.
- Structural citation errors (bad `[doc N]`, nonexistent page) still raise, and
  duplicate-key / supersession checks are unaffected.
- Existing fixtures (`_valid_input`, `_requirement`, related builders) gain an
  `evidence_quote` that matches their cited page, and `_requirement_rows` (or a
  companion helper) is extended to assert the new columns.

Update `worker/tests/test_requirements_schema.py` to verify that legacy-style
inserts receive `evidence_quote = ''` and `grounding_verified = false`, while an
explicit insert round-trips a non-empty quote and `true`. Existing tests and
fixtures outside extraction may continue omitting the columns and rely on those
defaults.

## Explicitly deferred

- Web UI surfacing of `grounding_verified` (badge / indicator on requirements).
- Any policy that filters or blocks unverified requirements before mapping,
  review, orchestration, or reporting.
- Any change to the `verify` stage. Findings are independently re-grounded there
  against page text; this change is confined to requirement extraction.
- Softening structural citation errors (bad doc/page) into soft flags.
