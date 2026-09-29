"""Shared seeded scenario for the change-set tests. Frozen now is
2026-09-15 10:00 Israel, so in September the shifts up to 15/09 B have
started and `free_from` is (15/09, C)."""
from __future__ import annotations

from datetime import date, datetime

from tests.rosters.helpers import insert_approval, insert_assignment, insert_contract, insert_roster, insert_worker
from tests.workers.conftest import tokens

NOW = datetime(2026, 9, 15, 10, 0)
LOCKED = (date(2026, 9, 10), "A")  # started
FREE = (date(2026, 9, 20), "A")  # upcoming
OCT = (date(2026, 10, 5), "B")  # upcoming, next month
AUG = (date(2026, 8, 3), "A")  # history month


def seed(db, uid: int, sep_status: str = "APPROVED") -> dict:
    """Worker W (GG, full availability since 2026-01) assigned in Aug (history),
    Sep (one started, one upcoming shift; APPROVED by default) and Oct (DRAFT)."""
    w = insert_worker(db, "111111118", "Alice Guard", "GENERAL_GUARD")
    insert_contract(db, w, uid, version_no=1, effective_month=date(2026, 1, 1))
    other = insert_worker(db, "222222226", "Ben Screener", "SCREENER")
    insert_contract(db, other, uid, version_no=1, effective_month=date(2026, 1, 1))
    ids = {"w": w, "other": other}
    for key, month, status, assignments in (
        ("aug", date(2026, 8, 1), "DRAFT", [AUG]),
        ("sep", date(2026, 9, 1), sep_status, [LOCKED, FREE]),
        ("oct", date(2026, 10, 1), "DRAFT", [OCT]),
    ):
        roster = insert_roster(db, month, uid, status=status)
        ids[key] = roster
        for d, s in assignments:
            insert_assignment(db, roster, w, d, s, "GENERAL_GUARD")
        if status == "APPROVED":
            insert_approval(db, roster, uid)
    insert_assignment(db, ids["sep"], other, LOCKED[0], LOCKED[1], "SCREENER")
    return ids


def approvals(db, roster_id: int) -> list[tuple]:
    with db.cursor() as cur:
        cur.execute(
            "SELECT revoke_cause, revoke_ref, revoked_by, revoked_at IS NOT NULL FROM roster_approvals "
            "WHERE roster_id = %s ORDER BY id",
            (roster_id,),
        )
        return cur.fetchall()


def roster_row(db, roster_id: int) -> tuple:
    with db.cursor() as cur:
        cur.execute("SELECT status, row_version FROM rosters WHERE id = %s", (roster_id,))
        return cur.fetchone()


def assignment_count(db, roster_id: int) -> int:
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM roster_assignments WHERE roster_id = %s", (roster_id,))
        return cur.fetchone()[0]


def version_count(db, worker_id: int) -> int:
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM contract_versions WHERE worker_id = %s", (worker_id,))
        return cur.fetchone()[0]


def slot(pair) -> list[str]:
    return tokens(pair)
