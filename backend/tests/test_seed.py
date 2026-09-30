"""§8 T2 "Verification": the seed is idempotent and only fills an empty workers table."""
from __future__ import annotations

import asyncio

from tests.conftest import requires_db


@requires_db
def test_seed_is_idempotent(db):
    import app.models  # noqa: F401
    from app.db import async_session_factory
    from app.seed import seed

    async def run_seed_twice():
        async with async_session_factory() as session:
            await seed(session)
        async with async_session_factory() as session:
            await seed(session)

    asyncio.run(run_seed_twice())

    with db.cursor() as cur:
        cur.execute("SELECT username, app_role FROM users ORDER BY username")
        users = cur.fetchall()
        cur.execute("SELECT count(*) FROM workers")
        worker_count = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM contract_versions")
        contract_count = cur.fetchone()[0]
        cur.execute(
            "SELECT count(*), min(c.max_hours), max(c.max_hours), min(c.hourly_rate_ils), max(c.hourly_rate_ils) "
            "FROM contract_versions c JOIN workers w ON w.id = c.worker_id WHERE w.national_id LIKE '9000%'"
        )
        extra = cur.fetchone()

    assert users == [("manager", "MANAGER"), ("planner", "PLANNER")]
    assert worker_count == 30  # one insert only, not duplicated by the 2nd run
    assert contract_count == 30
    assert extra == (25, 200, 200, 50, 50)


@requires_db
def test_seed_never_overwrites_existing_password(db):
    import app.models  # noqa: F401
    from app.auth.security import hash_password, verify_password
    from app.db import async_session_factory
    from app.seed import seed

    custom_hash = hash_password("a-custom-password")
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO users (username, display_name, password_hash, app_role) "
            "VALUES ('planner', 'Planner', %s, 'PLANNER')",
            (custom_hash,),
        )

    asyncio.run(_run_seed_once())

    with db.cursor() as cur:
        cur.execute("SELECT password_hash FROM users WHERE username = 'planner'")
        (stored_hash,) = cur.fetchone()

    assert stored_hash == custom_hash
    assert verify_password("a-custom-password", stored_hash)


@requires_db
def test_seed_does_not_recreate_a_deleted_demo_worker(db):
    asyncio.run(_run_seed_once())
    # contract_versions is append-only, so the API can't delete a seeded worker;
    # simulate a direct DB delete with the immutability trigger off for this transaction.
    with db.transaction(), db.cursor() as cur:
        cur.execute("ALTER TABLE contract_versions DISABLE TRIGGER trg_contract_versions_immutable")
        cur.execute("DELETE FROM contract_versions WHERE worker_id = (SELECT id FROM workers WHERE full_name = 'Worker 01')")
        cur.execute("ALTER TABLE contract_versions ENABLE TRIGGER trg_contract_versions_immutable")
        cur.execute("DELETE FROM workers WHERE full_name = 'Worker 01'")
    with db.cursor() as cur:
        cur.execute("UPDATE workers SET full_name = 'Edited Name' WHERE full_name = 'Worker 02'")
        cur.execute("UPDATE workers SET status = 'INACTIVE' WHERE full_name = 'Worker 03'")

    asyncio.run(_run_seed_once())

    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM workers")
        (worker_count,) = cur.fetchone()
        cur.execute("SELECT count(*) FROM workers WHERE full_name IN ('Worker 01', 'Worker 02')")
        (restored,) = cur.fetchone()
        cur.execute("SELECT count(*) FROM workers WHERE full_name = 'Edited Name'")
        (edited,) = cur.fetchone()
        cur.execute("SELECT status FROM workers WHERE full_name = 'Worker 03'")
        (status,) = cur.fetchone()

    assert worker_count == 29
    assert restored == 0
    assert edited == 1
    assert status == "INACTIVE"


@requires_db
def test_seed_adds_no_workers_to_a_populated_table(db):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO workers (national_id, full_name, role, status) "
            "VALUES ('123456782', 'Real Worker', 'GENERAL_GUARD', 'ACTIVE')"
        )

    asyncio.run(_run_seed_once())

    with db.cursor() as cur:
        cur.execute("SELECT full_name FROM workers")
        workers = cur.fetchall()
        cur.execute("SELECT count(*) FROM users")
        (user_count,) = cur.fetchone()

    assert workers == [("Real Worker",)]
    assert user_count == 2  # demo logins are still created


@requires_db
def test_seed_skips_demo_workers_when_disabled(db, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "seed_demo_workers", False)
    asyncio.run(_run_seed_once())

    with db.cursor() as cur:
        cur.execute("SELECT count(*), count(*) FILTER (WHERE national_id LIKE '9000%') FROM workers")
        counts = cur.fetchone()

    assert counts == (5, 0)


async def _run_seed_once():
    from app.db import async_session_factory
    from app.seed import seed

    async with async_session_factory() as session:
        await seed(session)
