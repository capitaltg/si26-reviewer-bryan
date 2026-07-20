import uuid

import psycopg
import pytest
from psycopg.types.json import Jsonb

from conftest import insert_analysis


def insert_solicitation_document(conn: psycopg.Connection) -> tuple[str, str]:
    analysis_id = insert_analysis(conn)
    document_id = conn.execute(
        """
        INSERT INTO documents
            (analysis_id, kind, display_name, blob_pathname, blob_url, content_type)
        VALUES (%s, 'solicitation_base', 'solicitation.pdf', %s, %s, 'application/pdf')
        RETURNING id
        """,
        (analysis_id, "documents/solicitation.pdf", "https://example.test/solicitation.pdf"),
    ).fetchone()[0]
    return analysis_id, str(document_id)


def insert_requirement(conn: psycopg.Connection, analysis_id: str, document_id: str) -> str:
    requirement_id = conn.execute(
        """
        INSERT INTO requirements
            (analysis_id, source_document_id, source, ref, text, page_no, weight)
        VALUES (%s, %s, 'L', 'L.1', 'Provide the requested approach.', 2, NULL)
        RETURNING id
        """,
        (analysis_id, document_id),
    ).fetchone()[0]
    return str(requirement_id)


def insert_mapping(conn: psycopg.Connection, requirement_id: str) -> None:
    conn.execute(
        """
        INSERT INTO mappings (requirement_id, status, slide_refs, rationale)
        VALUES (%s, 'covered', %s, 'The approach is addressed on slide 1.')
        """,
        (requirement_id, Jsonb([{"slide_no": 1}])),
    )


def test_duplicate_mapping_requirement_id_raises_unique_violation(conn):
    analysis_id, document_id = insert_solicitation_document(conn)
    requirement_id = insert_requirement(conn, analysis_id, document_id)
    insert_mapping(conn, requirement_id)

    with pytest.raises(psycopg.errors.UniqueViolation):
        insert_mapping(conn, requirement_id)


def test_deleting_requirement_cascades_to_mapping(conn):
    analysis_id, document_id = insert_solicitation_document(conn)
    requirement_id = insert_requirement(conn, analysis_id, document_id)
    insert_mapping(conn, requirement_id)

    conn.execute("DELETE FROM requirements WHERE id = %s", (requirement_id,))

    assert conn.execute(
        "SELECT count(*) FROM mappings WHERE requirement_id = %s", (requirement_id,)
    ).fetchone()[0] == 0


def test_requirement_source_document_requires_existing_document(conn):
    analysis_id = insert_analysis(conn)

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute(
            """
            INSERT INTO requirements
                (analysis_id, source_document_id, source, ref, text, page_no)
            VALUES (%s, %s, 'SOW', 'SOW.1', 'Provide the service.', 4)
            """,
            (analysis_id, uuid.uuid4()),
        )
