"""§8 T3: `approval.revoke` marks the open approval revoked with cause/ref/actor
and returns the roster to DRAFT, keeping the approval row (audit trail)."""
from __future__ import annotations

import asyncio
from datetime import date

from tests.conftest import requires_db
from tests.rosters.helpers import insert_approval, insert_roster, insert_user


def _revoke(roster_id: int, cause: str, ref: str | None, by: int):
    import app.models  # noqa: F401
    from app.db import async_session_factory
    from app.rosters.approval import revoke
    from app.rosters.models import Roster

    async def run():
        async with async_session_factory() as session:
            roster = await session.get(Roster, roster_id)
            await revoke(session, roster, cause=cause, ref=ref, revoked_by=by)
            await session.commit()

    asyncio.run(run())


@requires_db
def test_revoke_marks_approval_and_returns_roster_to_draft(db):
    user_id = insert_user(db)
    roster = insert_roster(db, date(2099, 1, 1), user_id, status="APPROVED")
    insert_approval(db, roster, user_id)
    _revoke(roster, "CONTRACT_CHANGE", "import:7", user_id)
    with db.cursor() as cur:
        cur.execute("SELECT status FROM rosters WHERE id = %s", (roster,))
        assert cur.fetchone()[0] == "DRAFT"
        cur.execute("SELECT revoke_cause, revoke_ref, revoked_by, revoked_at FROM roster_approvals")
        cause, ref, by, at = cur.fetchone()
    assert (cause, ref, by) == ("CONTRACT_CHANGE", "import:7", user_id) and at is not None
    assert at.tzinfo is not None


@requires_db
def test_revoke_only_touches_the_open_approval_and_keeps_history(db):
    user_id = insert_user(db)
    roster = insert_roster(db, date(2099, 1, 1), user_id, status="APPROVED")
    first = insert_approval(db, roster, user_id, roster_version=1)
    _revoke(roster, "EDIT", None, user_id)
    second = insert_approval(db, roster, user_id, roster_version=2)
    _revoke(roster, "WORKER_CHANGE", "worker:3", user_id)
    with db.cursor() as cur:
        cur.execute("SELECT id, revoke_cause FROM roster_approvals ORDER BY id")
        assert cur.fetchall() == [(first, "EDIT"), (second, "WORKER_CHANGE")]


@requires_db
def test_revoke_without_an_approval_is_a_draft_noop(db):
    user_id = insert_user(db)
    roster = insert_roster(db, date(2099, 1, 1), user_id, status="APPROVED")
    _revoke(roster, "EDIT", None, user_id)
    with db.cursor() as cur:
        cur.execute("SELECT status FROM rosters WHERE id = %s", (roster,))
        assert cur.fetchone()[0] == "DRAFT"
        cur.execute("SELECT count(*) FROM roster_approvals")
        assert cur.fetchone()[0] == 0
