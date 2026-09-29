"""Raw-SQL insert helpers shared by the T3 roster tests (mirrors the
style of `tests/test_contract_resolve.py` and `tests/test_seed.py`)."""
from __future__ import annotations

from datetime import date


def insert_user(db, username: str = "u1", app_role: str = "PLANNER") -> int:
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO users (username, display_name, password_hash, app_role) "
            "VALUES (%s, %s, 'h', %s) RETURNING id",
            (username, username, app_role),
        )
        return cur.fetchone()[0]


def insert_worker(
    db, national_id: str, full_name: str = "W", role: str = "GENERAL_GUARD", status: str = "ACTIVE"
) -> int:
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO workers (national_id, full_name, role, status) VALUES (%s, %s, %s, %s) RETURNING id",
            (national_id, full_name, role, status),
        )
        return cur.fetchone()[0]


def insert_contract(
    db,
    worker_id: int,
    user_id: int,
    version_no: int = 1,
    effective_month: date = date(2026, 1, 1),
    rate: str = "40.00",
    min_hours: int = 0,
    max_hours: int = 200,
    availability: list[str] | None = None,
) -> int:
    import json

    availability = availability if availability is not None else [
        f"{day}:{shift}" for day in ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN") for shift in ("A", "B", "C")
    ]
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO contract_versions "
            "(worker_id, version_no, effective_month, hourly_rate_ils, min_hours, max_hours, "
            " availability, created_by, source) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'UI') RETURNING id",
            (worker_id, version_no, effective_month, rate, min_hours, max_hours, json.dumps(availability), user_id),
        )
        return cur.fetchone()[0]


def insert_roster(
    db, month: date, user_id: int, status: str = "DRAFT", forbid_adjacent_shifts: bool = False, row_version: int = 1
) -> int:
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO rosters (month, status, forbid_adjacent_shifts, row_version, updated_by) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (month, status, forbid_adjacent_shifts, row_version, user_id),
        )
        return cur.fetchone()[0]


def insert_assignment(db, roster_id: int, worker_id: int, d: date, shift: str, role: str) -> int:
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO roster_assignments (roster_id, worker_id, date, shift, role) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (roster_id, worker_id, d, shift, role),
        )
        return cur.fetchone()[0]


def insert_worker_field_history(db, worker_id: int, field: str, old_value: str, new_value: str, effective_at, changed_by: int) -> None:
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO worker_field_history (worker_id, field, old_value, new_value, effective_at, changed_by) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (worker_id, field, old_value, new_value, effective_at, changed_by),
        )


def insert_approval(db, roster_id: int, user_id: int, roster_version: int = 1) -> int:
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO roster_approvals (roster_id, roster_version, approved_by) VALUES (%s, %s, %s) RETURNING id",
            (roster_id, roster_version, user_id),
        )
        return cur.fetchone()[0]
