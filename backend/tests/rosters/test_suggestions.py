"""§8 T7 suggestions (bonus 2): eligibility (incl. adjacency where the
rule applies), none for started or filled slots, ranking, reasons, and an
apply (the add endpoint) that is revalidated."""
from __future__ import annotations

from datetime import date, datetime

from app.rosters.suggestions import suggest
from app.scheduling.types import DEFAULT_DEMAND, Assignment, Problem, Role, Shift, Weekday, WorkerInput
from tests.conftest import requires_db
from tests.rosters.helpers import insert_assignment, insert_contract, insert_roster, insert_worker

JAN = date(2099, 1, 1)
D5 = date(2099, 1, 5)  # Monday
GG = "GENERAL_GUARD"
ALL = frozenset((d, s) for d in Weekday for s in Shift)


def _w(id, role=Role.GENERAL_GUARD, active=True, min_hours=0, max_hours=200, availability=ALL):
    return WorkerInput(id, role, active, availability, min_hours, max_hours)


def _problem(workers, forbid=False, free_from=(date(2099, 1, 1), Shift.A), neighbor=()):
    return Problem(2099, 1, DEFAULT_DEMAND, workers, free_from, (), tuple(neighbor), forbid)


def _ids(cands):
    return [c.worker_id for c in cands]


# --- pure ----------------------------------------------------------------------


def test_eligibility_filters_role_active_availability_and_max_hours():
    p = _problem(
        [
            _w("ok"),
            _w("screener", role=Role.SCREENER),
            _w("inactive", active=False),
            _w("unavail", availability=frozenset({(Weekday.TUE, Shift.A)})),
            _w("full", max_hours=8),
        ]
    )
    existing = [Assignment("full", date(2099, 1, 6), Shift.A, Role.GENERAL_GUARD)]
    state, cands = suggest(p, existing, D5, Shift.A, Role.GENERAL_GUARD, {})
    assert state == "OPEN" and _ids(cands) == ["ok"]


def test_adjacency_only_where_the_rule_applies():
    prior = [Assignment("w", D5, Shift.B, Role.GENERAL_GUARD)]
    off = suggest(_problem([_w("w")]), prior, D5, Shift.A, Role.GENERAL_GUARD, {})[1]
    on = suggest(_problem([_w("w")], forbid=True), prior, D5, Shift.A, Role.GENERAL_GUARD, {})[1]
    assert _ids(off) == ["w"] and on == []


def test_boundary_adjacency_uses_neighbor_assignments():
    nb = [Assignment("w", date(2098, 12, 31), Shift.C, Role.GENERAL_GUARD)]
    p = _problem([_w("w"), _w("x")], neighbor=nb)
    assert _ids(suggest(p, [], date(2099, 1, 1), Shift.A, Role.GENERAL_GUARD, {})[1]) == ["x"]


def test_no_candidates_for_started_or_filled_slots():
    p = _problem([_w("w")], free_from=(D5, Shift.B))
    assert suggest(p, [], D5, Shift.A, Role.GENERAL_GUARD, {}) == ("LOCKED", [])
    assert suggest(p, [], date(2099, 1, 4), Shift.C, Role.GENERAL_GUARD, {})[0] == "LOCKED"
    full = [Assignment(f"g{i}", D5, Shift.C, Role.SUPERVISOR) for i in range(1)]
    assert suggest(_problem([_w("s", role=Role.SUPERVISOR)]), full, D5, Shift.C, Role.SUPERVISOR, {}) == ("FILLED", [])


def test_ranking_deficit_then_hours_then_name_and_reasons():
    p = _problem(
        [
            _w("a", role=Role.SCREENER, min_hours=160),
            _w("b", role=Role.SCREENER, min_hours=160),
            _w("c", role=Role.SCREENER, min_hours=0),
            _w("d", role=Role.SCREENER, min_hours=0),
        ]
    )
    hours = [Assignment("b", date(2099, 1, 6 + i), Shift.A, Role.SCREENER) for i in range(2)]
    hours += [Assignment("c", date(2099, 1, 6), Shift.C, Role.SCREENER)]
    names = {"a": "Zed", "b": "Amy", "c": "Bob", "d": "Al"}
    state, cands = suggest(p, hours, D5, Shift.B, Role.SCREENER, names)
    # a: deficit 160; b: deficit 144; c and d: no deficit, d has fewer hours
    assert _ids(cands) == ["a", "b", "d", "c"]
    assert cands[0].reasons == ("Screener", "available Mon B", "0/160 h (160 h below minimum)", "0 shifts that day")
    assert cands[1].reasons[2] == "16/160 h (144 h below minimum)"
    assert cands[3].reasons[2] == "8/0 h (minimum met)" and cands[3].shifts_that_day == 0


def test_shifts_that_day_counts_and_daily_limit_excludes():
    p = _problem([_w("w")])
    two = [Assignment("w", D5, Shift.A, Role.GENERAL_GUARD), Assignment("w", D5, Shift.B, Role.GENERAL_GUARD)]
    assert suggest(p, two, D5, Shift.C, Role.GENERAL_GUARD, {})[1] == []  # 3rd shift: DAILY_LIMIT
    one = two[:1]
    c = suggest(p, one, D5, Shift.C, Role.GENERAL_GUARD, {})[1][0]
    assert c.shifts_that_day == 1 and c.reasons[3] == "1 shift that day"


# --- API -----------------------------------------------------------------------


def _worker(db, uid, nid, name, role=GG, status="ACTIVE", **contract):
    wid = insert_worker(db, nid, full_name=name, role=role, status=status)
    insert_contract(db, wid, uid, effective_month=date(2026, 1, 1), **contract)
    return wid


def _get(client, month, d, shift, role=GG):
    return client.get(f"/api/rosters/{month}/suggestions", params={"date": d, "shift": shift, "role": role})


@requires_db
def test_suggestions_endpoint_ranked_with_names_and_apply_revalidated(planner, db):
    client, uid = planner
    low = _worker(db, uid, "111111118", "Low", min_hours=40)
    none = _worker(db, uid, "222222226", "None")
    _worker(db, uid, "333333334", "Off", status="INACTIVE")
    roster = insert_roster(db, JAN, uid)
    insert_assignment(db, roster, none, date(2099, 1, 6), "A", GG)
    resp = _get(client, "2099-01", "2099-01-05", "A")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["slot_state"] == "OPEN"
    assert [c["full_name"] for c in body["candidates"]] == ["Low", "None"]
    assert body["candidates"][0]["hours_below_minimum"] == 40
    assert body["candidates"][0]["reasons"][1] == "available Mon A"

    # apply = add endpoint; after it the candidate is gone, and re-applying is revalidated (422)
    add = {"worker_id": str(low), "date": "2099-01-05", "shift": "A", "role": GG, "expected_version": 1}
    assert client.post("/api/rosters/2099-01/assignments", json=add).status_code == 200
    assert [c["full_name"] for c in _get(client, "2099-01", "2099-01-05", "A").json()["candidates"]] == ["None"]
    stale = client.post("/api/rosters/2099-01/assignments", json={**add, "expected_version": 2})
    assert stale.status_code == 422 and stale.json()["error"]["code"] == "HARD_VIOLATIONS"


@requires_db
def test_suggestions_endpoint_none_for_started_shifts_and_history(planner, db, freeze):
    client, uid = planner
    _worker(db, uid, "111111118", "W")
    insert_roster(db, date(2026, 3, 1), uid)
    insert_roster(db, date(2026, 2, 1), uid)
    freeze(datetime(2026, 3, 10, 10, 0))
    started = _get(client, "2026-03", "2026-03-10", "B").json()
    assert started["slot_state"] == "LOCKED" and started["candidates"] == []
    assert _get(client, "2026-03", "2026-03-10", "C").json()["candidates"] != []
    assert _get(client, "2026-02", "2026-02-10", "A").json()["slot_state"] == "LOCKED"


@requires_db
def test_suggestions_endpoint_boundary_adjacency_and_validation(planner, db):
    client, uid = planner
    w = _worker(db, uid, "111111118", "W")
    dec = insert_roster(db, date(2098, 12, 1), uid, forbid_adjacent_shifts=True)
    insert_roster(db, JAN, uid)
    insert_assignment(db, dec, w, date(2098, 12, 31), "C", GG)
    assert _get(client, "2099-01", "2099-01-01", "A").json()["candidates"] == []  # Dec roster has the rule on
    assert _get(client, "2099-01", "2099-01-01", "B").json()["candidates"] != []
    assert _get(client, "2099-01", "2099-02-01", "A").status_code == 422  # date outside the month
    assert _get(client, "2099-05", "2099-05-01", "A").status_code == 404
