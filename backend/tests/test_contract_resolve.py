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


@requires_db
def test_resolve_contracts_for_workers_matches_single_resolution(db):
    """Past, current and future months; same-month supersede (higher
    version_no wins); a worker with no applicable version is absent."""
    from app.contracts.resolve import resolve_contract, resolve_contracts_for_workers
    from app.db import async_session_factory

    user_id = _insert_user(db)
    w1 = _insert_worker(db)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO workers (national_id, full_name, role, status) VALUES ('987654321', 'W2', 'SCREENER', 'ACTIVE') RETURNING id"
        )
        w2 = cur.fetchone()[0]
    _insert_version(db, w1, user_id, 1, date(2026, 3, 1), "10.00")
    _insert_version(db, w1, user_id, 2, date(2026, 3, 1), "11.00")  # same-month revision supersedes
    _insert_version(db, w1, user_id, 3, date(2026, 6, 1), "12.00")  # future

    async def run():
        async with async_session_factory() as session:
            out = {}
            for m in (date(2026, 2, 1), date(2026, 3, 1), date(2026, 5, 1), date(2026, 6, 1)):
                bulk = await resolve_contracts_for_workers(session, [w1, w2], m)
                single = await resolve_contract(session, w1, m)
                out[m] = (bulk, single)
            return out

    out = asyncio.run(run())
    assert out[date(2026, 2, 1)][0] == {} and out[date(2026, 2, 1)][1] is None  # past: not yet effective
    assert out[date(2026, 3, 1)][0][w1].hourly_rate_ils == Decimal("11.00")  # current, superseded
    assert out[date(2026, 5, 1)][0][w1].hourly_rate_ils == Decimal("11.00")  # future month, latest <= M
    assert out[date(2026, 6, 1)][0][w1].hourly_rate_ils == Decimal("12.00")
    for bulk, single in out.values():
        assert (bulk.get(w1) is None and single is None) or bulk[w1].id == single.id
        assert w2 not in bulk  # no contract
