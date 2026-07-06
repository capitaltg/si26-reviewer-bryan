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


def test_update_stage_refreshes_heartbeat(conn):
    analysis_id = insert_analysis(conn)
    jobs.claim_job(conn, "w1")
    conn.execute(
        "UPDATE analyses SET locked_at = now() - make_interval(mins => 60) "
        "WHERE id = %s",
        (analysis_id,),
    )
    jobs.update_stage(conn, analysis_id, "ingest", "converting deck")
    assert jobs.requeue_stuck(conn, timeout_minutes=30) == (0, 0)
    status = conn.execute(
        "SELECT status FROM analyses WHERE id = %s", (analysis_id,)
    ).fetchone()[0]
    assert status == "running"
