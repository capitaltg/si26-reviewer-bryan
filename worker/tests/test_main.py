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
