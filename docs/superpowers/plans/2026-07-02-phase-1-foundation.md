# Phase 1: Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the deployed skeleton of the AI Proposal Review Board: monorepo, Postgres schema, Keycloak auth, private-Blob uploads, a Postgres-backed job queue with a Python worker running a stub pipeline, and upload → status screens working end-to-end on Vercel + Railway.

**Architecture:** Next.js app (`web/`, Vercel) owns auth, uploads, and all reads; a Python poller (`worker/`, Railway) claims `queued` rows from the shared `analyses` table with `FOR UPDATE SKIP LOCKED`, runs the pipeline (a stub in this phase), and writes stage progress back. Postgres (Railway) is the single source of truth; files live in private Vercel Blob. Later phases replace the stub pipeline; nothing else changes shape.

**Tech Stack:** Next.js (App Router, TypeScript), Auth.js v5 (`next-auth@beta`) + Keycloak provider, Drizzle ORM + node-postgres, zod, `@vercel/blob` (private access), Tailwind; Python 3.12, psycopg 3, pytest; Docker; Vercel + Railway.

**Spec:** `docs/superpowers/specs/2026-07-02-ai-proposal-review-board-design.md`. This is plan 1 of 5 (Foundation → Ingestion → Extraction/Matrix → Reviewers → Report UI).

## Global Constraints

- Advisory-only product: nothing in any phase edits or generates proposal content.
- All Blob uploads/reads use `access: 'private'`; the browser never receives a direct Blob URL — reads go through protected API routes.
- Every analysis row is owned by an authenticated user (`analyses.user_id`); every API route checks ownership before returning data.
- Auth is company Keycloak at `getgaleo.com` (realm/client provided at deploy time via env vars — never hardcoded).
- Job claiming must be a single transactional `FOR UPDATE SKIP LOCKED` statement; stuck `running` jobs are requeued once (tracked in `requeue_count`), then failed.
- Enum values are fixed by the spec: `analyses.status ∈ queued/running/complete/failed`; `documents.kind ∈ solicitation_base/solicitation_amendment/solicitation_q_and_a/solicitation_attachment/deck/script`.
- Default retention: `expires_at = now() + 7 days` on analysis creation.
- Node ≥ 20, Python ≥ 3.12, Postgres 16.
- Git: commit steps assume the real project repo exists. If working in the pre-repo directory, skip commit steps and keep a running list of intended commits (user preference: no `git init` here).

---

### Task 1: Monorepo scaffold

**Files:**

- Create: `web/` (via `create-next-app`)
- Create: `worker/pyproject.toml`
- Create: `worker/src/worker/__init__.py`
- Create: `worker/tests/.gitkeep`
- Create: `README.md`
- Create: `.gitignore` (root)

**Interfaces:**

- Consumes: nothing.
- Produces: `web/` Next.js app (App Router, TS, Tailwind, `@/*` alias → `src/*`); `worker` installable Python package importable as `worker`; pytest runnable from `worker/`.

- [ ] **Step 1: Scaffold the Next.js app**

```bash
npx create-next-app@latest web --typescript --tailwind --eslint --app --src-dir --import-alias "@/*" --use-npm --no-turbopack
```

Accept defaults for any remaining prompts.

- [ ] **Step 2: Verify the web app runs**

Run: `cd web && npm run dev`
Expected: server starts; `http://localhost:3000` renders the Next.js starter page. Stop the server.

- [ ] **Step 3: Create the worker package**

`worker/pyproject.toml`:

```toml
[project]
name = "worker"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["psycopg[binary]>=3.2"]

[project.optional-dependencies]
dev = ["pytest>=8"]

[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
```

`worker/src/worker/__init__.py`: empty file. `worker/tests/.gitkeep`: empty file — do **not** add `tests/__init__.py`; the tests directory must stay a non-package so pytest puts it on `sys.path` and `from conftest import insert_analysis` (Tasks 3–5) resolves.

- [ ] **Step 4: Verify the worker package installs and pytest runs**

Run:

```bash
cd worker
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

Expected: `no tests ran` (exit code 5 is fine — the package installed and pytest executed).

- [ ] **Step 5: Root files**

`README.md`:

```markdown
# AI Proposal Review Board

Advisory-only review of GovCon oral-proposal packages (deck + narration script)
against the actual solicitation. See `GOALS.md` and
`docs/superpowers/specs/2026-07-02-ai-proposal-review-board-design.md`.

- `web/` — Next.js app (Vercel): auth, uploads, status, report
- `worker/` — Python pipeline worker (Railway): claims jobs from Postgres
- `docs/` — specs and plans

## Local dev

1. `docker compose -f docker-compose.dev.yml up -d` (Postgres on 5432, test DB on 5433)
2. `cd web && cp .env.example .env.local && npm install && npm run db:migrate && npm run dev`
3. `cd worker && source .venv/bin/activate && DATABASE_URL=postgres://postgres:dev@localhost:5432/agentic_review python -m worker.main`
```

Root `.gitignore`:

```gitignore
node_modules/
.next/
.env*
!.env.example
.venv/
__pycache__/
*.pyc
.pytest_cache/
```

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: scaffold web (Next.js) and worker (Python) packages"
```

---

### Task 2: Local Postgres + Drizzle schema + first migration

**Files:**

- Create: `docker-compose.dev.yml`
- Create: `web/drizzle.config.ts`
- Create: `web/src/db/schema.ts`
- Create: `web/src/db/index.ts`
- Create: `web/.env.example`
- Modify: `web/package.json` (scripts)
- Generated: `web/drizzle/0000_*.sql` (checked in — the worker's tests apply it)

**Interfaces:**

- Consumes: Task 1 scaffold.
- Produces: tables `users`, `analyses`, `documents`, `uploads` (columns below); `db` Drizzle client exported from `@/db`; `users`, `analyses`, `documents`, `uploads`, `documentKindEnum`, `analysisStatusEnum` exported from `@/db/schema`; migration SQL files in `web/drizzle/*.sql` using drizzle-kit's `--> statement-breakpoint` separators (Task 3's test fixture depends on this).

- [ ] **Step 1: Local databases**

`docker-compose.dev.yml` (repo root):

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_PASSWORD: dev
      POSTGRES_DB: agentic_review
    ports:
      - "5432:5432"
  postgres-test:
    image: postgres:16
    environment:
      POSTGRES_PASSWORD: dev
      POSTGRES_DB: agentic_review_test
    ports:
      - "5433:5432"
```

Run: `docker compose -f docker-compose.dev.yml up -d`
Expected: both containers healthy (`docker compose -f docker-compose.dev.yml ps`).

- [ ] **Step 2: Install Drizzle**

```bash
cd web
npm install drizzle-orm pg zod
npm install -D drizzle-kit @types/pg
```

- [ ] **Step 3: Write the schema**

`web/src/db/schema.ts`:

```ts
import {
  boolean,
  integer,
  pgEnum,
  pgTable,
  text,
  timestamp,
  uuid,
} from "drizzle-orm/pg-core";

export const analysisStatusEnum = pgEnum("analysis_status", [
  "queued",
  "running",
  "complete",
  "failed",
]);

export const documentKindEnum = pgEnum("document_kind", [
  "solicitation_base",
  "solicitation_amendment",
  "solicitation_q_and_a",
  "solicitation_attachment",
  "deck",
  "script",
]);

export const users = pgTable("users", {
  id: uuid("id").primaryKey().defaultRandom(),
  keycloakSub: text("keycloak_sub").notNull().unique(),
  email: text("email").notNull(),
  createdAt: timestamp("created_at", { withTimezone: true })
    .notNull()
    .defaultNow(),
});

export const analyses = pgTable("analyses", {
  id: uuid("id").primaryKey().defaultRandom(),
  userId: uuid("user_id")
    .notNull()
    .references(() => users.id),
  status: analysisStatusEnum("status").notNull().default("queued"),
  stage: text("stage"),
  stageDetail: text("stage_detail"),
  error: text("error"),
  consentLlmTransit: boolean("consent_llm_transit").notNull(),
  distributionAttestation: boolean("distribution_attestation").notNull(),
  lockedBy: text("locked_by"),
  lockedAt: timestamp("locked_at", { withTimezone: true }),
  requeueCount: integer("requeue_count").notNull().default(0),
  createdAt: timestamp("created_at", { withTimezone: true })
    .notNull()
    .defaultNow(),
  expiresAt: timestamp("expires_at", { withTimezone: true }).notNull(),
});

export const documents = pgTable("documents", {
  id: uuid("id").primaryKey().defaultRandom(),
  analysisId: uuid("analysis_id")
    .notNull()
    .references(() => analyses.id, { onDelete: "cascade" }),
  kind: documentKindEnum("kind").notNull(),
  displayName: text("display_name").notNull(),
  blobPathname: text("blob_pathname").notNull(),
  pdfBlobPathname: text("pdf_blob_pathname"),
  pageCount: integer("page_count"),
});

export const uploads = pgTable("uploads", {
  id: uuid("id").primaryKey().defaultRandom(),
  userId: uuid("user_id")
    .notNull()
    .references(() => users.id, { onDelete: "cascade" }),
  blobPathname: text("blob_pathname").notNull().unique(),
  displayName: text("display_name").notNull(),
  contentType: text("content_type").notNull(),
  sizeBytes: integer("size_bytes").notNull(),
  createdAt: timestamp("created_at", { withTimezone: true })
    .notNull()
    .defaultNow(),
});
```

(Tables for `pages`, `requirements`, `mappings`, `findings`, `summaries` are added by later phases' migrations — YAGNI here.)

- [ ] **Step 4: Drizzle config, client, env, scripts**

`web/drizzle.config.ts`:

```ts
import { defineConfig } from "drizzle-kit";

export default defineConfig({
  schema: "./src/db/schema.ts",
  out: "./drizzle",
  dialect: "postgresql",
  dbCredentials: { url: process.env.DATABASE_URL! },
});
```

`web/src/db/index.ts`:

```ts
import { drizzle } from "drizzle-orm/node-postgres";
import { Pool } from "pg";
import * as schema from "./schema";

const pool = new Pool({ connectionString: process.env.DATABASE_URL });

export const db = drizzle(pool, { schema });
```

`web/.env.example`:

```bash
DATABASE_URL=postgres://postgres:dev@localhost:5432/agentic_review
AUTH_SECRET=generate-with-npx-auth-secret
AUTH_KEYCLOAK_ID=agentic-review
AUTH_KEYCLOAK_SECRET=from-keycloak-admin
AUTH_KEYCLOAK_ISSUER=https://getgaleo.com/realms/REALM_NAME
BLOB_READ_WRITE_TOKEN=from-vercel-blob-store
```

Add to `web/package.json` `"scripts"`:

```json
"db:generate": "drizzle-kit generate",
"db:migrate": "drizzle-kit migrate"
```

Copy env: `cp .env.example .env.local` (drizzle-kit reads `.env.local` via `dotenv` — if it doesn't pick it up, prefix commands with `DATABASE_URL=postgres://postgres:dev@localhost:5432/agentic_review`).

- [ ] **Step 5: Generate and apply the migration**

Run:

```bash
cd web
DATABASE_URL=postgres://postgres:dev@localhost:5432/agentic_review npm run db:generate
DATABASE_URL=postgres://postgres:dev@localhost:5432/agentic_review npm run db:migrate
```

Expected: a `web/drizzle/0000_*.sql` file exists; migrate reports success.

- [ ] **Step 6: Verify tables exist**

Run:

```bash
docker compose -f docker-compose.dev.yml exec postgres psql -U postgres -d agentic_review -c "\dt"
```

Expected: `users`, `analyses`, `documents`, `uploads` (plus drizzle's migrations table).

- [ ] **Step 7: Commit**

```bash
git add docker-compose.dev.yml web/drizzle.config.ts web/src/db web/drizzle web/.env.example web/package.json web/package-lock.json
git commit -m "feat: postgres schema for users, analyses, documents, uploads"
```

---

### Task 3: Worker job claiming (`FOR UPDATE SKIP LOCKED`)

**Files:**

- Create: `worker/src/worker/db.py`
- Create: `worker/src/worker/jobs.py`
- Create: `worker/tests/conftest.py`
- Test: `worker/tests/test_jobs.py`

**Interfaces:**

- Consumes: migration SQL at `web/drizzle/*.sql` (Task 2), split on `--> statement-breakpoint`.
- Produces: `worker.db.connect() -> psycopg.Connection` (autocommit, from `DATABASE_URL`); `worker.jobs.Job` dataclass with `id: str`; `worker.jobs.claim_job(conn, worker_id: str) -> Job | None`. Test helper `insert_analysis(conn, status="queued") -> str` in `conftest.py` (reused by Tasks 4–5 tests).

- [ ] **Step 1: Write the test fixture and failing tests**

`worker/tests/conftest.py`:

```python
import os
import pathlib

import psycopg
import pytest

MIGRATIONS_DIR = pathlib.Path(__file__).parents[2] / "web" / "drizzle"
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgres://postgres:dev@localhost:5433/agentic_review_test",
)


def apply_migrations(conn: psycopg.Connection) -> None:
    for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
        for stmt in sql_file.read_text().split("--> statement-breakpoint"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(stmt)


@pytest.fixture()
def conn():
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as c:
        c.execute("DROP SCHEMA public CASCADE")
        c.execute("CREATE SCHEMA public")
        apply_migrations(c)
        yield c


def insert_analysis(conn: psycopg.Connection, status: str = "queued") -> str:
    user_id = conn.execute(
        "INSERT INTO users (keycloak_sub, email) "
        "VALUES (gen_random_uuid()::text, 'test@example.com') RETURNING id"
    ).fetchone()[0]
    return str(
        conn.execute(
            """
            INSERT INTO analyses
                (user_id, status, consent_llm_transit, distribution_attestation, expires_at)
            VALUES (%s, %s, true, true, now() + interval '7 days')
            RETURNING id
            """,
            (user_id, status),
        ).fetchone()[0]
    )
```

`worker/tests/test_jobs.py`:

```python
from conftest import insert_analysis

from worker import jobs


def test_claim_returns_none_when_queue_empty(conn):
    assert jobs.claim_job(conn, "w1") is None


def test_claim_marks_job_running_and_records_lock(conn):
    analysis_id = insert_analysis(conn)
    job = jobs.claim_job(conn, "w1")
    assert job is not None
    assert job.id == analysis_id
    row = conn.execute(
        "SELECT status, locked_by, locked_at FROM analyses WHERE id = %s",
        (analysis_id,),
    ).fetchone()
    assert row[0] == "running"
    assert row[1] == "w1"
    assert row[2] is not None


def test_claimed_job_is_not_claimable_again(conn):
    insert_analysis(conn)
    assert jobs.claim_job(conn, "w1") is not None
    assert jobs.claim_job(conn, "w2") is None


def test_claims_oldest_queued_first(conn):
    first = insert_analysis(conn)
    insert_analysis(conn)
    assert jobs.claim_job(conn, "w1").id == first
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd worker && source .venv/bin/activate && pytest tests/test_jobs.py -v`
Expected: FAIL / ERROR with `ModuleNotFoundError: No module named 'worker.jobs'` (or `cannot import name 'jobs'`).

- [ ] **Step 3: Implement `db.py` and `jobs.py`**

`worker/src/worker/db.py`:

```python
import os

import psycopg


def connect() -> psycopg.Connection:
    return psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
```

`worker/src/worker/jobs.py`:

```python
from dataclasses import dataclass
from typing import Optional

import psycopg

CLAIM_SQL = """
WITH claimed AS (
    SELECT id FROM analyses
    WHERE status = 'queued'
    ORDER BY created_at
    LIMIT 1
    FOR UPDATE SKIP LOCKED
)
UPDATE analyses a
SET status = 'running',
    locked_by = %(worker_id)s,
    locked_at = now(),
    stage = 'claimed',
    stage_detail = NULL,
    error = NULL
FROM claimed
WHERE a.id = claimed.id
RETURNING a.id
"""


@dataclass
class Job:
    id: str


def claim_job(conn: psycopg.Connection, worker_id: str) -> Optional[Job]:
    with conn.transaction():
        row = conn.execute(CLAIM_SQL, {"worker_id": worker_id}).fetchone()
    return Job(id=str(row[0])) if row else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_jobs.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add worker/src/worker/db.py worker/src/worker/jobs.py worker/tests
git commit -m "feat(worker): transactional job claiming with FOR UPDATE SKIP LOCKED"
```

---

### Task 4: Worker job lifecycle (stage updates, completion, failure, stuck-job requeue)

**Files:**

- Modify: `worker/src/worker/jobs.py`
- Test: `worker/tests/test_jobs.py` (append)

**Interfaces:**

- Consumes: `claim_job`, `Job`, `insert_analysis` (Task 3).
- Produces: `jobs.update_stage(conn, analysis_id: str, stage: str, detail: str | None = None) -> None`; `jobs.complete_job(conn, analysis_id: str) -> None`; `jobs.fail_job(conn, analysis_id: str, error: str) -> None`; `jobs.requeue_stuck(conn, timeout_minutes: int = 30) -> tuple[int, int]` returning `(requeued, failed)`.

- [ ] **Step 1: Write the failing tests**

Append to `worker/tests/test_jobs.py`:

```python
def test_update_stage_writes_stage_and_detail(conn):
    analysis_id = insert_analysis(conn)
    jobs.claim_job(conn, "w1")
    jobs.update_stage(conn, analysis_id, "ingest", "converting deck")
    row = conn.execute(
        "SELECT stage, stage_detail FROM analyses WHERE id = %s", (analysis_id,)
    ).fetchone()
    assert row == ("ingest", "converting deck")


def test_complete_job(conn):
    analysis_id = insert_analysis(conn)
    jobs.claim_job(conn, "w1")
    jobs.complete_job(conn, analysis_id)
    row = conn.execute(
        "SELECT status, stage FROM analyses WHERE id = %s", (analysis_id,)
    ).fetchone()
    assert row == ("complete", "done")


def test_fail_job_records_error(conn):
    analysis_id = insert_analysis(conn)
    jobs.claim_job(conn, "w1")
    jobs.fail_job(conn, analysis_id, "boom")
    row = conn.execute(
        "SELECT status, error FROM analyses WHERE id = %s", (analysis_id,)
    ).fetchone()
    assert row == ("failed", "boom")


def _make_stuck(conn, analysis_id, minutes=60, requeue_count=0):
    conn.execute(
        "UPDATE analyses SET status = 'running', locked_by = 'dead-worker', "
        "locked_at = now() - make_interval(mins => %s), requeue_count = %s "
        "WHERE id = %s",
        (minutes, requeue_count, analysis_id),
    )


def test_requeue_stuck_requeues_first_timeout(conn):
    analysis_id = insert_analysis(conn)
    _make_stuck(conn, analysis_id)
    assert jobs.requeue_stuck(conn, timeout_minutes=30) == (1, 0)
    row = conn.execute(
        "SELECT status, locked_by, locked_at, requeue_count FROM analyses WHERE id = %s",
        (analysis_id,),
    ).fetchone()
    assert row == ("queued", None, None, 1)


def test_requeue_stuck_fails_second_timeout(conn):
    analysis_id = insert_analysis(conn)
    _make_stuck(conn, analysis_id, requeue_count=1)
    assert jobs.requeue_stuck(conn, timeout_minutes=30) == (0, 1)
    row = conn.execute(
        "SELECT status, error FROM analyses WHERE id = %s", (analysis_id,)
    ).fetchone()
    assert row[0] == "failed"
    assert "timeout" in row[1]


def test_requeue_stuck_ignores_fresh_running_jobs(conn):
    analysis_id = insert_analysis(conn)
    jobs.claim_job(conn, "w1")  # locked_at = now()
    assert jobs.requeue_stuck(conn, timeout_minutes=30) == (0, 0)
    status = conn.execute(
        "SELECT status FROM analyses WHERE id = %s", (analysis_id,)
    ).fetchone()[0]
    assert status == "running"
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `pytest tests/test_jobs.py -v`
Expected: the 6 new tests FAIL with `AttributeError: module 'worker.jobs' has no attribute 'update_stage'` (etc.); the 4 Task 3 tests still pass.

- [ ] **Step 3: Implement the lifecycle functions**

Append to `worker/src/worker/jobs.py`:

```python
def update_stage(
    conn: psycopg.Connection,
    analysis_id: str,
    stage: str,
    detail: Optional[str] = None,
) -> None:
    conn.execute(
        "UPDATE analyses SET stage = %s, stage_detail = %s WHERE id = %s",
        (stage, detail, analysis_id),
    )


def complete_job(conn: psycopg.Connection, analysis_id: str) -> None:
    conn.execute(
        "UPDATE analyses SET status = 'complete', stage = 'done', stage_detail = NULL "
        "WHERE id = %s",
        (analysis_id,),
    )


def fail_job(conn: psycopg.Connection, analysis_id: str, error: str) -> None:
    conn.execute(
        "UPDATE analyses SET status = 'failed', error = %s WHERE id = %s",
        (error, analysis_id),
    )


REQUEUE_SQL = """
UPDATE analyses
SET status = 'queued', locked_by = NULL, locked_at = NULL,
    requeue_count = requeue_count + 1
WHERE status = 'running'
  AND locked_at < now() - make_interval(mins => %(timeout)s)
  AND requeue_count = 0
"""

FAIL_STUCK_SQL = """
UPDATE analyses
SET status = 'failed', error = 'worker timeout after requeue'
WHERE status = 'running'
  AND locked_at < now() - make_interval(mins => %(timeout)s)
  AND requeue_count >= 1
"""


def requeue_stuck(
    conn: psycopg.Connection, timeout_minutes: int = 30
) -> tuple[int, int]:
    with conn.transaction():
        requeued = conn.execute(
            REQUEUE_SQL, {"timeout": timeout_minutes}
        ).rowcount
        failed = conn.execute(
            FAIL_STUCK_SQL, {"timeout": timeout_minutes}
        ).rowcount
    return (requeued, failed)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_jobs.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add worker/src/worker/jobs.py worker/tests/test_jobs.py
git commit -m "feat(worker): job lifecycle - stage updates, completion, failure, stuck-job requeue"
```

---

### Task 5: Worker poll loop + stub pipeline

**Files:**

- Create: `worker/src/worker/pipeline.py`
- Create: `worker/src/worker/main.py`
- Create: `worker/Dockerfile`
- Test: `worker/tests/test_main.py`

**Interfaces:**

- Consumes: everything in `worker.jobs` (Tasks 3–4), `insert_analysis`.
- Produces: `pipeline.run_pipeline(conn, analysis_id: str) -> None` — the single function later phases replace with the real pipeline; `main.tick(conn, worker_id: str) -> bool` (True if a job was processed); `main.run_forever()` entrypoint (`python -m worker.main`).

- [ ] **Step 1: Write the failing tests**

`worker/tests/test_main.py`:

```python
from conftest import insert_analysis

from worker import main, pipeline


def test_tick_returns_false_when_no_jobs(conn):
    assert main.tick(conn, "w1") is False


def test_tick_processes_job_to_complete(conn, monkeypatch):
    monkeypatch.setattr(pipeline, "STAGE_SLEEP_SECONDS", 0)
    analysis_id = insert_analysis(conn)
    assert main.tick(conn, "w1") is True
    status = conn.execute(
        "SELECT status FROM analyses WHERE id = %s", (analysis_id,)
    ).fetchone()[0]
    assert status == "complete"


def test_tick_marks_job_failed_when_pipeline_raises(conn, monkeypatch):
    def explode(conn_, analysis_id_):
        raise RuntimeError("stage blew up")

    monkeypatch.setattr(main.pipeline, "run_pipeline", explode)
    analysis_id = insert_analysis(conn)
    assert main.tick(conn, "w1") is True
    row = conn.execute(
        "SELECT status, error FROM analyses WHERE id = %s", (analysis_id,)
    ).fetchone()
    assert row[0] == "failed"
    assert "RuntimeError" in row[1] and "stage blew up" in row[1]


def test_connect_with_retry_recovers_from_transient_db_failure(monkeypatch):
    calls = []
    fake_conn = object()

    def flaky_connect():
        calls.append("call")
        if len(calls) == 1:
            raise main.psycopg.OperationalError("database not ready")
        return fake_conn

    monkeypatch.setattr(main.db, "connect", flaky_connect)
    monkeypatch.setattr(main.time, "sleep", lambda _seconds: None)

    assert main.connect_with_retry(retry_seconds=0.01) is fake_conn
    assert calls == ["call", "call"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_main.py -v`
Expected: FAIL / ERROR with `ModuleNotFoundError: No module named 'worker.main'`.

- [ ] **Step 3: Implement pipeline stub and main loop**

`worker/src/worker/pipeline.py`:

```python
"""Stub pipeline. Phase 2+ replaces the body of run_pipeline with real stages;
the signature and the update_stage/complete/fail contract stay the same."""

import time

import psycopg

from . import jobs

STAGE_SLEEP_SECONDS = 2

STUB_STAGES = [
    ("ingest", "downloading and converting documents (stub)"),
    ("review", "running reviewers (stub)"),
    ("report", "assembling report (stub)"),
]


def run_pipeline(conn: psycopg.Connection, analysis_id: str) -> None:
    for stage, detail in STUB_STAGES:
        jobs.update_stage(conn, analysis_id, stage, detail)
        time.sleep(STAGE_SLEEP_SECONDS)
```

`worker/src/worker/main.py`:

```python
import logging
import os
import socket
import time

import psycopg

from . import db, jobs, pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("worker")


def tick(conn: psycopg.Connection, worker_id: str) -> bool:
    jobs.requeue_stuck(conn)
    job = jobs.claim_job(conn, worker_id)
    if job is None:
        return False
    log.info("claimed analysis %s", job.id)
    try:
        pipeline.run_pipeline(conn, job.id)
        jobs.complete_job(conn, job.id)
        log.info("completed analysis %s", job.id)
    except Exception as exc:  # noqa: BLE001 — stage failures must land in the DB
        log.exception("pipeline failed for analysis %s", job.id)
        jobs.fail_job(conn, job.id, f"{type(exc).__name__}: {exc}")
    return True


def connect_with_retry(retry_seconds: float) -> psycopg.Connection:
    while True:
        try:
            return db.connect()
        except psycopg.OperationalError:
            log.exception("database connection failed; retrying")
            time.sleep(retry_seconds)


def run_forever() -> None:
    worker_id = os.environ.get("WORKER_ID", socket.gethostname())
    poll_seconds = float(os.environ.get("POLL_INTERVAL_SECONDS", "2"))
    log.info("worker %s polling every %ss", worker_id, poll_seconds)
    conn = connect_with_retry(poll_seconds)
    while True:
        try:
            if not tick(conn, worker_id):
                time.sleep(poll_seconds)
        except psycopg.OperationalError:
            log.exception("database connection lost; reconnecting")
            try:
                conn.close()
            except Exception:  # noqa: BLE001 — best-effort cleanup before reconnect
                pass
            conn = connect_with_retry(poll_seconds)


if __name__ == "__main__":
    run_forever()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest -v`
Expected: 14 passed (Tasks 3–5).

- [ ] **Step 5: Dockerfile**

`worker/Dockerfile`:

```dockerfile
# Phase 2 adds LibreOffice + PyMuPDF system deps to this image.
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .
CMD ["python", "-m", "worker.main"]
```

Verify it builds: `docker build -t agentic-review-worker worker/`
Expected: image builds successfully.

- [ ] **Step 6: Manual end-to-end check against local Postgres**

```bash
cd worker && source .venv/bin/activate
DATABASE_URL=postgres://postgres:dev@localhost:5432/agentic_review python - <<'EOF'
from worker import db
conn = db.connect()
user = conn.execute("INSERT INTO users (keycloak_sub, email) VALUES ('manual-test', 'me@example.com') ON CONFLICT (keycloak_sub) DO UPDATE SET email = excluded.email RETURNING id").fetchone()[0]
aid = conn.execute("INSERT INTO analyses (user_id, consent_llm_transit, distribution_attestation, expires_at) VALUES (%s, true, true, now() + interval '7 days') RETURNING id", (user,)).fetchone()[0]
print("queued analysis:", aid)
EOF
DATABASE_URL=postgres://postgres:dev@localhost:5432/agentic_review python -m worker.main
```

Expected: log lines `claimed analysis …`, then ~6s of stub stages, then `completed analysis …`. Ctrl-C to stop.

- [ ] **Step 7: Commit**

```bash
git add worker/src/worker/pipeline.py worker/src/worker/main.py worker/Dockerfile worker/tests/test_main.py
git commit -m "feat(worker): poll loop with stub pipeline and failure handling"
```

---

### Task 6: Keycloak auth (Auth.js v5) + users upsert

**Files:**

- Create: `web/src/auth.ts`
- Create: `web/src/types/next-auth.d.ts`
- Create: `web/src/app/api/auth/[...nextauth]/route.ts`
- Create: `web/src/lib/session.ts`
- Modify: `web/src/app/page.tsx` (temporary auth smoke check; Task 9 replaces it)

**Interfaces:**

- Consumes: `db`, `users` from Task 2.
- Produces: `auth`, `signIn`, `signOut`, `handlers` from `@/auth`; `getUserId(): Promise<string | null>` from `@/lib/session` returning the **internal** `users.id` (not the Keycloak sub) — every protected route in Tasks 7–9 calls this.

Design note: no `middleware.ts`. Auth.js middleware runs on the Edge runtime where `pg` can't connect, and our `jwt` callback touches the DB. Protection is enforced where it matters instead — `getUserId()` in every API route, `auth()` + redirect in pages.

- [ ] **Step 1: Install and configure**

```bash
cd web
npm install next-auth@beta
npx auth secret   # writes AUTH_SECRET to .env.local
```

`web/src/auth.ts`:

```ts
import NextAuth from "next-auth";
import Keycloak from "next-auth/providers/keycloak";
import { db } from "@/db";
import { users } from "@/db/schema";

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [Keycloak],
  callbacks: {
    async jwt({ token, profile }) {
      // First sign-in only: upsert the user, stash our internal id in the JWT.
      if (profile?.sub) {
        const [row] = await db
          .insert(users)
          .values({ keycloakSub: profile.sub, email: profile.email ?? "" })
          .onConflictDoUpdate({
            target: users.keycloakSub,
            set: { email: profile.email ?? "" },
          })
          .returning({ id: users.id });
        token.userId = row.id;
      }
      return token;
    },
    async session({ session, token }) {
      session.userId = token.userId as string | undefined;
      return session;
    },
  },
});
```

(The bare `Keycloak` provider reads `AUTH_KEYCLOAK_ID`, `AUTH_KEYCLOAK_SECRET`, `AUTH_KEYCLOAK_ISSUER` from the environment — set them in `.env.local` with the real realm/client values for the `getgaleo.com` Keycloak.)

`web/src/types/next-auth.d.ts`:

```ts
import "next-auth";
import "next-auth/jwt";

declare module "next-auth" {
  interface Session {
    userId?: string;
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    userId?: string;
  }
}
```

`web/src/app/api/auth/[...nextauth]/route.ts`:

```ts
import { handlers } from "@/auth";

export const { GET, POST } = handlers;
```

`web/src/lib/session.ts`:

```ts
import { auth } from "@/auth";

export async function getUserId(): Promise<string | null> {
  const session = await auth();
  return session?.userId ?? null;
}
```

- [ ] **Step 2: Temporary smoke-check home page**

Replace `web/src/app/page.tsx`:

```tsx
import { auth, signIn, signOut } from "@/auth";

export default async function Home() {
  const session = await auth();
  if (!session) {
    return (
      <main className="p-8">
        <form
          action={async () => {
            "use server";
            await signIn("keycloak");
          }}
        >
          <button className="rounded bg-black px-4 py-2 text-white">
            Sign in with Keycloak
          </button>
        </form>
      </main>
    );
  }
  return (
    <main className="p-8 space-y-4">
      <p>
        Signed in as {session.user?.email} (internal id: {session.userId})
      </p>
      <form
        action={async () => {
          "use server";
          await signOut();
        }}
      >
        <button className="rounded border px-4 py-2">Sign out</button>
      </form>
    </main>
  );
}
```

- [ ] **Step 3: Verify the sign-in flow manually**

Run: `cd web && npm run dev`, open `http://localhost:3000`.
Expected: "Sign in with Keycloak" → redirects to the `getgaleo.com` login → back to the app showing your email and a UUID internal id. Then verify the upsert:

```bash
docker compose -f docker-compose.dev.yml exec postgres psql -U postgres -d agentic_review -c "SELECT keycloak_sub, email FROM users;"
```

Expected: one row with your Keycloak sub and email.
(Requires the Keycloak client to allow redirect URI `http://localhost:3000/api/auth/callback/keycloak` — configure in Keycloak admin if missing.)

- [ ] **Step 4: Verify TypeScript compiles**

Run: `cd web && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add web/src/auth.ts web/src/types web/src/app/api/auth web/src/lib/session.ts web/src/app/page.tsx web/package.json web/package-lock.json
git commit -m "feat(web): keycloak auth via auth.js with users upsert"
```

---

### Task 7: Create-analysis API + private Blob upload route

**Files:**

- Create: `web/src/lib/validation.ts`
- Create: `web/src/app/api/upload/route.ts`
- Create: `web/src/app/api/analyses/route.ts`
- Test: `web/src/lib/validation.test.ts`

**Interfaces:**

- Consumes: `getUserId()` (Task 6); `db`, `analyses`, `documents`, `uploads` (Task 2).
- Produces: `createAnalysisSchema` (zod) and `CreateAnalysisInput` type from `@/lib/validation`; `POST /api/upload` (Vercel Blob client-upload token exchange, auth-gated; completed uploads recorded in `uploads` with owner); `POST /api/analyses` accepting `{ consentLlmTransit: true, distributionAttestation: true, documents: [{kind, displayName, blobPathname}] }` → `201 { id }` only when every `blobPathname` belongs to the current user. Task 9's upload page calls both.

- [ ] **Step 1: Install deps and write the failing validation tests**

```bash
cd web
npm install --save-exact @vercel/blob
npm install -D vitest
```

Add to `web/package.json` `"scripts"`: `"test": "vitest run"`.

`web/src/lib/validation.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { createAnalysisSchema } from "./validation";

const doc = (kind: string, n = 1) => ({
  kind,
  displayName: `doc-${n}.pdf`,
  blobPathname: `uploads/doc-${n}.pdf`,
});

const valid = {
  consentLlmTransit: true,
  distributionAttestation: true,
  documents: [doc("solicitation_base"), doc("deck", 2)],
};

describe("createAnalysisSchema", () => {
  it("accepts base solicitation + deck with both attestations", () => {
    expect(createAnalysisSchema.safeParse(valid).success).toBe(true);
  });

  it("accepts optional amendments, q&a, attachments, and one script", () => {
    const input = {
      ...valid,
      documents: [
        ...valid.documents,
        doc("solicitation_amendment", 3),
        doc("solicitation_q_and_a", 4),
        doc("solicitation_attachment", 5),
        doc("script", 6),
      ],
    };
    expect(createAnalysisSchema.safeParse(input).success).toBe(true);
  });

  it("rejects when consent is not literally true", () => {
    expect(
      createAnalysisSchema.safeParse({ ...valid, consentLlmTransit: false })
        .success,
    ).toBe(false);
  });

  it("rejects when distribution attestation is missing", () => {
    const { distributionAttestation: _omit, ...rest } = valid;
    expect(createAnalysisSchema.safeParse(rest).success).toBe(false);
  });

  it("rejects without exactly one solicitation_base", () => {
    expect(
      createAnalysisSchema.safeParse({ ...valid, documents: [doc("deck")] })
        .success,
    ).toBe(false);
    expect(
      createAnalysisSchema.safeParse({
        ...valid,
        documents: [
          doc("solicitation_base"),
          doc("solicitation_base", 2),
          doc("deck", 3),
        ],
      }).success,
    ).toBe(false);
  });

  it("rejects without exactly one deck", () => {
    expect(
      createAnalysisSchema.safeParse({
        ...valid,
        documents: [doc("solicitation_base")],
      }).success,
    ).toBe(false);
  });

  it("rejects more than one script", () => {
    expect(
      createAnalysisSchema.safeParse({
        ...valid,
        documents: [...valid.documents, doc("script", 3), doc("script", 4)],
      }).success,
    ).toBe(false);
  });

  it("rejects unknown document kinds", () => {
    expect(
      createAnalysisSchema.safeParse({
        ...valid,
        documents: [...valid.documents, doc("resume")],
      }).success,
    ).toBe(false);
  });

  it("rejects duplicate blob pathnames", () => {
    expect(
      createAnalysisSchema.safeParse({
        ...valid,
        documents: [
          doc("solicitation_base"),
          {
            kind: "deck",
            displayName: "same-path.pptx",
            blobPathname: "uploads/doc-1.pdf",
          },
        ],
      }).success,
    ).toBe(false);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npm test`
Expected: FAIL — cannot resolve `./validation`.

- [ ] **Step 3: Implement the schema**

`web/src/lib/validation.ts`:

```ts
import { z } from "zod";

export const documentKinds = [
  "solicitation_base",
  "solicitation_amendment",
  "solicitation_q_and_a",
  "solicitation_attachment",
  "deck",
  "script",
] as const;

export const createAnalysisSchema = z
  .object({
    consentLlmTransit: z.literal(true),
    distributionAttestation: z.literal(true),
    documents: z
      .array(
        z.object({
          kind: z.enum(documentKinds),
          displayName: z.string().min(1),
          blobPathname: z.string().min(1),
        }),
      )
      .min(2),
  })
  .superRefine((val, ctx) => {
    const count = (k: string) =>
      val.documents.filter((d) => d.kind === k).length;
    if (count("solicitation_base") !== 1) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "exactly one solicitation_base is required",
      });
    }
    if (count("deck") !== 1) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "exactly one deck is required",
      });
    }
    if (count("script") > 1) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "at most one script is allowed",
      });
    }
    const seen = new Set<string>();
    for (const document of val.documents) {
      if (seen.has(document.blobPathname)) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: `duplicate blobPathname: ${document.blobPathname}`,
        });
      }
      seen.add(document.blobPathname);
    }
  });

export type CreateAnalysisInput = z.infer<typeof createAnalysisSchema>;
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm test`
Expected: 9 passed.

- [ ] **Step 5: Implement the upload token route**

`web/src/app/api/upload/route.ts`:

```ts
import { handleUpload, type HandleUploadBody } from "@vercel/blob/client";
import { NextResponse } from "next/server";
import { db } from "@/db";
import { uploads } from "@/db/schema";
import { getUserId } from "@/lib/session";

const ALLOWED_CONTENT_TYPES = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  "text/plain",
];

export async function POST(request: Request): Promise<NextResponse> {
  const userId = await getUserId();
  if (!userId) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  const body = (await request.json()) as HandleUploadBody;
  try {
    const jsonResponse = await handleUpload({
      body,
      request,
      onBeforeGenerateToken: async () => ({
        allowedContentTypes: ALLOWED_CONTENT_TYPES,
        addRandomSuffix: true,
        tokenPayload: JSON.stringify({ userId }),
      }),
      onUploadCompleted: async ({ blob, tokenPayload }) => {
        const parsed = JSON.parse(tokenPayload) as { userId?: string };
        if (!parsed.userId) {
          throw new Error("upload token payload missing userId");
        }
        const metadata = blob as typeof blob & {
          contentType?: string;
          size?: number;
        };
        await db
          .insert(uploads)
          .values({
            userId: parsed.userId,
            blobPathname: blob.pathname,
            displayName: blob.pathname.split("/").at(-1) ?? blob.pathname,
            contentType: metadata.contentType ?? "application/octet-stream",
            sizeBytes: metadata.size ?? 0,
          })
          .onConflictDoNothing({ target: uploads.blobPathname });
      },
    });
    return NextResponse.json(jsonResponse);
  } catch (error) {
    return NextResponse.json(
      { error: (error as Error).message },
      { status: 400 },
    );
  }
}
```

The private/public choice is made in the browser `upload()` call (Task 9), matching the current Vercel client-upload API. `onBeforeGenerateToken` authenticates the request and limits MIME types; `onUploadCompleted` records the completed Blob pathname with the authenticated owner so `/api/analyses` never trusts pathnames supplied by the browser alone.

Retention note for Phase 5: abandoned uploads (user uploads files but never submits) leave orphaned `uploads` rows + blobs that no `documents` row references. The Phase 5 retention cron must sweep `uploads` older than N days with no matching `documents.blob_pathname`, deleting both the row and the blob — carry this into the Phase 5 plan alongside expired-analyses cleanup.

- [ ] **Step 6: Implement the create-analysis route**

`web/src/app/api/analyses/route.ts`:

```ts
import { NextResponse } from "next/server";
import { and, eq, inArray, sql } from "drizzle-orm";
import { db } from "@/db";
import { analyses, documents, uploads } from "@/db/schema";
import { getUserId } from "@/lib/session";
import { createAnalysisSchema } from "@/lib/validation";

const UPLOAD_COMPLETION_WAIT_ATTEMPTS = 10;
const UPLOAD_COMPLETION_WAIT_MS = 250;

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function countOwnedUploads(userId: string, pathnames: string[]) {
  const rows = await db
    .select({ blobPathname: uploads.blobPathname })
    .from(uploads)
    .where(and(eq(uploads.userId, userId), inArray(uploads.blobPathname, pathnames)));
  return rows.length;
}

async function waitForOwnedUploads(userId: string, pathnames: string[]) {
  for (let attempt = 0; attempt < UPLOAD_COMPLETION_WAIT_ATTEMPTS; attempt += 1) {
    if ((await countOwnedUploads(userId, pathnames)) === pathnames.length) {
      return true;
    }
    await sleep(UPLOAD_COMPLETION_WAIT_MS);
  }
  return false;
}

export async function POST(request: Request) {
  const userId = await getUserId();
  if (!userId) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  const parsed = createAnalysisSchema.safeParse(await request.json());
  if (!parsed.success) {
    return NextResponse.json(
      { error: parsed.error.flatten() },
      { status: 400 },
    );
  }
  const input = parsed.data;
  const pathnames = input.documents.map((document) => document.blobPathname);
  if (!(await waitForOwnedUploads(userId, pathnames))) {
    return NextResponse.json(
      { error: "one or more uploads are missing or not owned by current user" },
      { status: 400 },
    );
  }
  const id = await db.transaction(async (tx) => {
    const [analysis] = await tx
      .insert(analyses)
      .values({
        userId,
        consentLlmTransit: input.consentLlmTransit,
        distributionAttestation: input.distributionAttestation,
        expiresAt: sql`now() + interval '7 days'`,
      })
      .returning({ id: analyses.id });
    await tx.insert(documents).values(
      input.documents.map((d) => ({
        analysisId: analysis.id,
        kind: d.kind,
        displayName: d.displayName,
        blobPathname: d.blobPathname,
      })),
    );
    return analysis.id;
  });
  return NextResponse.json({ id }, { status: 201 });
}
```

- [ ] **Step 7: Verify auth gating and creation with curl**

With `npm run dev` running:

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:3000/api/analyses \
  -H 'content-type: application/json' -d '{}'
```

Expected: `401`.

Then in a signed-in browser session, from devtools console:

First register fake completed uploads for the signed-in user. This keeps the `/api/analyses` smoke test DB-only; the real Blob path is exercised by Task 9/10.

```bash
docker compose -f docker-compose.dev.yml exec postgres psql -U postgres -d agentic_review -c "
WITH current_user_row AS (
  SELECT id FROM users ORDER BY created_at DESC LIMIT 1
)
INSERT INTO uploads (user_id, blob_pathname, display_name, content_type, size_bytes)
SELECT id, 'uploads/sol.pdf', 'sol.pdf', 'application/pdf', 1 FROM current_user_row
UNION ALL
SELECT id, 'uploads/deck.pptx', 'deck.pptx', 'application/vnd.openxmlformats-officedocument.presentationml.presentation', 1 FROM current_user_row
ON CONFLICT (blob_pathname) DO NOTHING;
"
```

```js
fetch("/api/analyses", {
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify({
    consentLlmTransit: true,
    distributionAttestation: true,
    documents: [
      { kind: "solicitation_base", displayName: "sol.pdf", blobPathname: "uploads/sol.pdf" },
      { kind: "deck", displayName: "deck.pptx", blobPathname: "uploads/deck.pptx" },
    ],
  }),
}).then((r) => r.json()).then(console.log);
```

Expected: `{ id: "<uuid>" }` — and within ~10s the running local worker picks it up and completes it (check with `psql ... -c "SELECT status, stage FROM analyses ORDER BY created_at DESC LIMIT 1"`).

- [ ] **Step 8: Run checks and commit**

Run: `npm test && npx tsc --noEmit`
Expected: all pass.

```bash
git add web/src/lib/validation.ts web/src/lib/validation.test.ts web/src/app/api/upload web/src/app/api/analyses web/package.json web/package-lock.json
git commit -m "feat(web): private blob upload token route and create-analysis API"
```

---

### Task 8: Status API + status page

**Files:**

- Create: `web/src/app/api/analyses/[id]/route.ts`
- Create: `web/src/app/analysis/[id]/page.tsx`
- Create: `web/src/app/analysis/[id]/status-view.tsx`

**Interfaces:**

- Consumes: `getUserId()`, `db`, `analyses` schema, worker stage writes (`stage`, `stage_detail`).
- Produces: `GET /api/analyses/:id` → `{ id, status, stage, stageDetail, error, createdAt }` (404 for non-owner — existence is not leaked); `/analysis/[id]` page polling every 2s. Task 9 redirects here after upload; Phase 5's report page slots in next to it.

- [ ] **Step 1: Implement the status route**

`web/src/app/api/analyses/[id]/route.ts`:

```ts
import { NextResponse } from "next/server";
import { and, eq } from "drizzle-orm";
import { db } from "@/db";
import { analyses } from "@/db/schema";
import { getUserId } from "@/lib/session";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const userId = await getUserId();
  if (!userId) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  const { id } = await params;
  const uuidRe =
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  if (!uuidRe.test(id)) {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }
  const [row] = await db
    .select({
      id: analyses.id,
      status: analyses.status,
      stage: analyses.stage,
      stageDetail: analyses.stageDetail,
      error: analyses.error,
      createdAt: analyses.createdAt,
    })
    .from(analyses)
    .where(and(eq(analyses.id, id), eq(analyses.userId, userId)));
  if (!row) {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }
  return NextResponse.json(row);
}
```

- [ ] **Step 2: Implement the status page (server shell + client poller)**

`web/src/app/analysis/[id]/page.tsx`:

```tsx
import { redirect } from "next/navigation";
import { auth } from "@/auth";
import { StatusView } from "./status-view";

export default async function AnalysisPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const session = await auth();
  if (!session) redirect("/");
  const { id } = await params;
  return (
    <main className="mx-auto max-w-2xl p-8">
      <h1 className="mb-6 text-xl font-semibold">Analysis</h1>
      <StatusView analysisId={id} />
    </main>
  );
}
```

`web/src/app/analysis/[id]/status-view.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";

type AnalysisStatus = {
  id: string;
  status: "queued" | "running" | "complete" | "failed";
  stage: string | null;
  stageDetail: string | null;
  error: string | null;
};

export function StatusView({ analysisId }: { analysisId: string }) {
  const [data, setData] = useState<AnalysisStatus | null>(null);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    let stopped = false;
    async function poll() {
      const res = await fetch(`/api/analyses/${analysisId}`);
      if (res.status === 404) {
        setNotFound(true);
        return;
      }
      const body = (await res.json()) as AnalysisStatus;
      if (stopped) return;
      setData(body);
      if (body.status === "queued" || body.status === "running") {
        setTimeout(poll, 2000);
      }
    }
    poll();
    return () => {
      stopped = true;
    };
  }, [analysisId]);

  if (notFound) return <p>Analysis not found.</p>;
  if (!data) return <p>Loading…</p>;

  return (
    <div className="space-y-2">
      <p>
        Status: <span className="font-mono">{data.status}</span>
      </p>
      {data.stage && (
        <p>
          Stage: <span className="font-mono">{data.stage}</span>
          {data.stageDetail ? ` — ${data.stageDetail}` : null}
        </p>
      )}
      {data.status === "failed" && (
        <p className="text-red-600">Failed: {data.error}</p>
      )}
      {data.status === "complete" && (
        <p className="text-green-700">
          Analysis complete. (Report screen arrives in Phase 5.)
        </p>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Verify ownership and live progress manually**

With `npm run dev` and the local worker running: create an analysis via the Task 7 devtools snippet, then open `/analysis/<id>`.
Expected: status advances `queued → running` with stub stages (`ingest → review → report`) updating live, ending `complete`.

Then verify non-owner 404: `curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3000/api/analyses/<id>` (no cookie).
Expected: `401`. (Cross-user 404 is covered once a second Keycloak account exists; the query's `userId` predicate enforces it.)

- [ ] **Step 4: Run checks and commit**

Run: `npm test && npx tsc --noEmit`
Expected: pass.

```bash
git add web/src/app/api/analyses web/src/app/analysis
git commit -m "feat(web): ownership-checked status API and polling status page"
```

---

### Task 9: Upload page (end-to-end flow)

**Files:**

- Create: `web/src/app/upload-form.tsx`
- Modify: `web/src/app/page.tsx` (replace Task 6 smoke page)

**Interfaces:**

- Consumes: `upload()` from `@vercel/blob/client` against `POST /api/upload` (Task 7); `POST /api/analyses` (Task 7); `/analysis/[id]` (Task 8); `CreateAnalysisInput["documents"][number]["kind"]` values.
- Produces: the working `/` upload screen — signed-in users upload a solicitation package + deck + optional script, attest, submit, and land on the status page.

- [ ] **Step 1: Implement the upload form**

`web/src/app/upload-form.tsx`:

```tsx
"use client";

import { upload } from "@vercel/blob/client";
import { useRouter } from "next/navigation";
import { useState } from "react";

type Kind =
  | "solicitation_base"
  | "solicitation_amendment"
  | "solicitation_q_and_a"
  | "solicitation_attachment"
  | "deck"
  | "script";

type PendingDoc = { kind: Kind; file: File };

function FileInput({
  label,
  accept,
  multiple,
  onFiles,
}: {
  label: string;
  accept: string;
  multiple?: boolean;
  onFiles: (files: File[]) => void;
}) {
  return (
    <label className="block space-y-1">
      <span className="text-sm font-medium">{label}</span>
      <input
        type="file"
        accept={accept}
        multiple={multiple}
        className="block w-full text-sm"
        onChange={(e) => onFiles(Array.from(e.target.files ?? []))}
      />
    </label>
  );
}

export function UploadForm() {
  const router = useRouter();
  const [base, setBase] = useState<File | null>(null);
  const [amendments, setAmendments] = useState<File[]>([]);
  const [qAndA, setQAndA] = useState<File[]>([]);
  const [attachments, setAttachments] = useState<File[]>([]);
  const [deck, setDeck] = useState<File | null>(null);
  const [script, setScript] = useState<File | null>(null);
  const [consent, setConsent] = useState(false);
  const [markings, setMarkings] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const ready = base && deck && consent && markings && !busy;

  async function submit() {
    if (!base || !deck) return;
    setError(null);
    const docs: PendingDoc[] = [
      { kind: "solicitation_base", file: base },
      ...amendments.map(
        (file): PendingDoc => ({ kind: "solicitation_amendment", file }),
      ),
      ...qAndA.map(
        (file): PendingDoc => ({ kind: "solicitation_q_and_a", file }),
      ),
      ...attachments.map(
        (file): PendingDoc => ({ kind: "solicitation_attachment", file }),
      ),
      { kind: "deck", file: deck },
      ...(script ? [{ kind: "script" as Kind, file: script }] : []),
    ];
    try {
      const uploaded = [];
      for (const doc of docs) {
        setBusy(`Uploading ${doc.file.name}…`);
        const blob = await upload(`uploads/${doc.file.name}`, doc.file, {
          access: "private",
          handleUploadUrl: "/api/upload",
        });
        uploaded.push({
          kind: doc.kind,
          displayName: doc.file.name,
          blobPathname: blob.pathname,
        });
      }
      setBusy("Starting analysis…");
      const res = await fetch("/api/analyses", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          consentLlmTransit: true,
          distributionAttestation: true,
          documents: uploaded,
        }),
      });
      if (!res.ok) throw new Error((await res.text()) || "creation failed");
      const { id } = (await res.json()) as { id: string };
      router.push(`/analysis/${id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(null);
    }
  }

  return (
    <div className="space-y-6">
      <FileInput
        label="Solicitation (base document, PDF) — required"
        accept="application/pdf"
        onFiles={(f) => setBase(f[0] ?? null)}
      />
      <FileInput
        label="Amendments (PDF, optional)"
        accept="application/pdf"
        multiple
        onFiles={setAmendments}
      />
      <FileInput
        label="Q&A documents (PDF, optional)"
        accept="application/pdf"
        multiple
        onFiles={setQAndA}
      />
      <FileInput
        label="Solicitation attachments (PDF, optional)"
        accept="application/pdf"
        multiple
        onFiles={setAttachments}
      />
      <FileInput
        label="Proposal deck (PPTX or PDF) — required"
        accept="application/pdf,application/vnd.openxmlformats-officedocument.presentationml.presentation"
        onFiles={(f) => setDeck(f[0] ?? null)}
      />
      <FileInput
        label="Narration script (TXT with 'Slide N:' markers, optional)"
        accept="text/plain"
        onFiles={(f) => setScript(f[0] ?? null)}
      />

      <div className="space-y-2 rounded border p-4">
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            checked={consent}
            onChange={(e) => setConsent(e.target.checked)}
          />
          <span>
            I am authorized to submit these documents and consent to their
            content being processed by a third-party LLM API (Anthropic).
          </span>
        </label>
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            checked={markings}
            onChange={(e) => setMarkings(e.target.checked)}
          />
          <span>
            I have checked distribution markings: none of these documents are
            marked Proprietary, Source Selection Sensitive, CUI, or ITAR. (If
            any are, stop and get info-security sign-off first.)
          </span>
        </label>
      </div>

      <button
        disabled={!ready}
        onClick={submit}
        className="rounded bg-black px-4 py-2 text-white disabled:opacity-40"
      >
        {busy ?? "Analyze"}
      </button>
      {error && <p className="text-sm text-red-600">{error}</p>}
    </div>
  );
}
```

- [ ] **Step 2: Replace the home page**

`web/src/app/page.tsx`:

```tsx
import { auth, signIn, signOut } from "@/auth";
import { UploadForm } from "./upload-form";

export default async function Home() {
  const session = await auth();
  if (!session) {
    return (
      <main className="mx-auto max-w-2xl p-8">
        <h1 className="mb-6 text-xl font-semibold">AI Proposal Review Board</h1>
        <form
          action={async () => {
            "use server";
            await signIn("keycloak");
          }}
        >
          <button className="rounded bg-black px-4 py-2 text-white">
            Sign in with Keycloak
          </button>
        </form>
      </main>
    );
  }
  return (
    <main className="mx-auto max-w-2xl space-y-6 p-8">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">AI Proposal Review Board</h1>
        <form
          action={async () => {
            "use server";
            await signOut();
          }}
        >
          <button className="text-sm underline">
            Sign out ({session.user?.email})
          </button>
        </form>
      </div>
      <UploadForm />
    </main>
  );
}
```

- [ ] **Step 3: Verify the full local loop**

**The full Blob path cannot complete against bare `localhost`.** `onUploadCompleted` is a webhook — Vercel's servers call your `handleUploadUrl` after the upload finishes, and they can't reach `localhost`. Without it the `uploads` row is never written, so `/api/analyses` correctly rejects the submit with "uploads are missing or not owned". Two ways to verify locally:

1. **Tunnel (real webhook path):** expose the dev server (e.g. `ngrok http 3000`), set the tunnel URL as the app origin (`AUTH_URL`, and open the app via the tunnel URL so `handleUploadUrl` resolves publicly), add the tunnel callback URL to Keycloak's redirect URIs, then run the flow. Requires a real `BLOB_READ_WRITE_TOKEN` in `web/.env.local`.
2. **Seeding workaround (no tunnel):** run the flow, let `/api/analyses` reject, then insert the `uploads` rows for the just-uploaded pathnames with the Task 7 Step 7 psql pattern and resubmit.

Either way — the **Task 10 deployed smoke test is the authoritative check** of the real webhook path; don't skip it.

With `npm run dev` + worker running: sign in → pick a small PDF as solicitation, a PPTX as deck → check both boxes → Analyze.
Expected: per-file upload progress text, redirect to `/analysis/<id>`, stub stages advance, `complete`.

- [ ] **Step 4: Run checks and commit**

Run: `npm test && npx tsc --noEmit`
Expected: pass.

```bash
git add web/src/app/page.tsx web/src/app/upload-form.tsx
git commit -m "feat(web): upload screen with attestations wired to blob and analyses API"
```

---

### Task 10: Deploy (Vercel + Railway) and production smoke test

**Files:**

- Create: `web/.env.production.notes.md` (checklist of required env vars — no secrets)

**Interfaces:**

- Consumes: everything above.
- Produces: live URLs — web on Vercel, worker + Postgres on Railway; documented env var matrix.

- [ ] **Step 1: Railway — Postgres + worker**

In the Railway dashboard (or `railway` CLI):

1. Create project `agentic-review`.
2. Add a **PostgreSQL** service; copy its `DATABASE_URL` (public network URL for now).
3. Add a service from the repo, root directory `worker/`, builder = Dockerfile.
4. Set worker env vars: `DATABASE_URL` = reference to the Postgres service's internal URL, `POLL_INTERVAL_SECONDS=2`.

- [ ] **Step 2: Apply migrations to Railway Postgres**

```bash
cd web
DATABASE_URL="<railway-public-database-url>" npm run db:migrate
```

Expected: migration applies; verify with Railway's data tab or `psql` (`\dt` shows `users`, `analyses`, `documents`, `uploads`).

- [ ] **Step 3: Vercel — web app + Blob store**

1. `cd web && npx vercel link` (create project `agentic-review`, root `web/`).
2. In the Vercel dashboard: create a **Blob store** attached to the project (this injects `BLOB_READ_WRITE_TOKEN`).
3. Set env vars (Production): `DATABASE_URL` (Railway public URL), `AUTH_SECRET` (fresh: `npx auth secret --raw`), `AUTH_KEYCLOAK_ID`, `AUTH_KEYCLOAK_SECRET`, `AUTH_KEYCLOAK_ISSUER`, `AUTH_URL` = `https://<production-domain>`.
4. In Keycloak admin: add `https://<production-domain>/api/auth/callback/keycloak` to the client's valid redirect URIs.
5. Deploy: `npx vercel --prod`.

`web/.env.production.notes.md` — record the env matrix (names, where each value comes from, **no secret values**):

```markdown
# Production environment variables

| Var | Where set | Source |
| --- | --- | --- |
| DATABASE_URL | Vercel + Railway worker | Railway Postgres (public URL for Vercel, internal for worker) |
| AUTH_SECRET | Vercel | `npx auth secret --raw` |
| AUTH_KEYCLOAK_ID / _SECRET / _ISSUER | Vercel | getgaleo.com Keycloak admin (client + realm) |
| AUTH_URL | Vercel | production domain |
| BLOB_READ_WRITE_TOKEN | Vercel (auto) | Blob store attachment |
| POLL_INTERVAL_SECONDS | Railway worker | `2` |
| WORKER_ID | Railway worker (optional) | defaults to hostname |
```

- [ ] **Step 4: Production smoke test**

1. Open the production URL → sign in through `getgaleo.com`.
2. Upload a small PDF + PPTX, check both attestations, submit.
3. Watch `/analysis/<id>`: stub stages advance and finish `complete` (proves: auth, private Blob upload, DB write, worker claim over Railway networking, status polling).
4. Confirm unauthenticated access fails: `curl -s -o /dev/null -w "%{http_code}\n" https://<domain>/api/analyses/<id>` → `401`.
5. Check Railway worker logs show `claimed analysis` / `completed analysis`.

- [ ] **Step 5: Commit**

```bash
git add web/.env.production.notes.md
git commit -m "docs: production env var matrix for vercel + railway deploys"
```

---

## Phase 1 exit criteria

- All worker tests green (`cd worker && pytest` — 14 tests) and web tests green (`cd web && npm test` — 9 tests); `tsc --noEmit` clean.
- Production: sign in via getgaleo.com Keycloak → upload → live stub-stage progress → `complete`, with ownership-gated APIs and private Blob storage.
- Phase 2 (Ingestion) starts by replacing `worker/src/worker/pipeline.py`'s stub body and adding the `pages` table migration — no other Phase 1 surface changes.
