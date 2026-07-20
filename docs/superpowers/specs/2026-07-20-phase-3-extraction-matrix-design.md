# Phase 3: Extraction and Traceability Matrix Design

## Goal

Replace the first half of the worker's stub `review` stage with requirement extraction and persisted traceability mapping. This phase stops before reviewer findings, citation verification, report UI, and evaluation tooling.

## Scope

The worker reads already-ingested solicitation documents and deck/script page records. A structured Anthropic Bedrock call over the solicitation package extracts Section L requirements, Section M factors and weights, SOW/PWS scope statements, presentation limits, incorporated clauses, and amendment or Q&A changes. Each extracted record includes its source document, page number, reference, quoted text, source category, optional weight, and optional superseded requirement.

Only effective requirements enter the matrix. Superseded records remain persisted so the audit trail shows what changed, but a record replaced by a later requirement creates neither a coverage row nor a gap signal.

For each effective requirement, a mapping pass searches deck native text, vision summaries, and optional aligned narration text. It stores one coverage result: `covered`, `partial`, or `missing`, together with zero or more deck slide references and a concise rationale. A missing mapping must not invent a slide citation.

## Data Model

Add a `requirements` table linked to an analysis and solicitation document, with source metadata, quoted text, page number, optional weight, and an optional self-reference for supersession. Add a `mappings` table linked one-to-one with a requirement, containing its status, slide references as JSON, and rationale. Database constraints must prevent duplicate mappings for a requirement and preserve referential integrity.

## Pipeline and Failure Behavior

`run_pipeline` executes `extract` then `map` after ingestion, vision, and optional script alignment, updating `analyses.stage` and `stage_detail` with human-readable progress. The existing reviewer/report stubs remain after these stages.

Model responses are parsed with Pydantic schemas before any persistence. Extraction citations must refer to an existing solicitation document and page. Invalid schemas, invalid citations, or an unresolvable supersession reference fail the current stage and allow the existing job failure handling to report the error; no partial matrix is treated as complete.

## Testing

Unit tests cover structured-response validation, citation validation, amendment supersession, effective-requirement selection, and each coverage status. Database-focused tests verify requirements and mappings are persisted with the correct constraints. A pipeline test verifies the new stage order. Phase 3 deliberately omits ground-truth fixtures, precision/recall reporting, reviewer calls, finding verification, and all report UI work.
