"""§8 T8: approval endpoints (P11, P12) and the audit trail (bonus 1)."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from tests.conftest import requires_db
from tests.rosters.helpers import insert_assignment, insert_contract, insert_roster, insert_worker

JAN = date(2099, 1, 1)
FEB = date(2099, 2, 1)
GG, SCR, SUP = "GENERAL_GUARD", "SCREENER", "SUPERVISOR"
# Per shift: 2 GG, 2 SCR, 1 SUP (DEFAULT_DEMAND).
_CREW = [("A", GG), ("A", GG), ("A", SCR), ("A", SCR), ("A", SUP),
         ("B", GG), ("B", GG), ("B", SCR), ("B", SCR), ("B", SUP),
         ("C", GG), ("C", GG), ("C", SCR), ("C", SCR), ("C", SUP)]


def _q(db, sql, *params):
    with db.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def _code(resp) -> str:
    return resp.json()["error"]["code"]


def _full_roster(db, uid, month=FEB, status="DRAFT") -> int:
    """15 workers, each fixed to one shift every day: every slot covered, no
    violations, no hour shortfalls (min 0)."""
    roster = insert_roster(db, month, uid, status=status)
    for i, (shift, role) in enumerate(_CREW):
        w = insert_worker(db, f"{100000000 + i * 7:09d}", f"W{i}", role)
        insert_contract(db, w, uid, effective_month=date(2026, 1, 1), max_hours=400)
        for day in range(1, 29):
            insert_assignment(db, roster, w, date(month.year, month.month, day), shift, role)
    return roster


def _sparse_roster(db, uid, month=JAN, min_hours=8) -> tuple[int, int]:
    """One guard with a minimum and no assignments: many gaps + one shortfall, no violations."""
    roster = insert_roster(db, month, uid)
    w = insert_worker(db, "111111118", "Guard One", GG)
    insert_contract(db, w, uid, effective_month=date(2026, 1, 1), min_hours=min_hours)
    return roster, w


def _approve(client, month, version=1, **kw):
    return client.post(f"/api/rosters/{month}/approve", json={"expected_version": version, **kw})


def _open_approval_id(client, month) -> int | None:
    hist = client.get(f"/api/rosters/{month}").json()["approval_history"]
    return next((h["id"] for h in hist if h["revoked_at"] is None), None)


def _revoke(client, month, version=1, approval_id=None, **kw):
    """Revokes the approval currently shown (or the given one), like the dialog does."""
    if approval_id is None:
        approval_id = _open_approval_id(client, month) or 0
    return client.post(f"/api/rosters/{month}/revoke", json={"expected_version": version, "approval_id": approval_id, **kw})


def _ack_body(client, month, reason="Known staffing shortage"):
    p = client.get(f"/api/rosters/{month}/approval-preview").json()
    return {"acknowledge_warnings": True, "reason": reason, "warnings_fingerprint": p["warnings_fingerprint"]}


# --- permissions and the clean path ------------------------------------------


@requires_db
def test_planner_gets_403_manager_succeeds_and_approver_and_time_are_recorded(duo, db):
    _full_roster(db, duo.planner_id)
    assert _approve(duo.as_("planner"), "2099-02").status_code == 403
    assert _q(db, "SELECT status FROM rosters") == [("DRAFT",)]
    assert duo.client.post("/api/rosters/2099-02/revoke", json={"expected_version": 1, "approval_id": 1}).status_code == 403

    resp = _approve(duo.as_("manager"), "2099-02")  # no shortages: no acknowledgement needed
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "APPROVED" and body["version"] == 1
    ev = body["event"]
    assert ev["approved_by"] == "manager" and ev["roster_version"] == 1 and ev["acknowledged_warnings"] is None
    assert ev["reason"] is None and ev["revoked_at"] is None and ev["revoke_cause"] is None
    assert datetime.fromisoformat(ev["approved_at"]).tzinfo is not None
    (by, at, ver) = _q(db, "SELECT approved_by, approved_at, roster_version FROM roster_approvals")[0]
    assert by == duo.manager_id and at is not None and ver == 1
    got = duo.client.get("/api/rosters/2099-02").json()
    assert got["status"] == "APPROVED" and got["approval_history"] == [ev]


@requires_db
def test_unauthenticated_and_missing_roster(duo, db):
    duo.client.post("/api/auth/logout")
    assert _approve(duo.client, "2099-02").status_code == 401
    assert _approve(duo.as_("manager"), "2099-02").status_code == 404
    assert duo.client.get("/api/rosters/2099-02/approval-preview").status_code == 404
    assert _approve(duo.client, "2099-13").status_code == 422


# --- hard violations ------------------------------------------------------------


@requires_db
def test_hard_violation_blocks_even_with_acknowledgement_and_reason(duo, db):
    roster, w = _sparse_roster(db, duo.planner_id)
    off = insert_worker(db, "222222226", "Off Duty", GG)
    insert_contract(db, off, duo.planner_id, effective_month=date(2026, 1, 1), availability=["TUE:A"])
    insert_assignment(db, roster, off, date(2099, 1, 5), "A", GG)  # a Monday: UNAVAILABLE
    client = duo.as_("manager")
    body = _ack_body(client, "2099-01")
    resp = _approve(client, "2099-01", **body)
    assert resp.status_code == 422 and _code(resp) == "HARD_VIOLATIONS", resp.text
    assert "UNAVAILABLE" in {v["code"] for v in resp.json()["error"]["details"]}
    assert _q(db, "SELECT status FROM rosters") == [("DRAFT",)]
    assert _q(db, "SELECT count(*) FROM roster_approvals") == [(0,)]
    pv = client.get("/api/rosters/2099-01/approval-preview").json()
    assert pv["can_approve"] is False and [v["code"] for v in pv["hard_violations"]] == ["UNAVAILABLE"]


@requires_db
def test_no_contract_is_a_hard_violation_too(duo, db):
    roster, _ = _sparse_roster(db, duo.planner_id)
    nc = insert_worker(db, "222222226", "No Contract", GG)
    insert_assignment(db, roster, nc, date(2099, 1, 5), "A", GG)
    client = duo.as_("manager")
    resp = _approve(client, "2099-01", **_ack_body(client, "2099-01"))
    assert resp.status_code == 422 and _code(resp) == "HARD_VIOLATIONS"
    assert "NO_CONTRACT_FOR_MONTH" in {v["code"] for v in resp.json()["error"]["details"]}


@requires_db
def test_hard_violation_in_a_started_shift_blocks_approval(duo, db, freeze):
    freeze(datetime(2099, 1, 15, 10, 0))
    roster, _ = _sparse_roster(db, duo.planner_id)
    wrong = insert_worker(db, "222222226", "Wrong Slot", GG)
    insert_contract(db, wrong, duo.planner_id, effective_month=date(2026, 1, 1))
    insert_assignment(db, roster, wrong, date(2099, 1, 5), "A", "SCREENER")  # started long ago, cannot be edited
    client = duo.as_("manager")
    got = client.get("/api/rosters/2099-01").json()
    assert got["free_from"][0] == "2099-01-15" and [v["code"] for v in got["violations"]] == ["WRONG_ROLE"]
    resp = _approve(client, "2099-01", **_ack_body(client, "2099-01"))
    assert resp.status_code == 422 and _code(resp) == "HARD_VIOLATIONS", resp.text
    assert [v["code"] for v in resp.json()["error"]["details"]] == ["WRONG_ROLE"]


@requires_db
def test_unavailable_in_a_started_shift_is_not_a_violation(duo, db, freeze):
    """Availability counts from the first free shift: a started shift the
    worker is no longer available for neither shows nor blocks approval."""
    freeze(datetime(2099, 1, 15, 10, 0))
    roster, _ = _sparse_roster(db, duo.planner_id)
    off = insert_worker(db, "333333334", "Off Duty", GG)
    insert_contract(db, off, duo.planner_id, effective_month=date(2026, 1, 1), availability=["TUE:A"])
    insert_assignment(db, roster, off, date(2099, 1, 5), "A", GG)
    client = duo.as_("manager")
    assert client.get("/api/rosters/2099-01").json()["violations"] == []
    pv = client.get("/api/rosters/2099-01/approval-preview").json()
    assert pv["hard_violations"] == [] and pv["can_approve"] is True


# --- soft shortages -----------------------------------------------------------------


@requires_db
def test_soft_shortages_need_acknowledgement_reason_and_fingerprint(duo, db):
    _sparse_roster(db, duo.planner_id)
    client = duo.as_("manager")
    fp = _ack_body(client, "2099-01")["warnings_fingerprint"]
    for kw in (
        {},  # nothing
        {"acknowledge_warnings": True},  # no reason
        {"acknowledge_warnings": True, "reason": "   ", "warnings_fingerprint": fp},  # blank reason
        {"acknowledge_warnings": False, "reason": "why", "warnings_fingerprint": fp},  # not acknowledged
        {"acknowledge_warnings": True, "reason": "why"},  # no fingerprint
    ):
        resp = _approve(client, "2099-01", **kw)
        assert resp.status_code == 422 and _code(resp) == "WARNINGS_NOT_ACKNOWLEDGED", (kw, resp.text)
        assert resp.json()["error"]["details"]["warnings_fingerprint"] == fp
    assert _q(db, "SELECT status FROM rosters") == [("DRAFT",)]
    assert _q(db, "SELECT count(*) FROM roster_approvals") == [(0,)]


@requires_db
def test_acknowledged_approval_stores_the_snapshot_and_reason(duo, db):
    _, w = _sparse_roster(db, duo.planner_id)
    client = duo.as_("manager")
    pv = client.get("/api/rosters/2099-01/approval-preview").json()
    assert pv["requires_acknowledgement"] and pv["can_approve"] and pv["hard_violations"] == []
    assert len(pv["coverage_gaps"]) == 31 * 3 * 3 and all(g["missing"] > 0 for g in pv["coverage_gaps"])
    assert [s["worker_id"] for s in pv["hour_shortfalls"]] == [str(w)]

    resp = _approve(client, "2099-01", acknowledge_warnings=True, reason="  Summer leave  ", warnings_fingerprint=pv["warnings_fingerprint"])
    assert resp.status_code == 200, resp.text
    ev = resp.json()["event"]
    assert ev["reason"] == "Summer leave"
    snap = ev["acknowledged_warnings"]
    assert snap["warnings_fingerprint"] == pv["warnings_fingerprint"]
    assert snap["coverage_gaps"] == pv["coverage_gaps"] and snap["hour_shortfalls"] == pv["hour_shortfalls"]
    stored = _q(db, "SELECT acknowledged_warnings, reason FROM roster_approvals")[0]
    assert stored[0]["warnings_fingerprint"] == pv["warnings_fingerprint"] and stored[1] == "Summer leave"
    assert client.get("/api/rosters/2099-01").json()["approval_history"][0]["acknowledged_warnings"] == snap


@requires_db
def test_stale_fingerprint_is_409_and_nothing_is_approved(duo, db):
    roster, w = _sparse_roster(db, duo.planner_id)
    client = duo.as_("manager")
    body = _ack_body(client, "2099-01")
    insert_assignment(db, roster, w, date(2099, 1, 5), "A", GG)  # the shortage set changes after the review
    resp = _approve(client, "2099-01", **body)
    assert resp.status_code == 409 and _code(resp) == "STALE_PREVIEW", resp.text
    assert resp.json()["error"]["details"]["warnings_fingerprint"] != body["warnings_fingerprint"]
    resp = _approve(client, "2099-01", acknowledge_warnings=True, reason="r", warnings_fingerprint="deadbeef")
    assert resp.status_code == 409 and _code(resp) == "STALE_PREVIEW"
    assert _q(db, "SELECT status FROM rosters") == [("DRAFT",)]
    assert _q(db, "SELECT count(*) FROM roster_approvals") == [(0,)]
    # ... and the current fingerprint works
    assert _approve(client, "2099-01", **_ack_body(client, "2099-01")).status_code == 200


@requires_db
def test_fingerprint_is_deterministic_and_tracks_the_shortage_set(duo, db):
    roster, w = _sparse_roster(db, duo.planner_id)
    client = duo.as_("planner")  # planners may read the preview
    a = client.get("/api/rosters/2099-01/approval-preview").json()["warnings_fingerprint"]
    b = client.get("/api/rosters/2099-01/approval-preview").json()["warnings_fingerprint"]
    assert a == b and len(a) == 64
    insert_assignment(db, roster, w, date(2099, 1, 5), "A", GG)
    c = client.get("/api/rosters/2099-01/approval-preview").json()["warnings_fingerprint"]
    assert c != a


def test_fingerprint_ignores_input_order():
    from app.api_schemas.common import CoverageGapOut, HourShortfallOut
    from app.rosters.approval import warnings_fingerprint

    g1 = CoverageGapOut(date=date(2099, 1, 1), shift="A", role=GG, required=2, assigned=0, missing=2, proven_missing=0, locked=False)
    g2 = CoverageGapOut(date=date(2099, 1, 2), shift="B", role=SUP, required=1, assigned=0, missing=1, proven_missing=0, locked=False)
    s1 = HourShortfallOut(worker_id="1", min_hours=8, assigned_hours=0, missing_hours=8)
    s2 = HourShortfallOut(worker_id="2", min_hours=16, assigned_hours=8, missing_hours=8)
    assert warnings_fingerprint([g1, g2], [s1, s2]) == warnings_fingerprint([g2, g1], [s2, s1])
    assert warnings_fingerprint([g1], []) != warnings_fingerprint([g2], [])
    assert warnings_fingerprint([], []) == warnings_fingerprint([], [])


# --- version, state, history month ---------------------------------------------------


@requires_db
def test_version_conflict_is_409(duo, db):
    _full_roster(db, duo.planner_id)
    client = duo.as_("manager")
    resp = _approve(client, "2099-02", version=7)
    assert resp.status_code == 409 and _code(resp) == "VERSION_CONFLICT"
    assert resp.json()["error"]["details"] == {"current_version": 1}
    assert _q(db, "SELECT status FROM rosters") == [("DRAFT",)]
    assert _revoke(client, "2099-02", version=7).status_code == 409


@requires_db
def test_approving_twice_and_revoking_a_draft_are_409(duo, db):
    _full_roster(db, duo.planner_id)
    client = duo.as_("manager")
    assert _revoke(client, "2099-02").json()["error"]["code"] == "NOT_APPROVED"
    assert _approve(client, "2099-02").status_code == 200
    resp = _approve(client, "2099-02")
    assert resp.status_code == 409 and _code(resp) == "ALREADY_APPROVED"
    assert _q(db, "SELECT count(*) FROM roster_approvals") == [(1,)]


@requires_db
def test_history_month_cannot_be_approved(duo, db):
    insert_roster(db, date(2001, 1, 1), duo.planner_id)
    resp = _approve(duo.as_("manager"), "2001-01")
    assert resp.status_code == 422 and _code(resp) == "LOCKED_SHIFT"
    assert duo.client.get("/api/rosters/2001-01/approval-preview").json()["can_approve"] is False


# --- audit trail: order, actors, and automatic invalidation by edit / regenerate ---------


@requires_db
def test_manual_revoke_and_history_order(duo, db):
    _full_roster(db, duo.planner_id)
    client = duo.as_("manager")
    assert _approve(client, "2099-02").status_code == 200
    rv = _revoke(client, "2099-02")
    assert rv.status_code == 200 and rv.json()["status"] == "DRAFT"
    assert rv.json()["event"]["revoke_cause"] == "MANUAL" and rv.json()["event"]["revoked_by"] == "manager"
    assert _approve(client, "2099-02").status_code == 200
    hist = client.get("/api/rosters/2099-02").json()["approval_history"]
    assert [h["revoke_cause"] for h in hist] == [None, "MANUAL"]  # every approval kept, newest first
    assert hist[0]["id"] > hist[1]["id"] and hist[0]["approved_at"] >= hist[1]["approved_at"]
    assert hist[0]["revoked_at"] is None and hist[1]["revoked_at"] is not None


@requires_db
def test_stale_revoke_dialog_never_revokes_a_newer_approval(duo, db):
    """A opens the dialog on #1; B revokes #1 and approves again (#2). Approving
    and revoking keep the roster version, so only the approval id catches A's stale submit."""
    _full_roster(db, duo.planner_id)
    client = duo.as_("manager")
    assert _approve(client, "2099-02").status_code == 200
    first = _open_approval_id(client, "2099-02")  # what A's dialog shows
    assert _revoke(client, "2099-02", reason="B withdraws").status_code == 200
    assert _approve(client, "2099-02").status_code == 200
    second = _open_approval_id(client, "2099-02")
    assert second != first
    before = _q(db, "SELECT * FROM roster_approvals WHERE id = %s", second)

    resp = _revoke(client, "2099-02", approval_id=first, reason="A's reason for #1")
    assert resp.status_code == 409 and _code(resp) == "STALE_APPROVAL"
    assert resp.json()["error"]["details"] == {"current_approval_id": second}
    assert _q(db, "SELECT * FROM roster_approvals WHERE id = %s", second) == before  # #2 untouched
    assert _q(db, "SELECT revoked_at IS NULL FROM roster_approvals WHERE id = %s", second) == [(True,)]
    assert _q(db, "SELECT status FROM rosters") == [("APPROVED",)]
    assert _q(db, "SELECT count(*) FROM roster_approvals WHERE revoke_reason = %s", "A's reason for #1") == [(0,)]


@requires_db
def test_manual_revoke_stores_the_reason_and_history_returns_it(duo, db):
    _full_roster(db, duo.planner_id)
    client = duo.as_("manager")
    assert _approve(client, "2099-02").status_code == 200
    rv = _revoke(client, "2099-02", reason="  worker called in sick  ")
    assert rv.status_code == 200 and rv.json()["event"]["revoke_reason"] == "worker called in sick"
    hist = client.get("/api/rosters/2099-02").json()["approval_history"]
    assert hist[0]["revoke_reason"] == "worker called in sick"
    # A blank reason is stored as none; an automatic revocation never has one.
    assert _approve(client, "2099-02").status_code == 200
    rv = _revoke(client, "2099-02", reason="   ")
    assert rv.status_code == 200 and rv.json()["event"]["revoke_reason"] is None


@requires_db
def test_edit_revokes_with_cause_edit_and_history_records_everything(duo, db):
    _full_roster(db, duo.planner_id)
    manager = duo.as_("manager")
    assert _approve(manager, "2099-02").status_code == 200

    planner = duo.as_("planner")
    ids = planner.get("/api/rosters/2099-02/assignments").json()
    target = next(a for a in ids if a["date"] == "2099-02-10" and a["shift"] == "A" and a["role"] == GG)
    # Unacknowledged edit of an approved roster is refused and changes nothing.
    r = planner.request("DELETE", f"/api/rosters/2099-02/assignments/{target['id']}", json={"expected_version": 1})
    assert r.status_code == 409 and _code(r) == "APPROVED_EDIT_NOT_ACKNOWLEDGED"
    assert _q(db, "SELECT status FROM rosters") == [("APPROVED",)]
    r = planner.request(
        "DELETE", f"/api/rosters/2099-02/assignments/{target['id']}",
        json={"expected_version": 1, "acknowledge_approved_edit": True},
    )
    assert r.status_code == 200 and r.json()["approval_revoked"] is True and r.json()["version"] == 2

    got = planner.get("/api/rosters/2099-02").json()
    assert got["status"] == "DRAFT"
    (ev,) = got["approval_history"]
    assert (ev["revoke_cause"], ev["revoke_ref"], ev["revoked_by"], ev["approved_by"]) == ("EDIT", None, "planner", "manager")
    assert ev["roster_version"] == 1 and ev["revoked_at"] is not None

    # Re-approval (now one gap): a second history entry, at the new version, with a snapshot.
    manager = duo.as_("manager")
    body = _ack_body(manager, "2099-02", reason="one guard short")
    r = _approve(manager, "2099-02", version=2, **body)
    assert r.status_code == 200, r.text
    second, first = manager.get("/api/rosters/2099-02").json()["approval_history"]
    assert (first["id"], second["id"]) == (ev["id"], r.json()["event"]["id"])
    assert second["roster_version"] == 2 and second["revoke_cause"] is None
    assert second["acknowledged_warnings"]["coverage_gaps"][0]["date"] == "2099-02-10"


@requires_db
def test_regenerate_save_with_replace_revokes_with_cause_regenerate(duo, db, fingerprint_for):
    roster, w = _sparse_roster(db, duo.planner_id, min_hours=0)
    manager = duo.as_("manager")
    assert _approve(manager, "2099-01", **_ack_body(manager, "2099-01")).status_code == 200
    planner = duo.as_("planner")
    save = planner.post(
        "/api/rosters/2099-01/save",
        json={
            "assignments": [{"worker_id": str(w), "date": "2099-01-05", "shift": "A", "role": GG}],
            "fingerprint": fingerprint_for(JAN), "replace_existing": True, "expected_version": 1,
        },
    )
    assert save.status_code == 200 and save.json()["status"] == "DRAFT", save.text
    (ev,) = planner.get("/api/rosters/2099-01").json()["approval_history"]
    assert (ev["revoke_cause"], ev["revoke_ref"], ev["revoked_by"]) == ("REGENERATE", None, "planner")
    assert ev["roster_version"] == 1 and ev["reason"] == "Known staffing shortage"
