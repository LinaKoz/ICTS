"""§3 "Contract resolution": effective_month <= M, ordered by
effective_month DESC, version_no DESC, first row."""
from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal

from tests.conftest import requires_db


def _insert_user(db) -> int:
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO users (username, display_name, password_hash, app_role) "
            "VALUES ('u1', 'U', 'h', 'PLANNER') RETURNING id"
        )
        return cur.fetchone()[0]


def _insert_worker(db) -> int:
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO workers (national_id, full_name, role, status) "
            "VALUES ('123456789', 'W', 'GENERAL_GUARD', 'ACTIVE') RETURNING id"
        )
        return cur.fetchone()[0]


def _insert_version(db, worker_id, user_id, version_no, effective_month, rate):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO contract_versions "
            "(worker_id, version_no, effective_month, hourly_rate_ils, min_hours, max_hours, "
            " availability, created_by, source) "
            "VALUES (%s, %s, %s, %s, 0, 100, '[]'::jsonb, %s, 'UI')",
            (worker_id, version_no, effective_month, rate, user_id),
        )


@requires_db
def test_resolve_contract_picks_latest_applicable_version(db):
    import app.models  # noqa: F401
    from app.contracts.resolve import resolve_contract
    from app.db import async_session_factory

    user_id = _insert_user(db)
    worker_id = _insert_worker(db)
    _insert_version(db, worker_id, user_id, 1, date(2026, 1, 1), Decimal("40.00"))
    _insert_version(db, worker_id, user_id, 2, date(2026, 3, 1), Decimal("45.00"))
    # a same-month revision (P1): higher version_no wins for that month.
    _insert_version(db, worker_id, user_id, 3, date(2026, 3, 1), Decimal("46.00"))
    # a future version must never resolve for an earlier month.
    _insert_version(db, worker_id, user_id, 4, date(2026, 6, 1), Decimal("50.00"))

    async def run():
        async with async_session_factory() as session:
            return await resolve_contract(session, worker_id, date(2026, 4, 1))

    resolved = asyncio.run(run())
    assert resolved is not None
    assert resolved.version_no == 3
    assert resolved.hourly_rate_ils == Decimal("46.00")


@requires_db
def test_resolve_contract_none_before_first_version(db):
    import app.models  # noqa: F401
    from app.contracts.resolve import resolve_contract
    from app.db import async_session_factory

    user_id = _insert_user(db)
    worker_id = _insert_worker(db)
    _insert_version(db, worker_id, user_id, 1, date(2026, 3, 1), Decimal("40.00"))

    async def run():
        async with async_session_factory() as session:
            return await resolve_contract(session, worker_id, date(2026, 1, 1))

    assert asyncio.run(run()) is None
