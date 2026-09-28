"""Constraint tests against a real Postgres (§8 T2 "Verification"):
the national_id regex, min<=max, unique month, and both immutability
triggers (`contract_versions`, `worker_field_history`)."""
from __future__ import annotations

import psycopg
import pytest

from tests.conftest import requires_db


def _insert_user(conn) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (username, display_name, password_hash, app_role) "
            "VALUES ('u1', 'U', 'h', 'PLANNER') RETURNING id"
        )
        return cur.fetchone()[0]


def _insert_worker(conn, national_id: str = "123456789") -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO workers (national_id, full_name, role, status) "
            "VALUES (%s, 'W', 'GENERAL_GUARD', 'ACTIVE') RETURNING id",
            (national_id,),
        )
        return cur.fetchone()[0]


@requires_db
def test_national_id_regex_rejects_non_digits(db):
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO workers (national_id, full_name, role, status) "
                "VALUES ('12345678A', 'W', 'GENERAL_GUARD', 'ACTIVE')"
            )


@requires_db
def test_national_id_regex_rejects_wrong_length(db):
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO workers (national_id, full_name, role, status) "
                "VALUES ('12345', 'W', 'GENERAL_GUARD', 'ACTIVE')"
            )


@requires_db
def test_national_id_regex_accepts_nine_digits(db):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO workers (national_id, full_name, role, status) "
            "VALUES ('123456789', 'W', 'GENERAL_GUARD', 'ACTIVE')"
        )


@requires_db
def test_national_id_unique(db):
    _insert_worker(db, "123456789")
    with pytest.raises(psycopg.errors.UniqueViolation):
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO workers (national_id, full_name, role, status) "
                "VALUES ('123456789', 'W2', 'GENERAL_GUARD', 'ACTIVE')"
            )


@requires_db
def test_contract_min_hours_le_max_hours(db):
    user_id = _insert_user(db)
    worker_id = _insert_worker(db)
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO contract_versions "
                "(worker_id, version_no, effective_month, hourly_rate_ils, min_hours, max_hours, "
                " availability, created_by, source) "
                "VALUES (%s, 1, '2026-01-01', 50.00, 100, 50, '[]'::jsonb, %s, 'UI')",
                (worker_id, user_id),
            )


@requires_db
def test_contract_effective_month_must_be_day_one(db):
    user_id = _insert_user(db)
    worker_id = _insert_worker(db)
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO contract_versions "
                "(worker_id, version_no, effective_month, hourly_rate_ils, min_hours, max_hours, "
                " availability, created_by, source) "
                "VALUES (%s, 1, '2026-01-15', 50.00, 0, 100, '[]'::jsonb, %s, 'UI')",
                (worker_id, user_id),
            )


@requires_db
def test_contract_versions_immutable_update_rejected(db):
    user_id = _insert_user(db)
    worker_id = _insert_worker(db)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO contract_versions "
            "(worker_id, version_no, effective_month, hourly_rate_ils, min_hours, max_hours, "
            " availability, created_by, source) "
            "VALUES (%s, 1, '2026-01-01', 50.00, 0, 100, '[]'::jsonb, %s, 'UI') RETURNING id",
            (worker_id, user_id),
        )
        row_id = cur.fetchone()[0]
    with pytest.raises(psycopg.errors.RaiseException):
        with db.cursor() as cur:
            cur.execute("UPDATE contract_versions SET version_no = 2 WHERE id = %s", (row_id,))


@requires_db
def test_contract_versions_immutable_delete_rejected(db):
    user_id = _insert_user(db)
    worker_id = _insert_worker(db)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO contract_versions "
            "(worker_id, version_no, effective_month, hourly_rate_ils, min_hours, max_hours, "
            " availability, created_by, source) "
            "VALUES (%s, 1, '2026-01-01', 50.00, 0, 100, '[]'::jsonb, %s, 'UI') RETURNING id",
            (worker_id, user_id),
        )
        row_id = cur.fetchone()[0]
    with pytest.raises(psycopg.errors.RaiseException):
        with db.cursor() as cur:
            cur.execute("DELETE FROM contract_versions WHERE id = %s", (row_id,))


@requires_db
def test_worker_field_history_immutable(db):
    user_id = _insert_user(db)
    worker_id = _insert_worker(db)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO worker_field_history (worker_id, field, old_value, new_value, effective_at, changed_by) "
            "VALUES (%s, 'STATUS', 'ACTIVE', 'INACTIVE', now(), %s) RETURNING id",
            (worker_id, user_id),
        )
        row_id = cur.fetchone()[0]
    with pytest.raises(psycopg.errors.RaiseException):
        with db.cursor() as cur:
            cur.execute("DELETE FROM worker_field_history WHERE id = %s", (row_id,))


@requires_db
def test_rosters_month_unique_and_day_one(db):
    user_id = _insert_user(db)
    with db.cursor() as cur:
        cur.execute("INSERT INTO rosters (month, updated_by) VALUES ('2026-02-01', %s)", (user_id,))
    with pytest.raises(psycopg.errors.UniqueViolation):
        with db.cursor() as cur:
            cur.execute("INSERT INTO rosters (month, updated_by) VALUES ('2026-02-01', %s)", (user_id,))
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.cursor() as cur:
            cur.execute("INSERT INTO rosters (month, updated_by) VALUES ('2026-03-15', %s)", (user_id,))
