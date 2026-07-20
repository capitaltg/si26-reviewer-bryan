import uuid

import psycopg
import pytest
from psycopg.types.json import Jsonb

from conftest import insert_analysis


def _analysis_with_requirement(conn):
    analysis_id = insert_analysis(conn)
    document_id = conn.execute(
        """
        INSERT INTO documents
            (analysis_id, kind, display_name, blob_pathname, blob_url, content_type)
        VALUES (%s, 'solicitation_base', 'solicitation.pdf', %s, %s, 'application/pdf')
        RETURNING id
        """,
        (analysis_id, "documents/s.pdf", "https://example.test/s.pdf"),
    ).fetchone()[0]
    requirement_id = conn.execute(
        """
        INSERT INTO requirements
            (analysis_id, source_document_id, source, ref, text, page_no)
        VALUES (%s, %s, 'L', 'L.1', 'Provide the approach.', 2)
        RETURNING id
        """,
        (analysis_id, document_id),
    ).fetchone()[0]
    return analysis_id, str(requirement_id)


def _insert_finding(conn, analysis_id, requirement_id, **overrides):
    values = {
        "reviewer": "compliance",
        "finding_kind": "observation",
        "severity": "high",
        "confidence": "medium",
        "requirement_id": requirement_id,
        "evidence": Jsonb(
            {
                "solicitation": {
                    "document_id": "d",
                    "document_name": "solicitation.pdf",
                    "ref": "L.1",
                    "page": 2,
                    "quote": "Provide the approach.",
                },
                "proposal": {"slide": 1, "quote": "Our approach is X."},
            }
        ),
        "evidence_provenance": "native_text",
        "description": "Addressed on slide 1.",
        "suggestion": "Keep it.",
        "solicitation_verified": True,
        "proposal_verified": True,
        "verification": "verified",
    }
    values.update(overrides)
    return conn.execute(
        """
        INSERT INTO findings
            (analysis_id, reviewer, finding_kind, severity, confidence,
             requirement_id, evidence, evidence_provenance, description,
             suggestion, cluster_id, solicitation_verified, proposal_verified,
             verification)
        VALUES (%(analysis_id)s, %(reviewer)s, %(finding_kind)s, %(severity)s,
                %(confidence)s, %(requirement_id)s, %(evidence)s,
                %(evidence_provenance)s, %(description)s, %(suggestion)s, NULL,
                %(solicitation_verified)s, %(proposal_verified)s,
                %(verification)s)
        RETURNING id
        """,
        {"analysis_id": analysis_id, **values},
    ).fetchone()[0]


def test_deleting_analysis_cascades_to_findings(conn):
    analysis_id, requirement_id = _analysis_with_requirement(conn)
    _insert_finding(conn, analysis_id, requirement_id)

    conn.execute("DELETE FROM analyses WHERE id = %s", (analysis_id,))

    assert conn.execute("SELECT count(*) FROM findings").fetchone()[0] == 0


def test_deleting_requirement_nulls_finding_requirement_id(conn):
    analysis_id, requirement_id = _analysis_with_requirement(conn)
    finding_id = _insert_finding(conn, analysis_id, requirement_id)

    conn.execute("DELETE FROM requirements WHERE id = %s", (requirement_id,))

    row = conn.execute(
        "SELECT requirement_id FROM findings WHERE id = %s", (finding_id,)
    ).fetchone()
    assert row[0] is None


def test_gap_finding_persists_with_null_proposal_fields(conn):
    analysis_id, requirement_id = _analysis_with_requirement(conn)
    finding_id = _insert_finding(
        conn,
        analysis_id,
        requirement_id,
        finding_kind="gap",
        evidence=Jsonb(
            {
                "solicitation": {
                    "document_id": "d",
                    "document_name": "solicitation.pdf",
                    "ref": "L.1",
                    "page": 2,
                    "quote": "Provide the approach.",
                },
                "searched_scope": "Searched all 3 deck slides.",
            }
        ),
        evidence_provenance=None,
        proposal_verified=None,
        verification="verified",
    )
    assert finding_id is not None


def test_gap_requires_proposal_verified_null(conn):
    analysis_id, requirement_id = _analysis_with_requirement(conn)
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert_finding(
            conn,
            analysis_id,
            requirement_id,
            finding_kind="gap",
            evidence_provenance=None,
            proposal_verified=False,
            verification="unverified",
        )


def test_observation_requires_proposal_verified(conn):
    analysis_id, requirement_id = _analysis_with_requirement(conn)
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert_finding(
            conn,
            analysis_id,
            requirement_id,
            proposal_verified=None,
            evidence_provenance=None,
            verification="unverified",
        )


def test_provenance_without_passing_proposal_violates_check(conn):
    analysis_id, requirement_id = _analysis_with_requirement(conn)
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert_finding(
            conn,
            analysis_id,
            requirement_id,
            proposal_verified=False,
            evidence_provenance="native_text",
            verification="unverified",
        )


def test_passing_proposal_requires_provenance(conn):
    analysis_id, requirement_id = _analysis_with_requirement(conn)
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert_finding(
            conn,
            analysis_id,
            requirement_id,
            proposal_verified=True,
            evidence_provenance=None,
            verification="unverified",
        )


def test_verified_requires_both_sides_for_observation(conn):
    analysis_id, requirement_id = _analysis_with_requirement(conn)
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert_finding(
            conn,
            analysis_id,
            requirement_id,
            proposal_verified=False,
            evidence_provenance=None,
            verification="verified",
        )


def test_verified_gap_requires_solicitation_side(conn):
    analysis_id, requirement_id = _analysis_with_requirement(conn)
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert_finding(
            conn,
            analysis_id,
            requirement_id,
            finding_kind="gap",
            evidence_provenance=None,
            solicitation_verified=False,
            proposal_verified=None,
            verification="verified",
        )


def test_finding_rejects_invalid_reviewer_enum(conn):
    analysis_id, requirement_id = _analysis_with_requirement(conn)
    with pytest.raises(psycopg.errors.InvalidTextRepresentation):
        _insert_finding(
            conn,
            analysis_id,
            requirement_id,
            reviewer="unknown",
        )


def test_solicitation_verified_is_required(conn):
    analysis_id, requirement_id = _analysis_with_requirement(conn)
    with pytest.raises(psycopg.errors.NotNullViolation):
        _insert_finding(
            conn,
            analysis_id,
            requirement_id,
            solicitation_verified=None,
            verification="unverified",
        )


def test_finding_requires_existing_analysis(conn):
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute(
            """
            INSERT INTO findings
                (analysis_id, reviewer, finding_kind, severity, confidence,
                 evidence, description, suggestion, solicitation_verified,
                 verification)
            VALUES (%s, 'compliance', 'gap', 'low', 'low', %s, 'd', 's', true,
                    'verified')
            """,
            (uuid.uuid4(), Jsonb({})),
        )
