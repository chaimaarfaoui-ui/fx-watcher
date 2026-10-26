import os
import uuid
from pathlib import Path

import pytest

SCHEMA_SQL = (Path(__file__).resolve().parent.parent / "sql" / "schema.sql").read_text()


@pytest.fixture
def db():
    """A throwaway PostgreSQL schema per test. Skipped when no database is reachable."""
    psycopg = pytest.importorskip("psycopg")
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        pytest.skip("set DATABASE_URL to run database tests")
    try:
        conn = psycopg.connect(dsn, autocommit=True)
    except psycopg.OperationalError as exc:
        pytest.skip(f"database not reachable: {exc}")
    name = "t_" + uuid.uuid4().hex[:10]
    conn.execute(f"CREATE SCHEMA {name}")
    conn.execute(f"SET search_path TO {name}")
    conn.execute(SCHEMA_SQL)
    yield conn
    conn.execute(f"DROP SCHEMA {name} CASCADE")
    conn.close()
