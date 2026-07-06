import os
import pathlib

import psycopg
import pytest

MIGRATIONS_DIR = pathlib.Path(__file__).parents[2] / "web" / "drizzle"
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgres://postgres:dev@localhost:5435/agentic_review_test",
)


def apply_migrations(conn: psycopg.Connection) -> None:
    for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
        for stmt in sql_file.read_text().split("--> statement-breakpoint"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(stmt)


@pytest.fixture()
def conn():
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as c:
        c.execute("DROP SCHEMA public CASCADE")
        c.execute("CREATE SCHEMA public")
        apply_migrations(c)
        yield c


def insert_analysis(conn: psycopg.Connection, status: str = "queued") -> str:
    user_id = conn.execute(
        "INSERT INTO users (keycloak_sub, email) "
        "VALUES (gen_random_uuid()::text, 'test@example.com') RETURNING id"
    ).fetchone()[0]
    return str(
        conn.execute(
            """
            INSERT INTO analyses
                (user_id, status, consent_llm_transit, distribution_attestation, expires_at)
            VALUES (%s, %s, true, true, now() + interval '7 days')
            RETURNING id
            """,
            (user_id, status),
        ).fetchone()[0]
    )
