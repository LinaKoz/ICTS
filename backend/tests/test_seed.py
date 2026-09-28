"""§8 T2 "Verification": the seed is idempotent."""
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

    assert users == [("manager", "MANAGER"), ("planner", "PLANNER")]
    assert worker_count == 5  # one insert only, not duplicated by the 2nd run
    assert contract_count == 5


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


async def _run_seed_once():
    from app.db import async_session_factory
    from app.seed import seed

    async with async_session_factory() as session:
        await seed(session)
