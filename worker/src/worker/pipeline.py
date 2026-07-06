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
