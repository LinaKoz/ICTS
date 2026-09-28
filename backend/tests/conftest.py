"""Shared fixtures for DB-dependent tests (§8 T2 verification).

Needs a real Postgres reachable at `TEST_DATABASE_URL` (sync `psycopg`
URL, e.g. `postgresql://icts:icts@localhost:55432/icts`). Tests that
need it are marked `@requires_db` and skip cleanly when it isn't
reachable, so this suite also runs (mostly skipped) with no database.

`DATABASE_URL` is set here, before any `app.*` module is imported
elsewhere in the test session, so `app.config.settings` (read once, at
import time) points at the test database.
"""
from __future__ import annotations

import os
import subprocess
import sys

import psycopg
import pytest

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://icts:icts@localhost:55432/icts"
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

_APP_TABLES = (
    "roster_approvals",
    "roster_assignments",
    "rosters",
    "worker_field_history",
    "contract_versions",
    "csv_imports",
    "workers",
    "users",
)


def _db_reachable() -> bool:
    try:
        with psycopg.connect(TEST_DATABASE_URL, connect_timeout=2):
            return True
    except Exception:
        return False


DB_AVAILABLE = _db_reachable()
requires_db = pytest.mark.skipif(not DB_AVAILABLE, reason="no reachable Postgres (TEST_DATABASE_URL)")


@pytest.fixture(scope="session")
def _migrated_once():
    if not DB_AVAILABLE:
        pytest.skip("no reachable Postgres")
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend_dir,
        env=os.environ.copy(),
        check=True,
    )
    yield


@pytest.fixture()
def db(_migrated_once):
    """A raw sync connection, autocommit, with every app table truncated."""
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"TRUNCATE {', '.join(_APP_TABLES)} RESTART IDENTITY CASCADE")
        yield conn
