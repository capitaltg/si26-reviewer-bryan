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


def update_stage(
    conn: psycopg.Connection,
    analysis_id: str,
    stage: str,
    detail: Optional[str] = None,
) -> None:
    conn.execute(
        "UPDATE analyses SET stage = %s, stage_detail = %s, locked_at = now() "
        "WHERE id = %s",
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
