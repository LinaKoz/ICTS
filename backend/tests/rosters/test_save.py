"""§8 T3: save -- stores `forbid_adjacent_shifts`, fingerprint mismatch
409 (incl. a shift that started between generate and save, and a flag
mismatch), changed started shift 422 LOCKED_SHIFT, replace needs the
flag and version, new hard violations 422 while existing ones in locked
shifts do not block, approval revoked on replace (REGENERATE)."""
from __future__ import annotations

from datetime import date, datetime

from tests.conftest import requires_db
from tests.rosters.helpers import insert_approval, insert_assignment, insert_contract, insert_roster, insert_worker

FUTURE = date(2099, 1, 1)
FUTURE_URL = "/api/rosters/2099-01/save"


def _a(worker_id: int, d: date, shift: str, role: str = "GENERAL_GUARD") -> dict:
    return {"worker_id": str(worker_id), "date": d.isoformat(), "shift": shift, "role": role}


def _guard(db, user_id, nid="111111118", **contract):
    wid = insert_worker(db, nid)
    insert_contract(db, wid, user_id, effective_month=date(2026, 1, 1), **contract)
    return wid


def _row(db, sql: str, *params):
    with db.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def _body(assignments, fingerprint, **kw) -> dict:
    return {"assignments": assignments, "fingerprint": fingerprint, **kw}


@requires_db
def test_save_creates_draft_and_stores_the_flag(planner, db, fingerprint_for):
    client, user_id = planner
    w = _guard(db, user_id)
    fp = fingerprint_for(FUTURE, True)
    resp = client.post(FUTURE_URL, json=_body([_a(w, date(2099, 1, 5), "A")], fp, forbid_adjacent_shifts=True))
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "DRAFT" and resp.json()["version"] == 1
    assert _row(db, "SELECT status, forbid_adjacent_shifts FROM rosters") == [("DRAFT", True)]
    assert _row(db, "SELECT count(*) FROM roster_assignments") == [(1,)]
    got = client.get("/api/rosters/2099-01").json()
    assert got["forbid_adjacent_shifts"] is True and len(got["assignments"]) == 1


@requires_db
def test_save_stale_fingerprint_is_409_and_persists_nothing(planner, db, fingerprint_for):
    client, user_id = planner
    w = _guard(db, user_id)
    fp = fingerprint_for(FUTURE)
    with db.cursor() as cur:
        cur.execute("UPDATE workers SET row_version = row_version + 1 WHERE id = %s", (w,))
    resp = client.post(FUTURE_URL, json=_body([_a(w, date(2099, 1, 5), "A")], fp))
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "STALE_PREVIEW"
    assert _row(db, "SELECT count(*) FROM rosters") == [(0,)]


@requires_db
def test_save_new_contract_changes_fingerprint(planner, db, fingerprint_for):
    client, user_id = planner
    w = _guard(db, user_id)
    fp = fingerprint_for(FUTURE)
    insert_contract(db, w, user_id, version_no=2, effective_month=date(2026, 6, 1), rate="50.00")
    resp = client.post(FUTURE_URL, json=_body([_a(w, date(2099, 1, 5), "A")], fp))
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "STALE_PREVIEW"


@requires_db
def test_save_flag_mismatch_against_fingerprint_is_409(planner, db, fingerprint_for):
    client, user_id = planner
    w = _guard(db, user_id)
    fp = fingerprint_for(FUTURE, False)
    resp = client.post(FUTURE_URL, json=_body([_a(w, date(2099, 1, 5), "A")], fp, forbid_adjacent_shifts=True))
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "STALE_PREVIEW"


@requires_db
def test_save_neighbor_roster_change_is_409(planner, db, fingerprint_for):
    client, user_id = planner
    w = _guard(db, user_id)
    prev = insert_roster(db, date(2098, 12, 1), user_id)
    fp = fingerprint_for(FUTURE)
    with db.cursor() as cur:
        cur.execute("UPDATE rosters SET forbid_adjacent_shifts = true, row_version = 2 WHERE id = %s", (prev,))
    resp = client.post(FUTURE_URL, json=_body([_a(w, date(2099, 1, 5), "A")], fp))
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "STALE_PREVIEW"


@requires_db
def test_save_shift_started_between_generate_and_save_is_409(planner, db, freeze, fingerprint_for):
    client, user_id = planner
    w = _guard(db, user_id)
    freeze(datetime(2026, 3, 10, 7, 59))
    fp = fingerprint_for(date(2026, 3, 1))
    freeze(datetime(2026, 3, 10, 8, 0))  # shift B starts: free_from moves
    resp = client.post("/api/rosters/2026-03/save", json=_body([_a(w, date(2026, 3, 20), "A")], fp))
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "STALE_PREVIEW"


@requires_db
def test_save_changed_started_shift_is_422_locked_shift(planner, db, freeze, fingerprint_for):
    client, user_id = planner
    w = _guard(db, user_id)
    roster_id = insert_roster(db, date(2026, 3, 1), user_id)
    insert_assignment(db, roster_id, w, date(2026, 3, 5), "A", "GENERAL_GUARD")
    freeze(datetime(2026, 3, 10, 10, 0))
    fp = fingerprint_for(date(2026, 3, 1))
    # body drops the started assignment and adds a different one in a started shift
    body = _body([_a(w, date(2026, 3, 6), "B"), _a(w, date(2026, 3, 20), "A")], fp, replace_existing=True, expected_version=1)
    resp = client.post("/api/rosters/2026-03/save", json=body)
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "LOCKED_SHIFT"
    assert _row(db, "SELECT count(*) FROM roster_assignments") == [(1,)]


@requires_db
def test_save_keeps_started_shifts_and_replaces_free_ones(planner, db, freeze, fingerprint_for):
    client, user_id = planner
    w = _guard(db, user_id)
    roster_id = insert_roster(db, date(2026, 3, 1), user_id)
    insert_assignment(db, roster_id, w, date(2026, 3, 5), "A", "GENERAL_GUARD")
    insert_assignment(db, roster_id, w, date(2026, 3, 25), "A", "GENERAL_GUARD")
    freeze(datetime(2026, 3, 10, 10, 0))
    fp = fingerprint_for(date(2026, 3, 1))
    body = _body([_a(w, date(2026, 3, 5), "A"), _a(w, date(2026, 3, 26), "B")], fp, replace_existing=True, expected_version=1)
    resp = client.post("/api/rosters/2026-03/save", json=body)
    assert resp.status_code == 200, resp.text
    assert resp.json()["version"] == 2
    assert _row(db, "SELECT date, shift FROM roster_assignments ORDER BY date") == [
        (date(2026, 3, 5), "A"), (date(2026, 3, 26), "B")]


@requires_db
def test_save_replace_needs_flag_and_matching_version(planner, db, fingerprint_for):
    client, user_id = planner
    w = _guard(db, user_id)
    roster_id = insert_roster(db, FUTURE, user_id)
    insert_assignment(db, roster_id, w, date(2099, 1, 3), "A", "GENERAL_GUARD")
    fp = fingerprint_for(FUTURE)
    new = [_a(w, date(2099, 1, 5), "A")]

    no_flag = client.post(FUTURE_URL, json=_body(new, fp, expected_version=1))
    assert no_flag.status_code == 409 and no_flag.json()["error"]["code"] == "VERSION_CONFLICT"
    bad_version = client.post(FUTURE_URL, json=_body(new, fp, replace_existing=True, expected_version=7))
    assert bad_version.status_code == 409 and bad_version.json()["error"]["code"] == "VERSION_CONFLICT"
    assert _row(db, "SELECT date FROM roster_assignments") == [(date(2099, 1, 3),)]

    ok = client.post(FUTURE_URL, json=_body(new, fp, replace_existing=True, expected_version=1))
    assert ok.status_code == 200 and ok.json()["version"] == 2
    assert _row(db, "SELECT date FROM roster_assignments") == [(date(2099, 1, 5),)]


@requires_db
def test_save_new_hard_violation_is_422_and_persists_nothing(planner, db, fingerprint_for):
    client, user_id = planner
    w = _guard(db, user_id, availability=["MON:A"])  # 2099-01-05 is a Monday; shift B is not available
    fp = fingerprint_for(FUTURE)
    resp = client.post(FUTURE_URL, json=_body([_a(w, date(2099, 1, 5), "B")], fp))
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "HARD_VIOLATIONS"
    assert {d["code"] for d in resp.json()["error"]["details"]} == {"UNAVAILABLE"}
    assert _row(db, "SELECT count(*) FROM rosters") == [(0,)]


@requires_db
def test_save_existing_violation_in_locked_shift_does_not_block(planner, db, freeze, fingerprint_for):
    client, user_id = planner
    w = _guard(db, user_id, availability=["MON:A"])
    roster_id = insert_roster(db, date(2026, 3, 1), user_id)
    insert_assignment(db, roster_id, w, date(2026, 3, 5), "A", "GENERAL_GUARD")  # Thursday: UNAVAILABLE, but started
    freeze(datetime(2026, 3, 10, 10, 0))
    fp = fingerprint_for(date(2026, 3, 1))
    body = _body([_a(w, date(2026, 3, 5), "A"), _a(w, date(2026, 3, 16), "A")], fp, replace_existing=True, expected_version=1)
    resp = client.post("/api/rosters/2026-03/save", json=body)
    assert resp.status_code == 200, resp.text


@requires_db
def test_save_worsening_an_existing_violation_is_still_rejected(planner, db, freeze, fingerprint_for):
    client, user_id = planner
    w = _guard(db, user_id, max_hours=8)  # the started shift already fills the cap ... and one more is over
    roster_id = insert_roster(db, date(2026, 3, 1), user_id)
    insert_assignment(db, roster_id, w, date(2026, 3, 5), "A", "GENERAL_GUARD")
    insert_assignment(db, roster_id, w, date(2026, 3, 6), "A", "GENERAL_GUARD")  # 16h > 8h: MAX_HOURS mag 8
    freeze(datetime(2026, 3, 10, 10, 0))
    fp = fingerprint_for(date(2026, 3, 1))
    body = _body([_a(w, date(2026, 3, 5), "A"), _a(w, date(2026, 3, 6), "A"), _a(w, date(2026, 3, 16), "A")], fp,
                 replace_existing=True, expected_version=1)
    resp = client.post("/api/rosters/2026-03/save", json=body)
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "HARD_VIOLATIONS"
    assert {d["code"] for d in resp.json()["error"]["details"]} == {"MAX_HOURS"}


@requires_db
def test_save_replacing_approved_roster_revokes_approval_regenerate(planner, db, fingerprint_for):
    client, user_id = planner
    w = _guard(db, user_id)
    roster_id = insert_roster(db, FUTURE, user_id, status="APPROVED")
    insert_assignment(db, roster_id, w, date(2099, 1, 3), "A", "GENERAL_GUARD")
    insert_approval(db, roster_id, user_id)
    fp = fingerprint_for(FUTURE)
    resp = client.post(FUTURE_URL, json=_body([_a(w, date(2099, 1, 5), "A")], fp, replace_existing=True, expected_version=1))
    assert resp.status_code == 200 and resp.json()["status"] == "DRAFT"
    (cause, revoked_by, revoked_at) = _row(db, "SELECT revoke_cause, revoked_by, revoked_at FROM roster_approvals")[0]
    assert cause == "REGENERATE" and revoked_by == user_id and revoked_at is not None
    assert _row(db, "SELECT status FROM rosters") == [("DRAFT",)]
    hist = client.get("/api/rosters/2099-01").json()["approval_history"]
    assert hist[0]["revoke_cause"] == "REGENERATE"


@requires_db
def test_save_history_month_rejected(planner, db):
    client, _ = planner
    resp = client.post("/api/rosters/2001-01/save", json=_body([], "x"))
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "LOCKED_SHIFT"
