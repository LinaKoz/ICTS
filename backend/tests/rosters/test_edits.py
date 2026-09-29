"""§8 T7: manual edits (add/remove/move), the P10 repair rule, adjacency
(in month, across days, across a month boundary), LOCKED_SHIFT, approved
edits, and the neighbor-month `row_version` / fingerprint requirement."""
from __future__ import annotations

from datetime import date, datetime

from tests.conftest import requires_db
from tests.rosters.helpers import insert_approval, insert_assignment, insert_contract, insert_roster, insert_worker

JAN = date(2099, 1, 1)
FEB = date(2099, 2, 1)
D5 = date(2099, 1, 5)  # a Monday
GG = "GENERAL_GUARD"


def _q(db, sql: str, *params):
    with db.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def _worker(db, user_id, nid, role=GG, status="ACTIVE", **contract) -> int:
    wid = insert_worker(db, nid, full_name=f"W{nid}", role=role, status=status)
    insert_contract(db, wid, user_id, effective_month=date(2026, 1, 1), **contract)
    return wid


def _add(client, month, wid, d, shift, version, role=GG, **kw):
    body = {"worker_id": str(wid), "date": d.isoformat(), "shift": shift, "role": role, "expected_version": version, **kw}
    return client.post(f"/api/rosters/{month}/assignments", json=body)


def _code(resp) -> str:
    return resp.json()["error"]["code"]


def _version(db, month: date) -> int:
    return _q(db, "SELECT row_version FROM rosters WHERE month = %s", month)[0][0]


# --- add ---------------------------------------------------------------------


@requires_db
def test_add_valid_increments_version_and_returns_assignment(planner, db):
    client, uid = planner
    w = _worker(db, uid, "111111118")
    insert_roster(db, JAN, uid)
    resp = _add(client, "2099-01", w, D5, "A", 1)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["version"] == 2 and body["status"] == "DRAFT" and body["approval_revoked"] is False
    assert body["assignment"]["worker_id"] == str(w) and body["assignment"]["id"] > 0
    assert _version(db, JAN) == 2
    ids = client.get("/api/rosters/2099-01/assignments").json()
    assert [a["id"] for a in ids] == [body["assignment"]["id"]]


@requires_db
def test_add_rejects_new_violations(planner, db):
    client, uid = planner
    unavailable = _worker(db, uid, "111111118", availability=["TUE:A"])
    screener = _worker(db, uid, "222222226", role="SCREENER")
    inactive = _worker(db, uid, "333333334", status="INACTIVE")
    ok = _worker(db, uid, "444444442")
    insert_roster(db, JAN, uid)
    cases = [
        (unavailable, GG, "UNAVAILABLE"),
        (screener, GG, "WRONG_ROLE"),
        (inactive, GG, "INACTIVE_WORKER"),
    ]
    for wid, role, code in cases:
        resp = _add(client, "2099-01", wid, D5, "A", 1, role=role)
        assert resp.status_code == 422 and _code(resp) == "HARD_VIOLATIONS", resp.text
        assert code in {v["code"] for v in resp.json()["error"]["details"]}
    # duplicate assignment and out-of-month
    assert _add(client, "2099-01", ok, D5, "A", 1).status_code == 200
    resp = _add(client, "2099-01", ok, D5, "A", 2)
    assert resp.status_code == 422 and "DUPLICATE_ASSIGNMENT" in {v["code"] for v in resp.json()["error"]["details"]}
    resp = _add(client, "2099-01", ok, date(2099, 2, 3), "A", 2)
    assert resp.status_code == 422 and "OUT_OF_MONTH" in {v["code"] for v in resp.json()["error"]["details"]}
    assert _version(db, JAN) == 2  # only the one success bumped it
    assert _q(db, "SELECT count(*) FROM roster_assignments") == [(1,)]


@requires_db
def test_add_unknown_worker_and_missing_roster(planner, db):
    client, uid = planner
    insert_roster(db, JAN, uid)
    assert _add(client, "2099-01", 9999, D5, "A", 1).status_code == 422
    assert _add(client, "2099-03", 1, D5, "A", 1).status_code == 404


@requires_db
def test_worsened_magnitude_is_rejected_but_unrelated_add_passes(planner, db):
    client, uid = planner
    over = _worker(db, uid, "111111118", max_hours=8)  # two shifts = 16 h, already 8 h over
    other = _worker(db, uid, "222222226")
    roster = insert_roster(db, JAN, uid)
    insert_assignment(db, roster, over, D5, "A", GG)
    insert_assignment(db, roster, over, date(2099, 1, 6), "A", GG)
    resp = _add(client, "2099-01", over, date(2099, 1, 7), "A", 1)  # same MAX_HOURS key, magnitude 8 -> 16
    assert resp.status_code == 422
    assert [v["code"] for v in resp.json()["error"]["details"]] == ["MAX_HOURS"]
    assert _add(client, "2099-01", other, D5, "A", 1).status_code == 200  # existing violation does not block


@requires_db
def test_remove_from_free_shift_allowed_on_invalid_roster(planner, db):
    client, uid = planner
    over = _worker(db, uid, "111111118", max_hours=8)
    roster = insert_roster(db, JAN, uid)
    a1 = insert_assignment(db, roster, over, D5, "A", GG)
    insert_assignment(db, roster, over, date(2099, 1, 6), "A", GG)
    resp = client.request("DELETE", f"/api/rosters/2099-01/assignments/{a1}", json={"expected_version": 1})
    assert resp.status_code == 200 and resp.json()["version"] == 2 and resp.json()["assignment"] is None
    assert _q(db, "SELECT count(*) FROM roster_assignments") == [(1,)]
    assert client.request("DELETE", f"/api/rosters/2099-01/assignments/{a1}", json={"expected_version": 2}).status_code == 404


@requires_db
def test_version_conflict_is_409(planner, db):
    client, uid = planner
    w = _worker(db, uid, "111111118")
    insert_roster(db, JAN, uid, row_version=3)
    resp = _add(client, "2099-01", w, D5, "A", 2)
    assert resp.status_code == 409 and _code(resp) == "VERSION_CONFLICT"
    assert _q(db, "SELECT count(*) FROM roster_assignments") == [(0,)]


# --- move --------------------------------------------------------------------


@requires_db
def test_move_valid_keeps_id_and_bumps_version(planner, db):
    client, uid = planner
    w1 = _worker(db, uid, "111111118")
    w2 = _worker(db, uid, "222222226")
    roster = insert_roster(db, JAN, uid)
    a = insert_assignment(db, roster, w1, D5, "A", GG)
    resp = client.post(f"/api/rosters/2099-01/assignments/{a}/move", json={"worker_id": str(w2), "shift": "C", "expected_version": 1})
    assert resp.status_code == 200, resp.text
    assert resp.json()["assignment"]["id"] == a and resp.json()["version"] == 2
    assert _q(db, "SELECT worker_id, shift FROM roster_assignments") == [(w2, "C")]


@requires_db
def test_failed_move_leaves_original_intact(planner, db):
    client, uid = planner
    w1 = _worker(db, uid, "111111118")
    w2 = _worker(db, uid, "222222226", availability=["TUE:A"])
    roster = insert_roster(db, JAN, uid)
    a = insert_assignment(db, roster, w1, D5, "A", GG)
    resp = client.post(f"/api/rosters/2099-01/assignments/{a}/move", json={"worker_id": str(w2), "expected_version": 1})
    assert resp.status_code == 422 and _code(resp) == "HARD_VIOLATIONS"
    assert _q(db, "SELECT worker_id, date, shift FROM roster_assignments") == [(w1, D5, "A")]
    assert _version(db, JAN) == 1
    same = client.post(f"/api/rosters/2099-01/assignments/{a}/move", json={"expected_version": 1})
    assert same.status_code == 400


# --- adjacency ---------------------------------------------------------------


@requires_db
def test_adjacency_rule_on_rejects_within_day_and_across_days(planner, db):
    client, uid = planner
    w = _worker(db, uid, "111111118")
    roster = insert_roster(db, JAN, uid, forbid_adjacent_shifts=True)
    insert_assignment(db, roster, w, D5, "B", GG)
    resp = _add(client, "2099-01", w, D5, "A", 1)
    assert resp.status_code == 422 and "ADJACENT_SHIFTS" in {v["code"] for v in resp.json()["error"]["details"]}
    assert _add(client, "2099-01", w, D5, "C", 1).status_code == 422
    insert_assignment(db, roster, w, date(2099, 1, 10), "C", GG)
    assert _add(client, "2099-01", w, date(2099, 1, 11), "A", 1).status_code == 422  # C then next-day A
    assert _add(client, "2099-01", w, date(2099, 1, 12), "A", 1).status_code == 200


@requires_db
def test_adjacency_rule_off_accepts_a_plus_b(planner, db):
    client, uid = planner
    w = _worker(db, uid, "111111118")
    roster = insert_roster(db, JAN, uid)
    insert_assignment(db, roster, w, D5, "A", GG)
    assert _add(client, "2099-01", w, D5, "B", 1).status_code == 200


@requires_db
def test_adjacency_across_month_boundary(planner, db):
    client, uid = planner
    w = _worker(db, uid, "111111118")
    jan = insert_roster(db, JAN, uid, forbid_adjacent_shifts=True)
    insert_roster(db, FEB, uid, forbid_adjacent_shifts=False)
    insert_assignment(db, jan, w, date(2099, 1, 31), "C", GG)
    # Feb roster has the rule off, but Jan's is on: the boundary pair is rejected
    resp = _add(client, "2099-02", w, FEB, "A", 1)
    assert resp.status_code == 422 and "ADJACENT_SHIFTS" in {v["code"] for v in resp.json()["error"]["details"]}
    assert _add(client, "2099-02", w, date(2099, 2, 2), "A", 1).status_code == 200


@requires_db
def test_adjacency_boundary_rule_on_in_edited_month_and_reverse_direction(planner, db):
    client, uid = planner
    w = _worker(db, uid, "111111118")
    jan = insert_roster(db, JAN, uid, forbid_adjacent_shifts=False)
    feb = insert_roster(db, FEB, uid, forbid_adjacent_shifts=True)
    insert_assignment(db, feb, w, FEB, "A", GG)
    resp = _add(client, "2099-01", w, date(2099, 1, 31), "C", 1)  # neighbor (Feb) has the rule on
    assert resp.status_code == 422 and "ADJACENT_SHIFTS" in {v["code"] for v in resp.json()["error"]["details"]}
    del jan


@requires_db
def test_boundary_pair_accepted_when_neither_month_has_the_rule(planner, db):
    client, uid = planner
    w = _worker(db, uid, "111111118")
    jan = insert_roster(db, JAN, uid)
    insert_roster(db, FEB, uid)
    insert_assignment(db, jan, w, date(2099, 1, 31), "C", GG)
    assert _add(client, "2099-02", w, FEB, "A", 1).status_code == 200


# --- locked shifts -----------------------------------------------------------


@requires_db
def test_started_shifts_are_locked_for_add_remove_move(planner, db, freeze):
    client, uid = planner
    w = _worker(db, uid, "111111118")
    w2 = _worker(db, uid, "222222226")
    roster = insert_roster(db, date(2026, 3, 1), uid)
    started = insert_assignment(db, roster, w, date(2026, 3, 5), "A", GG)
    upcoming = insert_assignment(db, roster, w, date(2026, 3, 20), "A", GG)
    freeze(datetime(2026, 3, 10, 10, 0))
    resp = _add(client, "2026-03", w2, date(2026, 3, 9), "C", 1)
    assert resp.status_code == 422 and _code(resp) == "LOCKED_SHIFT"
    assert _code(_add(client, "2026-03", w2, date(2026, 3, 10), "B", 1)) == "LOCKED_SHIFT"  # B started at 08:00
    resp = client.request("DELETE", f"/api/rosters/2026-03/assignments/{started}", json={"expected_version": 1})
    assert resp.status_code == 422 and _code(resp) == "LOCKED_SHIFT"
    resp = client.post(f"/api/rosters/2026-03/assignments/{started}/move", json={"date": "2026-03-21", "expected_version": 1})
    assert _code(resp) == "LOCKED_SHIFT"
    resp = client.post(f"/api/rosters/2026-03/assignments/{upcoming}/move", json={"date": "2026-03-06", "expected_version": 1})
    assert _code(resp) == "LOCKED_SHIFT"  # target already started
    assert _version(db, date(2026, 3, 1)) == 1
    assert _add(client, "2026-03", w2, date(2026, 3, 10), "C", 1).status_code == 200  # first free shift


@requires_db
def test_history_month_is_locked(planner, db, freeze):
    client, uid = planner
    w = _worker(db, uid, "111111118")
    insert_roster(db, date(2026, 2, 1), uid)
    freeze(datetime(2026, 3, 10, 10, 0))
    assert _code(_add(client, "2026-02", w, date(2026, 2, 5), "A", 1)) == "LOCKED_SHIFT"


# --- approved rosters ----------------------------------------------------------


@requires_db
def test_editing_approved_roster_needs_acknowledgement_and_returns_to_draft(planner, db):
    client, uid = planner
    w = _worker(db, uid, "111111118")
    roster = insert_roster(db, JAN, uid, status="APPROVED")
    insert_approval(db, roster, uid)
    resp = _add(client, "2099-01", w, D5, "A", 1)
    assert resp.status_code == 409 and _code(resp) == "APPROVED_EDIT_NOT_ACKNOWLEDGED"
    assert _q(db, "SELECT status, row_version FROM rosters") == [("APPROVED", 1)]
    assert _q(db, "SELECT count(*) FROM roster_assignments") == [(0,)]

    resp = _add(client, "2099-01", w, D5, "A", 1, acknowledge_approved_edit=True)
    assert resp.status_code == 200
    assert resp.json()["status"] == "DRAFT" and resp.json()["approval_revoked"] is True
    rows = _q(db, "SELECT revoke_cause, revoked_by FROM roster_approvals")
    assert rows == [("EDIT", uid)]  # history kept, not deleted
    hist = client.get("/api/rosters/2099-01").json()["approval_history"]
    assert len(hist) == 1 and hist[0]["revoke_cause"] == "EDIT"


@requires_db
def test_removal_and_move_on_approved_roster_need_acknowledgement(planner, db):
    client, uid = planner
    w = _worker(db, uid, "111111118")
    roster = insert_roster(db, JAN, uid, status="APPROVED")
    insert_approval(db, roster, uid)
    a = insert_assignment(db, roster, w, D5, "A", GG)
    resp = client.request("DELETE", f"/api/rosters/2099-01/assignments/{a}", json={"expected_version": 1})
    assert _code(resp) == "APPROVED_EDIT_NOT_ACKNOWLEDGED"
    resp = client.post(f"/api/rosters/2099-01/assignments/{a}/move", json={"shift": "C", "expected_version": 1})
    assert _code(resp) == "APPROVED_EDIT_NOT_ACKNOWLEDGED"
    resp = client.post(f"/api/rosters/2099-01/assignments/{a}/move", json={"shift": "C", "expected_version": 1, "acknowledge_approved_edit": True})
    assert resp.status_code == 200 and resp.json()["status"] == "DRAFT"


# --- neighbor-month row_version / fingerprint ---------------------------------


@requires_db
def test_every_edit_kind_increments_row_version(planner, db):
    client, uid = planner
    w = _worker(db, uid, "111111118")
    insert_roster(db, JAN, uid)
    r = _add(client, "2099-01", w, D5, "A", 1).json()
    assert r["version"] == 2
    a = r["assignment"]["id"]
    r = client.post(f"/api/rosters/2099-01/assignments/{a}/move", json={"shift": "C", "expected_version": 2}).json()
    assert r["version"] == 3
    r = client.request("DELETE", f"/api/rosters/2099-01/assignments/{a}", json={"expected_version": 3}).json()
    assert r["version"] == 4 and _version(db, JAN) == 4


@requires_db
def test_edit_to_adjacent_month_makes_a_previewed_save_stale(planner, db, fingerprint_for):
    client, uid = planner
    w = _worker(db, uid, "111111118")
    insert_roster(db, FEB, uid)
    before = fingerprint_for(JAN)
    assert _add(client, "2099-02", w, date(2099, 2, 10), "A", 1).status_code == 200  # edit next month's roster
    after = fingerprint_for(JAN)
    assert before != after
    body = {
        "assignments": [{"worker_id": str(w), "date": "2099-01-05", "shift": "A", "role": GG}],
        "fingerprint": before,
    }
    resp = client.post("/api/rosters/2099-01/save", json=body)
    assert resp.status_code == 409 and _code(resp) == "STALE_PREVIEW"
    assert _q(db, "SELECT count(*) FROM rosters WHERE month = %s", JAN) == [(0,)]
    assert client.post("/api/rosters/2099-01/save", json={**body, "fingerprint": after}).status_code == 200


@requires_db
def test_edit_to_previous_month_makes_a_previewed_save_stale(planner, db, fingerprint_for):
    client, uid = planner
    w = _worker(db, uid, "111111118")
    dec = insert_roster(db, date(2098, 12, 1), uid)
    before = fingerprint_for(JAN)
    a = insert_assignment(db, dec, w, date(2098, 12, 10), "A", GG)
    assert client.request("DELETE", f"/api/rosters/2098-12/assignments/{a}", json={"expected_version": 1}).status_code == 200
    body = {"assignments": [], "fingerprint": before}
    assert _code(client.post("/api/rosters/2099-01/save", json=body)) == "STALE_PREVIEW"


# --- permissions / validation --------------------------------------------------


@requires_db
def test_requires_login_and_strict_month(planner, db):
    client, uid = planner
    assert client.post("/api/rosters/2099-1/assignments", json={}).status_code == 422
    client.post("/api/auth/logout")
    assert _add(client, "2099-01", 1, D5, "A", 1).status_code == 401


# --- swap --------------------------------------------------------------------


def _swap(client, month, a_id, b_id, version, **kw):
    body = {"other_assignment_id": b_id, "expected_version": version, **kw}
    return client.post(f"/api/rosters/{month}/assignments/{a_id}/swap", json=body)


@requires_db
def test_swap_exchanges_workers_across_days_and_bumps_version(planner, db):
    client, uid = planner
    w1, w2 = _worker(db, uid, "111111118"), _worker(db, uid, "222222226")
    roster = insert_roster(db, JAN, uid)
    a = insert_assignment(db, roster, w1, D5, "A", GG)
    b = insert_assignment(db, roster, w2, date(2099, 1, 7), "A", GG)
    resp = _swap(client, "2099-01", a, b, 1)
    assert resp.status_code == 200, resp.text
    assert resp.json()["version"] == 2
    rows = dict(_q(db, "SELECT id, worker_id FROM roster_assignments WHERE roster_id = %s", roster))
    assert rows == {a: w2, b: w1}


@requires_db
def test_swap_may_cross_shifts(planner, db):
    client, uid = planner
    w1, w2 = _worker(db, uid, "111111118"), _worker(db, uid, "222222226")
    roster = insert_roster(db, JAN, uid)
    a = insert_assignment(db, roster, w1, D5, "A", GG)
    b = insert_assignment(db, roster, w2, date(2099, 1, 7), "B", GG)
    resp = _swap(client, "2099-01", a, b, 1)
    assert resp.status_code == 200, resp.text
    rows = dict(_q(db, "SELECT id, worker_id FROM roster_assignments WHERE roster_id = %s", roster))
    assert rows == {a: w2, b: w1}


@requires_db
def test_swap_rejects_bad_pairs_and_worsening(planner, db):
    client, uid = planner
    w1 = _worker(db, uid, "111111118")
    w2 = _worker(db, uid, "222222226")
    w3 = _worker(db, uid, "333333334", role="SCREENER")
    roster = insert_roster(db, JAN, uid)
    a = insert_assignment(db, roster, w1, D5, "A", GG)
    same_slot = insert_assignment(db, roster, w2, D5, "A", GG)
    other_shift = insert_assignment(db, roster, w2, date(2099, 1, 7), "B", GG)
    other_role = insert_assignment(db, roster, w3, date(2099, 1, 7), "A", "SCREENER")
    assert _swap(client, "2099-01", a, same_slot, 1).status_code == 400
    assert _swap(client, "2099-01", a, other_role, 1).status_code == 400
    assert _swap(client, "2099-01", a, a, 1).status_code == 400
    assert _swap(client, "2099-01", a, 999999, 1).status_code == 404
    assert _swap(client, "2099-01", a, other_shift, 7).status_code == 409
    assert _version(db, JAN) == 1


@requires_db
def test_swap_rejected_when_it_would_break_a_rule_and_when_approved_unacknowledged(planner, db):
    client, uid = planner
    w1 = _worker(db, uid, "111111118")
    w2 = _worker(db, uid, "222222226", availability=["MON:A"])
    roster = insert_roster(db, JAN, uid)
    a = insert_assignment(db, roster, w1, date(2099, 1, 7), "A", GG)  # Wednesday
    b = insert_assignment(db, roster, w2, D5, "A", GG)  # Monday: w2 is only available Mondays
    resp = _swap(client, "2099-01", a, b, 1)
    assert resp.status_code == 422 and _code(resp) == "HARD_VIOLATIONS"
    assert _version(db, JAN) == 1
