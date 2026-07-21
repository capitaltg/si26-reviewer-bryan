import pathlib
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


def test_requirement_classification_is_all_null_or_complete(conn):
    analysis_id, document_id = insert_solicitation_document(conn)

    legacy_id = insert_requirement(conn, analysis_id, document_id)
    assert conn.execute(
        """
        SELECT applies_to, obligation_type, obligation_side,
               classification_rationale
        FROM requirements WHERE id = %s
        """,
        (legacy_id,),
    ).fetchone() == (None, None, None, None)

    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            """
            INSERT INTO requirements
                (analysis_id, source_document_id, source, ref, text, page_no,
                 applies_to)
            VALUES (%s, %s, 'L', 'L.partial', 'Partial classification.', 1,
                    'deck')
            """,
            (analysis_id, document_id),
        )


def test_requirement_classification_requires_trimmed_rationale(conn):
    analysis_id, document_id = insert_solicitation_document(conn)

    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            """
            INSERT INTO requirements
                (analysis_id, source_document_id, source, ref, text, page_no,
                 applies_to, obligation_type, obligation_side,
                 classification_rationale)
            VALUES (%s, %s, 'L', 'L.blank', 'Blank rationale.', 1,
                    'deck', 'content', 'quoter', '   ')
            """,
            (analysis_id, document_id),
        )


def test_requirement_accepts_complete_classification(conn):
    analysis_id, document_id = insert_solicitation_document(conn)

    requirement_id = conn.execute(
        """
        INSERT INTO requirements
            (analysis_id, source_document_id, source, ref, text, page_no,
             applies_to, obligation_type, obligation_side,
             classification_rationale)
        VALUES (%s, %s, 'L', 'L.deck', 'Deck content.', 1,
                'deck', 'content', 'quoter', 'Factor 3 oral-presentation content')
        RETURNING id
        """,
        (analysis_id, document_id),
    ).fetchone()[0]

    assert requirement_id is not None


def test_applicability_migration_has_no_guessed_backfill_and_clears_mappings():
    migrations_dir = pathlib.Path(__file__).parents[2] / "web" / "drizzle"
    migration_files = sorted(migrations_dir.glob("0006_*.sql"))
    assert len(migration_files) == 1
    sql_text = migration_files[0].read_text()

    assert 'ADD COLUMN "applies_to"' in sql_text
    assert "DEFAULT 'deck'" not in sql_text
    assert "DEFAULT 'content'" not in sql_text
    assert "DEFAULT 'quoter'" not in sql_text
    assert 'DELETE FROM "mappings";' in sql_text
