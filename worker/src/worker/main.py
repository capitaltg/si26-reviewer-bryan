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
