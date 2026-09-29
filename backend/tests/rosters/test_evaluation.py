"""§8 T3: `GET /rosters/{month}` / `evaluate` -- violations on read with
the D9(b) locked-shift override, NO_CONTRACT_FOR_MONTH (P4), history
months without evaluation (P3), costs with unknown contracts (P15)."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from tests.conftest import requires_db
from tests.rosters.helpers import (
    insert_assignment,
    insert_contract,
    insert_roster,
    insert_worker,
    insert_worker_field_history,
)

TZ = ZoneInfo("Asia/Jerusalem")
MARCH = date(2026, 3, 1)


def _codes(body: dict) -> list[tuple[str, str]]:
    return sorted((v["code"], v["key"][0]) for v in body["violations"])


def _setup(db, user_id, **worker_kw):
    wid = insert_worker(db, "111111118", **worker_kw)
    insert_contract(db, wid, user_id, effective_month=date(2026, 1, 1))
    roster = insert_roster(db, MARCH, user_id)
    return wid, roster


@requires_db
def test_get_roster_404_when_missing(planner):
    client, _ = planner
    resp = client.get("/api/rosters/2099-05")
    assert resp.status_code == 404 and resp.json()["error"]["code"] == "NOT_FOUND"


@requires_db
def test_worker_deactivated_after_shift_started_is_not_a_violation_but_upcoming_is(planner, db, freeze):
    client, user_id = planner
    wid, roster = _setup(db, user_id, status="INACTIVE")  # deactivated 03-07, i.e. after the 03-05 shift
    insert_worker_field_history(db, wid, "STATUS", "ACTIVE", "INACTIVE", datetime(2026, 3, 7, 12, 0, tzinfo=TZ), user_id)
    insert_assignment(db, roster, wid, date(2026, 3, 5), "A", "GENERAL_GUARD")  # started, worked while ACTIVE
    insert_assignment(db, roster, wid, date(2026, 3, 20), "A", "GENERAL_GUARD")  # upcoming
    freeze(datetime(2026, 3, 10, 10, 0))

    body = client.get("/api/rosters/2026-03").json()
    inactive = [v for v in body["violations"] if v["code"] == "INACTIVE_WORKER"]
    assert [v["key"][1] for v in inactive] == ["2026-03-20"]
    # deactivation must not surface as UNAVAILABLE / MAX_HOURS on the worked shift either
    assert {v["code"] for v in body["violations"]} == {"INACTIVE_WORKER"}


@requires_db
def test_worker_already_inactive_before_shift_started_still_violates(planner, db, freeze):
    client, user_id = planner
    wid, roster = _setup(db, user_id, status="INACTIVE")
    insert_worker_field_history(db, wid, "STATUS", "ACTIVE", "INACTIVE", datetime(2026, 3, 1, 0, 0, tzinfo=TZ), user_id)
    insert_assignment(db, roster, wid, date(2026, 3, 5), "A", "GENERAL_GUARD")
    freeze(datetime(2026, 3, 10, 10, 0))
    body = client.get("/api/rosters/2026-03").json()
    assert _codes(body) == [("INACTIVE_WORKER", str(wid))]


@requires_db
def test_role_change_after_shift_started_is_not_wrong_role_but_upcoming_is(planner, db, freeze):
    client, user_id = planner
    wid, roster = _setup(db, user_id, role="SCREENER")  # was GENERAL_GUARD until 03-07
    insert_worker_field_history(db, wid, "ROLE", "GENERAL_GUARD", "SCREENER", datetime(2026, 3, 7, 12, 0, tzinfo=TZ), user_id)
    insert_assignment(db, roster, wid, date(2026, 3, 5), "A", "GENERAL_GUARD")
    insert_assignment(db, roster, wid, date(2026, 3, 20), "A", "GENERAL_GUARD")
    freeze(datetime(2026, 3, 10, 10, 0))
    body = client.get("/api/rosters/2026-03").json()
    wrong = [v for v in body["violations"] if v["code"] == "WRONG_ROLE"]
    assert [v["key"][1] for v in wrong] == ["2026-03-20"]


@requires_db
def test_active_worker_without_contract_gets_no_contract_for_month(planner, db, freeze):
    client, user_id = planner
    wid = insert_worker(db, "111111118")  # no contract at all
    roster = insert_roster(db, MARCH, user_id)
    insert_assignment(db, roster, wid, date(2026, 3, 20), "A", "GENERAL_GUARD")
    freeze(datetime(2026, 3, 10, 10, 0))
    body = client.get("/api/rosters/2026-03").json()
    assert _codes(body) == [("NO_CONTRACT_FOR_MONTH", str(wid))]
    assert body["costs"]["unknown_cost_worker_count"] == 1
    assert body["costs"]["monthly_total_ils"] == "0.00"
    assert body["costs"]["per_worker"][0]["amount_ils"] is None


@requires_db
def test_inactive_worker_with_contract_keeps_known_cost(planner, db, freeze):
    client, user_id = planner
    wid, roster = _setup(db, user_id, status="INACTIVE")
    insert_assignment(db, roster, wid, date(2026, 3, 20), "A", "GENERAL_GUARD")
    freeze(datetime(2026, 3, 10, 10, 0))
    body = client.get("/api/rosters/2026-03").json()
    assert body["costs"]["unknown_cost_worker_count"] == 0
    assert body["costs"]["monthly_total_ils"] == "320.00"
    assert body["costs"]["per_shift"] == [
        {"date": "2026-03-20", "shift": "A", "amount_ils": "320.00", "unknown_cost_assignments": 0}]


@requires_db
def test_history_month_is_read_only_and_not_evaluated(planner, db, freeze):
    client, user_id = planner
    wid = insert_worker(db, "111111118", status="INACTIVE")
    insert_contract(db, wid, user_id, effective_month=date(2026, 1, 1))
    roster = insert_roster(db, date(2026, 1, 1), user_id)
    insert_assignment(db, roster, wid, date(2026, 1, 5), "A", "GENERAL_GUARD")  # would violate if evaluated
    freeze(datetime(2026, 3, 10, 10, 0))
    body = client.get("/api/rosters/2026-01").json()
    assert body["is_history"] is True
    assert body["violations"] == []
    assert body["free_from"] == ["2026-02-01", "A"]
    assert len(body["assignments"]) == 1


@requires_db
def test_free_from_and_flags_reported(planner, db, freeze):
    client, user_id = planner
    _setup(db, user_id)
    freeze(datetime(2026, 3, 10, 10, 30))
    body = client.get("/api/rosters/2026-03").json()
    assert body["is_history"] is False and body["forbid_adjacent_shifts"] is False
    assert body["free_from"][0] == "2026-03-10" and body["free_from"][1] == "C"
