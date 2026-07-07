"""Pipeline stages: ingest -> vision -> script_align (optional) -> review
(stub) -> report (stub).

Phase 2 replaces the ingest/vision/script_align stages with real work;
review and report stay stub sleeps until their own phases land. The
signature and the update_stage/complete/fail contract stay the same as the
Phase 1 stub."""

import time

import psycopg

from . import ingest, jobs, script_align, vision

STAGE_SLEEP_SECONDS = 2

# Stub stages only -- ingest, vision, and script_align are real work now,
# driven directly by run_pipeline below rather than this list.
STUB_STAGES = [
    ("review", "running reviewers (stub)"),
    ("report", "assembling report (stub)"),
]


def run_pipeline(conn: psycopg.Connection, analysis_id: str) -> None:
    _run_ingest_stage(conn, analysis_id)

    jobs.update_stage(
        conn, analysis_id, "vision", "enriching deck pages with vision descriptions"
    )
    vision.run_vision_pass(conn, analysis_id)

    if _has_script_document(conn, analysis_id):
        jobs.update_stage(
            conn, analysis_id, "script_align", "aligning narration script to deck pages"
        )
        script_align.align_script(conn, analysis_id)

    for stage, detail in STUB_STAGES:
        jobs.update_stage(conn, analysis_id, stage, detail)
        time.sleep(STAGE_SLEEP_SECONDS)


def _run_ingest_stage(conn: psycopg.Connection, analysis_id: str) -> None:
    """Ingest every non-`script` document belonging to `analysis_id`,
    reporting document-loop progress (`"page {i}/{n} — {display_name}"`)
    before each document is ingested.

    Mirrors the query shape of `ingest.ingest_analysis` (deliberately not
    called directly: it has no per-document progress hook), plus
    `display_name` for the progress detail string.
    """
    rows = conn.execute(
        "SELECT id, kind, blob_pathname, blob_url, content_type, display_name "
        "FROM documents WHERE analysis_id = %s AND kind != 'script' "
        "ORDER BY id",
        (analysis_id,),
    ).fetchall()
    total = len(rows)
    for index, row in enumerate(rows, start=1):
        document = ingest.Document(
            id=str(row[0]),
            kind=row[1],
            blob_pathname=row[2],
            blob_url=row[3],
            content_type=row[4],
        )
        display_name = row[5]
        jobs.update_stage(
            conn, analysis_id, "ingest", f"page {index}/{total} — {display_name}"
        )
        ingest.ingest_document(conn, analysis_id, document)


def _has_script_document(conn: psycopg.Connection, analysis_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM documents WHERE analysis_id = %s AND kind = 'script'",
        (analysis_id,),
    ).fetchone()
    return row is not None
