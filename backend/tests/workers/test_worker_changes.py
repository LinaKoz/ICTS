"""§8 T5 status/role change acceptance (P7, D9(b)): WORKER_CHANGE revoke,
`worker_field_history`, and `resolve_worker_state` for locked shifts."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest

from tests.conftest import requires_db
from tests.rosters.helpers import insert_worker_field_history
from tests.workers.scenario import (
    FREE,
    LOCKED,
    NOW,
    approvals,
    assignment_count,
    roster_row,
    seed,
)
from tests.workers.conftest import TZ


@pytest.fixture()
def world(planner, db, freeze):
    freeze(NOW)
    client, uid = planner
    return client, uid, db, seed(db, uid)


def _patch(client, w, version=1, **fields):
    r = client.patch(f"/api/workers/{w}", json={"expected_version": version, **fields})
    assert r.status_code == 200, r.text
    return r.json()


def _history(db, w):
    with db.cursor() as cur:
        cur.execute(
            "SELECT field, old_value, new_value, effective_at, changed_by FROM worker_field_history "
            "WHERE worker_id = %s ORDER BY id",
            (w,),
        )
        return cur.fetchall()


def _codes(roster: dict) -> list[tuple[str, str]]:
    return sorted((v["code"], v["key"][1]) for v in roster["violations"])


@requires_db
def test_deactivation_affects_upcoming_shift_only_and_revokes_approval(world):
    client, uid, db, ids = world
    w = ids["w"]
    out = _patch(client, w, status="INACTIVE")
    assert out["changed"] is True and out["worker"]["status"] == "INACTIVE" and out["worker"]["row_version"] == 2

    # Impact: only the upcoming shift is a new violation; the already-worked one is not, and nothing is "locked".
    sep = next(r for r in out["affected_rosters"] if r["month"] == "2026-09")
    assert [(v["code"], v["key"][1]) for v in sep["new_violations"]] == [("INACTIVE_WORKER", "2026-09-20")]
    assert out["locked_violations"] == []
    assert out["invalidates_approved"] is True and sep["revokes_approval"] is True
    assert {r["month"] for r in out["affected_rosters"]} == {"2026-09", "2026-10"}  # not the Aug history roster

    # One history row, in the same change.
    (field, old, new, at, by), = _history(db, w)
    assert (field, old, new, by) == ("STATUS", "ACTIVE", "INACTIVE", uid)
    assert at == NOW.replace(tzinfo=TZ)

    # WORKER_CHANGE revoke; the approval row is kept; assignments untouched.
    assert roster_row(db, ids["sep"])[0] == "DRAFT" and assignment_count(db, ids["sep"]) == 3
    assert approvals(db, ids["sep"]) == [("WORKER_CHANGE", f"worker:{w}", uid, True)]

    roster = client.get("/api/rosters/2026-09").json()
    assert _codes(roster) == [("INACTIVE_WORKER", "2026-09-20")]  # the started 10/09 shift is not a violation
    assert roster["approval_history"][0]["revoke_cause"] == "WORKER_CHANGE"
    detail = client.get(f"/api/workers/{w}").json()
    assert [(h["field"], h["old_value"], h["new_value"], h["changed_by"]) for h in detail["field_history"]] == [
        ("STATUS", "ACTIVE", "INACTIVE", "planner")
    ]


@requires_db
def test_role_change_same_rules_wrong_role_upcoming_only(world):
    client, uid, db, ids = world
    w = ids["w"]
    out = _patch(client, w, role="SCREENER")
    sep = next(r for r in out["affected_rosters"] if r["month"] == "2026-09")
    assert [(v["code"], v["key"][1]) for v in sep["new_violations"]] == [("WRONG_ROLE", "2026-09-20")]
    assert out["locked_violations"] == []
    assert approvals(db, ids["sep"])[0][:2] == ("WORKER_CHANGE", f"worker:{w}")
    assert _history(db, w)[0][:3] == ("ROLE", "GENERAL_GUARD", "SCREENER")
    assert _codes(client.get("/api/rosters/2026-09").json()) == [("WRONG_ROLE", "2026-09-20")]
    # Assignments keep their snapshotted slot role (P7): nothing moved silently.
    with db.cursor() as cur:
        cur.execute("SELECT DISTINCT role FROM roster_assignments WHERE worker_id = %s", (w,))
        assert cur.fetchall() == [("GENERAL_GUARD",)]


@requires_db
def test_resolve_worker_state_before_and_after_the_change(world):
    from app.db import async_session_factory
    from app.workers.history import resolve_worker_state
    from app.timeutil import shift_start_time

    client, uid, db, ids = world
    w = ids["w"]
    _patch(client, w, status="INACTIVE")
    _patch(client, w, version=2, role="SUPERVISOR")

    async def states():
        async with async_session_factory() as session:
            return (
                await resolve_worker_state(session, w, shift_start_time(*LOCKED)),  # before both changes
                await resolve_worker_state(session, w, shift_start_time(*FREE)),  # after both
            )

    started, upcoming = asyncio.run(states())
    assert started == {"status": "ACTIVE", "role": "GENERAL_GUARD"}
    assert upcoming == {"status": "INACTIVE", "role": "SUPERVISOR"}


@requires_db
def test_worker_already_inactive_before_the_shift_still_violates(world):
    client, uid, db, ids = world
    w = ids["w"]
    # Deactivated on 1 Sep, before the 10 Sep shift started: history says INACTIVE at that time.
    with db.cursor() as cur:
        cur.execute("UPDATE workers SET status = 'INACTIVE' WHERE id = %s", (w,))
    insert_worker_field_history(db, w, "STATUS", "ACTIVE", "INACTIVE", (NOW - timedelta(days=14)).replace(tzinfo=TZ), uid)
    assert ("INACTIVE_WORKER", "2026-09-10") in _codes(client.get("/api/rosters/2026-09").json())

    # Never had history at all (created inactive): same.
    other = ids["other"]
    with db.cursor() as cur:
        cur.execute("UPDATE workers SET status = 'INACTIVE' WHERE id = %s", (other,))
    codes = _codes(client.get("/api/rosters/2026-09").json())
    assert codes.count(("INACTIVE_WORKER", "2026-09-10")) == 2


@requires_db
def test_worker_reactivated_after_the_shift_still_shows_the_old_violation(world):
    client, uid, db, ids = world
    w = ids["w"]
    # Inactive when the 10 Sep shift started, reactivated on 12 Sep: the worked shift was invalid at the time.
    insert_worker_field_history(db, w, "STATUS", "ACTIVE", "INACTIVE", datetime(2026, 9, 1, 12).replace(tzinfo=TZ), uid)
    insert_worker_field_history(db, w, "STATUS", "INACTIVE", "ACTIVE", datetime(2026, 9, 12, 12).replace(tzinfo=TZ), uid)
    assert _codes(client.get("/api/rosters/2026-09").json()) == [("INACTIVE_WORKER", "2026-09-10")]


@requires_db
def test_change_with_no_roster_impact_keeps_approval(world):
    client, uid, db, ids = world
    out = _patch(client, ids["other"], role="SUPERVISOR")  # the screener's started shift is not a violation; no upcoming shifts
    assert out["invalidates_approved"] is False
    assert roster_row(db, ids["sep"])[0] == "APPROVED"
    assert approvals(db, ids["sep"]) == [(None, None, None, False)]

    # Name-only edits touch no roster and write no history.
    out = _patch(client, ids["w"], full_name="Alice Renamed")
    assert out["affected_rosters"] == [] and _history(db, ids["w"]) == []


@requires_db
def test_reactivation_does_not_revoke(world):
    client, uid, db, ids = world
    with db.cursor() as cur:
        cur.execute("UPDATE workers SET status = 'INACTIVE' WHERE id = %s", (ids["w"],))
    insert_worker_field_history(db, ids["w"], "STATUS", "ACTIVE", "INACTIVE", datetime(2026, 8, 1).replace(tzinfo=TZ), uid)
    with db.cursor() as cur:
        cur.execute("UPDATE rosters SET status = 'DRAFT' WHERE id = %s", (ids["sep"],))
    out = _patch(client, ids["w"], status="ACTIVE")
    sep = next(r for r in out["affected_rosters"] if r["month"] == "2026-09")
    assert sep["new_violations"] == [] and out["invalidates_approved"] is False


@requires_db
def test_stale_expected_version_applies_nothing(world):
    client, uid, db, ids = world
    _patch(client, ids["w"], full_name="First")
    r = client.patch(f"/api/workers/{ids['w']}", json={"expected_version": 1, "status": "INACTIVE"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "VERSION_CONFLICT"
    assert _history(db, ids["w"]) == [] and roster_row(db, ids["sep"])[0] == "APPROVED"
