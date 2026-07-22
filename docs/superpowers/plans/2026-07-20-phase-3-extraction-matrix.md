# Phase 3: Extraction and Traceability Matrix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist solicitation requirements and a retry-safe traceability matrix that maps effective obligation requirements to the ingested deck and narration content.

**Architecture:** Add `requirements` and `mappings` to the existing Postgres schema. The worker will use the same forced-tool Anthropic Bedrock pattern as `vision.py`: `extract.py` validates and persists a single full-package extraction response (all solicitation documents in one call, so supersession across amendments resolves within one context; an oversized package fails loudly rather than being split, because per-document splitting cannot resolve cross-document supersession), while `mapping.py` validates and persists coverage results for effective Section L/SOW requirements only. `pipeline.py` inserts these stages after vision/script alignment and before the still-stubbed reviewer/report stages.

**Tech Stack:** Next.js/Drizzle ORM migrations; Postgres 16; Python 3.12; psycopg; Pydantic v2; Anthropic Bedrock classic `InvokeModel`; pytest.

---

## File Structure

- `web/src/db/schema.ts` — Drizzle table definitions and enums.
- the next generated `web/drizzle/0003_*.sql` migration and matching `web/drizzle/meta/` snapshot — schema migration artifacts emitted by Drizzle.
- `worker/src/worker/extract.py` — solicitation context loading, forced-tool response validation, citation/supersession validation, and atomic replacement persistence.
- `worker/src/worker/mapping.py` — obligation selection, proposal-context loading, forced-tool mapping validation, and persistence.
- `worker/src/worker/pipeline.py` — new `extract` and `map` stage calls.
- `worker/tests/test_requirements_schema.py`, `worker/tests/test_extract.py`, `worker/tests/test_mapping.py`, `worker/tests/test_pipeline.py` — deterministic unit, database, and pipeline-order coverage.

### Task 1: Add requirements and mappings persistence

**Files:**
- Modify: `web/src/db/schema.ts`
- Create: next `web/drizzle/0003_*.sql` migration emitted by `npm run db:generate`
- Create: `worker/tests/test_requirements_schema.py`

- [ ] **Step 1: Write failing schema tests**

Create `worker/tests/test_requirements_schema.py` with tests that insert a solicitation document, a requirement, and a mapping; assert that a duplicate `mappings.requirement_id` raises `psycopg.errors.UniqueViolation`, deleting the requirement removes its mapping, and a `requirements.source_document_id` referencing a non-existent document raises `psycopg.errors.ForeignKeyViolation`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd worker && pytest tests/test_requirements_schema.py -q`

Expected: FAIL because `requirements` and `mappings` do not exist.

- [ ] **Step 3: Add Drizzle definitions and generate the migration**

In `web/src/db/schema.ts`, import `jsonb` and add:

```ts
export const requirementSourceEnum = pgEnum("requirement_source", [
  "L", "M", "SOW", "limit", "FAR", "amendment",
]);
export const mappingStatusEnum = pgEnum("mapping_status", [
  "covered", "partial", "missing",
]);

export const requirements = pgTable("requirements", {
  id: uuid("id").primaryKey().defaultRandom(),
  analysisId: uuid("analysis_id").notNull().references(() => analyses.id, { onDelete: "cascade" }),
  sourceDocumentId: uuid("source_document_id").notNull().references(() => documents.id, { onDelete: "cascade" }),
  source: requirementSourceEnum("source").notNull(),
  ref: text("ref").notNull(),
  text: text("text").notNull(),
  pageNo: integer("page_no").notNull(),
  weight: text("weight"),
  supersedesRequirementId: uuid("supersedes_requirement_id").references((): AnyPgColumn => requirements.id),
});

export const mappings = pgTable("mappings", {
  id: uuid("id").primaryKey().defaultRandom(),
  requirementId: uuid("requirement_id").notNull().unique().references(() => requirements.id, { onDelete: "cascade" }),
  status: mappingStatusEnum("status").notNull(),
  slideRefs: jsonb("slide_refs").notNull(),
  rationale: text("rationale").notNull(),
});
```

Also import `AnyPgColumn` from `drizzle-orm/pg-core`. Run `cd web && npm run db:generate`; retain the new migration and every `web/drizzle/meta/` artifact it creates.

- [ ] **Step 4: Run persistence tests**

Run: `cd worker && pytest tests/test_requirements_schema.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```sh
git add web/src/db/schema.ts web/drizzle worker/tests/test_requirements_schema.py
git commit -m "feat(data): add requirements and mappings tables"
```

### Task 2: Implement validated, idempotent requirement extraction

**Files:**
- Create: `worker/src/worker/extract.py`
- Create: `worker/tests/test_extract.py`
- Modify: `worker/pyproject.toml`

- [ ] **Step 1: Write failing extraction tests**

In `worker/tests/test_extract.py`, create fake Anthropic message/tool-use classes matching `test_vision.py`. Test `extract.run_extraction(conn, analysis_id)` with a base solicitation document and an amendment document (each with a page). The queued tool input must contain two `ExtractedRequirement` records that cite documents by the 1-based handle the prompt assigns, where the amendment record has `supersedes_key="l-1"` referencing the base record's key. Assert stored rows resolve that key to the base row ID and that the handles resolve to the correct document UUIDs. Add cases for: a citation to page 99, a citation to an out-of-range document handle, an unknown `supersedes_key`, `refusal`, and `max_tokens`; each raises `ExtractionError` and leaves no requirements. Add a case where the built prompt exceeds `extract.MAX_EXTRACTION_INPUT_CHARS` (monkeypatched low) and assert it raises `ExtractionError` rather than silently splitting — single-pass extraction is required so cross-document supersession stays resolvable. Re-run with a changed response and assert the previous rows are replaced rather than duplicated.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd worker && pytest tests/test_extract.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'worker.extract'`.

- [ ] **Step 3: Add the extraction model and persistence implementation**

Add `pydantic>=2` to `worker/pyproject.toml`. In `worker/src/worker/extract.py`, define `ExtractionError`, a `RequirementSource` `StrEnum` matching the database enum, and Pydantic models:

```python
class ExtractedRequirement(BaseModel):
    key: str
    source_document: int = Field(ge=1)  # 1-based document handle, resolved to a UUID worker-side
    source: RequirementSource
    ref: str
    text: str
    page_no: int = Field(ge=1)
    weight: str | None = None
    supersedes_key: str | None = None

class ExtractionResult(BaseModel):
    requirements: list[ExtractedRequirement]
```

Load only `documents.kind IN ('solicitation_base', 'solicitation_amendment', 'solicitation_q_and_a', 'solicitation_attachment')` for the analysis, joining `pages` and ordering by document and page. Assign each solicitation document a stable 1-based **handle** and present it in the prompt as `[doc N] kind — display_name`, followed by that document's pages (`page K:` + native text). The model cites a requirement's location by `source_document` (the handle) and `page_no`, never by UUID — echoing long UUIDs per record is error-prone and a single slip would fail the whole all-or-nothing stage. The worker maps each handle back to its document UUID after validation.

Instruct the model to record every obligation under its **functional** source (`L`, `SOW`, `M`, `limit`, `FAR`) regardless of which document it appears in: an amendment that revises a Section L instruction is emitted as a `source='L'` record that supersedes the base one — not as `source='amendment'`. Reserve `source='amendment'` for change notes that are not themselves slide-mappable obligations. This keeps amendment-revised obligations in the `L`/`SOW` set the mapping stage selects.

Set `MAX_EXTRACTION_INPUT_CHARS` (a guardrail sized to the verified Bedrock context limit, not an assumed 1M) and `MAX_TOKENS = 16_384`. Build one prompt over all solicitation pages; if its length exceeds `MAX_EXTRACTION_INPUT_CHARS`, raise `ExtractionError` rather than split per document — per-document calls cannot resolve cross-document supersession, so single-pass is required. Require record keys to be unique within the response. Call `AnthropicBedrock.messages.create` with a single forced `record_extraction` tool (`tool_choice` naming it, as in `vision.py`); reject `refusal`, `max_tokens`, missing/misnamed tool use, Pydantic validation errors, duplicate keys, out-of-range document handles, and missing pages.

Within `with conn.transaction():` (valid on the autocommit connection, as `jobs.py` already does), delete `requirements WHERE analysis_id = %s`, insert every extracted record with `supersedes_requirement_id = NULL`, collect generated IDs by model key, then update every record that has a `supersedes_key` to point at the resolved ID. Raise before committing if a referenced key is absent. Export `run_extraction(conn, analysis_id) -> None`.

- [ ] **Step 4: Run extraction tests**

Run: `cd worker && pytest tests/test_extract.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```sh
git add worker/pyproject.toml worker/src/worker/extract.py worker/tests/test_extract.py
git commit -m "feat(worker): extract solicitation requirements"
```

### Task 3: Implement batched obligation-only coverage mapping

**Files:**
- Create: `worker/src/worker/mapping.py`
- Create: `worker/tests/test_mapping.py`

- [ ] **Step 1: Write failing mapping tests**

Create requirements with sources `L`, `SOW`, `M`, `limit`, and `FAR`; add one requirement whose ID is used as another row's `supersedes_requirement_id`. Seed deck pages with native text, `vision_summary`, and `script_text`. Fake one `record_mappings` tool response for the effective L/SOW IDs only. Assert only those two rows get mappings, their JSON `slide_refs` are persisted, and M/limit/FAR/superseded rows do not. Add failures for a mapping to a non-selected requirement, duplicate requirement IDs, an invalid deck page number, a `missing` status with slide refs, and an untrusted stop reason. Add 201 effective L requirements, monkeypatch `MAX_MAPPING_OUTPUT_REQUIREMENTS = 200`, queue two tool responses, and assert exactly two model calls cover every requirement once.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd worker && pytest tests/test_mapping.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'worker.mapping'`.

- [ ] **Step 3: Add mapping implementation**

In `worker/src/worker/mapping.py`, define `MappingError`, `MappingStatus` (`covered`, `partial`, `missing`), and these Pydantic models:

```python
class ProposedMapping(BaseModel):
    requirement_id: str
    status: MappingStatus
    slide_refs: list[int]
    rationale: str

class MappingResult(BaseModel):
    mappings: list[ProposedMapping]
```

Select effective requirements with `source IN ('L', 'SOW')` and `NOT EXISTS (SELECT 1 FROM requirements successor WHERE successor.supersedes_requirement_id = requirements.id)`. Because amendment-revised obligations are recorded under their functional `L`/`SOW` source (see Task 2), this selection already includes them, while the superseded base rows are excluded by the `NOT EXISTS` clause. Load all deck pages ordered by `page_no`, including native text, vision summary, and script text. Set `MAX_MAPPING_OUTPUT_REQUIREMENTS = 200` and `MAX_TOKENS = 16_384`. If 200 or fewer obligations are selected, make one forced `record_mappings` call with every selected requirement and the full deck context; if more, split the ordered requirements into groups of 200 and call once per group, re-sending the same deck context. Unlike extraction, mapping has no cross-record dependency, so chunking here is safe. For each call, validate that its response IDs equal **that group's** requirement-ID set exactly (not the whole set), every slide reference is an existing deck page number, and a `missing` status carries no slide refs; then aggregate. In one transaction, delete existing mappings for the selected requirements and insert each validated mapping using `Json(slide_refs)` from `psycopg.types.json`. Export `run_mapping(conn, analysis_id) -> None`.

- [ ] **Step 4: Run mapping tests**

Run: `cd worker && pytest tests/test_mapping.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```sh
git add worker/src/worker/mapping.py worker/tests/test_mapping.py
git commit -m "feat(worker): persist obligation traceability mappings"
```

### Task 4: Wire stages and verify end-to-end behavior

**Files:**
- Modify: `worker/src/worker/pipeline.py`
- Modify: `worker/tests/test_pipeline.py`

- [ ] **Step 1: Write the failing pipeline-order test**

Add a test that monkeypatches `pipeline.ingest.ingest_document`, `pipeline.vision.run_vision_pass`, `pipeline.script_align.align_script`, `pipeline.extract.run_extraction`, `pipeline.mapping.run_mapping`, and `pipeline.jobs.update_stage`. Insert a deck, solicitation, and script document. `_run_ingest_stage` emits an `ingest` update per non-script document, so assert on the ordered, de-duplicated stage labels — `ingest`, `vision`, `script_align`, `extract`, `map`, `review`, `report` — rather than an exact call count; also assert the `run_extraction` then `run_mapping` calls occur in that order.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd worker && pytest tests/test_pipeline.py -q`

Expected: FAIL because `pipeline` does not import or execute `extract` and `mapping`.

- [ ] **Step 3: Wire the stages**

Replace the `from . import ...` line in `worker/src/worker/pipeline.py` with:

```python
from . import extract, ingest, jobs, mapping, script_align, vision
```

Immediately after optional script alignment, add:

```python
jobs.update_stage(conn, analysis_id, "extract", "extracting solicitation requirements")
extract.run_extraction(conn, analysis_id)
jobs.update_stage(conn, analysis_id, "map", "mapping requirements to proposal content")
mapping.run_mapping(conn, analysis_id)
```

Keep `STUB_STAGES` limited to `review` and `report` so Phase 4 and 5 contracts stay unchanged.

- [ ] **Step 4: Run focused and full worker tests**

Run:

```sh
cd worker && pytest tests/test_requirements_schema.py tests/test_extract.py tests/test_mapping.py tests/test_pipeline.py -q
cd worker && pytest -q
```

Expected: both commands PASS.

- [ ] **Step 5: Commit**

```sh
git add worker/src/worker/pipeline.py worker/tests/test_pipeline.py
git commit -m "feat(worker): run extraction and mapping pipeline stages"
```

## Plan Self-Review

- Spec coverage: Task 1 provides the constraints and JSON mapping shape; Task 2 handles single-pass extraction, document-handle citations, functional-source recording, client-side validation, supersession key resolution, and idempotency; Task 3 enforces obligation-only mapping with safe output chunking; Task 4 adds ordered progress stages. Reviewer calls, verification, UI, and eval work are intentionally absent.
- Placeholder scan: no deferred behavior is left unspecified; each task names files, test cases, implementation contract, commands, and commit scope.
- Type consistency: extraction cites documents by 1-based handle and records by model key before persistence, resolving both to database UUIDs afterward; mapping refers only to persisted UUID requirement IDs and integer deck page numbers.
- Correctness guard: extraction is single-pass (never split per document) so cross-document supersession stays resolvable; amendment-borne obligations are recorded under their functional `L`/`SOW` source so the mapping selection does not silently drop them.
