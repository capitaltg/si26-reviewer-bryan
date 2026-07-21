import psycopg
import pytest
from psycopg.types.json import Json

from conftest import insert_analysis


def _insert_summary(conn, analysis_id, *, summary_text="An executive summary.", notes=None):
    return conn.execute(
        """
        INSERT INTO summaries (analysis_id, summary_text, disagreement_notes)
        VALUES (%s, %s, %s)
        RETURNING id
        """,
        (analysis_id, summary_text, Json([] if notes is None else notes)),
    ).fetchone()[0]


def test_summary_persists_and_cascades(conn):
    analysis_id = insert_analysis(conn)
    _insert_summary(
        conn,
        analysis_id,
        notes=[{"finding_ids": ["a", "b"], "reviewers": ["compliance", "technical"], "note": "n"}],
    )

    conn.execute("DELETE FROM analyses WHERE id = %s", (analysis_id,))

    assert conn.execute("SELECT count(*) FROM summaries").fetchone()[0] == 0


def test_summary_is_unique_per_analysis(conn):
    analysis_id = insert_analysis(conn)
    _insert_summary(conn, analysis_id)
    with pytest.raises(psycopg.errors.UniqueViolation):
        _insert_summary(conn, analysis_id)


def test_summary_text_must_be_non_empty(conn):
    analysis_id = insert_analysis(conn)
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert_summary(conn, analysis_id, summary_text="   ")


def test_disagreement_notes_must_be_a_json_array(conn):
    analysis_id = insert_analysis(conn)
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "INSERT INTO summaries (analysis_id, summary_text, disagreement_notes) "
            "VALUES (%s, %s, %s)",
            (analysis_id, "ok", Json({"not": "an array"})),
        )


def test_disagreement_notes_defaults_to_empty_array(conn):
    analysis_id = insert_analysis(conn)
    conn.execute(
        "INSERT INTO summaries (analysis_id, summary_text) VALUES (%s, %s)",
        (analysis_id, "ok"),
    )
    row = conn.execute(
        "SELECT disagreement_notes FROM summaries WHERE analysis_id = %s", (analysis_id,)
    ).fetchone()
    assert row[0] == []
