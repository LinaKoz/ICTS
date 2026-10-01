"""§8 T5 contract-change acceptance: impact listing, apply semantics, stale
base, P1 same-month correction, started shifts exempt from availability and
worked-hours limits, P5 identical data."""
from __future__ import annotations

from datetime import date

import pytest

from tests.conftest import requires_db
from tests.rosters.helpers import insert_assignment
from tests.workers.conftest import all_but, contract_body
from tests.workers.scenario import (
    FREE,
    LOCKED,
    NOW,
    approvals,
    assignment_count,
    roster_row,
    seed,
    slot,
    version_count,
)


@pytest.fixture()
def world(planner, db, freeze):
    freeze(NOW)
    client, uid = planner
    return client, uid, db, seed(db, uid)


def _preview(client, w, body):
    r = client.post(f"/api/workers/{w}/contracts/preview", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _apply(client, w, body, fingerprint):
    return client.post(f"/api/workers/{w}/contracts", json={**body, "fingerprint": fingerprint})


@requires_db
def test_contracts_listing_with_resolved_for(world):
    client, uid, db, ids = world
    w = ids["w"]
    r = client.get(f"/api/workers/{w}/contracts").json()
    assert r["resolved_for"] == "2026-09" and r["resolved"]["version_no"] == 1
    assert [v["effective_month"] for v in r["versions"]] == ["2026-01"]
    assert r["versions"][0]["hourly_rate_ils"] == "40.00" and r["versions"][0]["created_by"] == "planner"
    before = client.get(f"/api/workers/{w}/contracts?resolved_for=2025-12").json()
    assert before["resolved"] is None and len(before["versions"]) == 1
    assert client.get(f"/api/workers/{w}/contracts?resolved_for=2026-13").status_code == 422
    assert client.get("/api/workers/9999/contracts").status_code == 404


@requires_db
def test_contract_validation(world):
    client, _, _, ids = world
    url = f"/api/workers/{ids['w']}/contracts/preview"
    ok = contract_body("2026-10")
    for bad in (
        {**ok, "effective_month": "2026-10-01"},
        {**ok, "effective_month": "2026-1"},
        {**ok, "hourly_rate_ils": "0"},
        {**ok, "hourly_rate_ils": "12.345"},
        {**ok, "min_hours": 100, "max_hours": 50},
        {**ok, "max_hours": 745},
        {**ok, "min_hours": -1},
        {**ok, "availability": []},
        {**ok, "availability": ["MON:D"]},
    ):
        r = client.post(url, json=bad)
        assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR", bad
    norm = _preview(client, ids["w"], {**ok, "availability": ["sun:b", "MON:A", "MON:A"]})
    assert norm["unchanged"] is False


@requires_db
def test_preview_lists_affected_rosters_and_writes_nothing(world):
    client, uid, db, ids = world
    body = contract_body("2026-09", all_but(slot(FREE)))  # the upcoming Sunday A becomes unavailable
    p = _preview(client, ids["w"], body)
    assert p["retroactive"] is True and p["unchanged"] is False
    assert p["previous"]["version_no"] == 1
    # Aug is before the effective month; Sep and Oct contain the worker.
    assert [(r["month"], r["is_history"], r["assignment_count"]) for r in p["affected_rosters"]] == [
        ("2026-09", False, 2),
        ("2026-10", False, 1),
    ]
    sep = p["affected_rosters"][0]
    assert [v["code"] for v in sep["new_violations"]] == ["UNAVAILABLE"]
    assert sep["status"] == "APPROVED" and sep["revokes_approval"] is True
    assert p["invalidates_approved"] is True
    assert p["locked_violations"] == [] and sep["locked_violations"] == []  # free shift only
    # A dry run leaves no trace.
    assert version_count(db, ids["w"]) == 1 and roster_row(db, ids["sep"])[0] == "APPROVED"
    assert approvals(db, ids["sep"]) == [(None, None, None, False)]


@requires_db
def test_apply_keeps_assignments_and_revokes_to_draft_keeping_the_approval_row(world):
    client, uid, db, ids = world
    body = contract_body("2026-09", all_but(slot(FREE)))
    p = _preview(client, ids["w"], body)
    r = _apply(client, ids["w"], body, p["fingerprint"])
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["created"] is True and out["contract"]["version_no"] == 2
    assert out["revoked_rosters"] == ["2026-09"] and out["invalidates_approved"] is True

    assert roster_row(db, ids["sep"])[0] == "DRAFT"
    assert assignment_count(db, ids["sep"]) == 3  # nothing rescheduled
    cause, ref, by, revoked = approvals(db, ids["sep"])[0]
    assert cause == "CONTRACT_CHANGE" and ref == f"contract_version:{out['contract']['id']}"
    assert by == uid and revoked is True
    roster = client.get("/api/rosters/2026-09").json()
    assert roster["status"] == "DRAFT" and roster["approval_history"][0]["revoke_cause"] == "CONTRACT_CHANGE"
    assert [v["code"] for v in roster["violations"]] == ["UNAVAILABLE"]


@requires_db
def test_approved_roster_without_new_violations_stays_approved(world):
    client, _, db, ids = world
    body = contract_body("2026-09", rate="55.00")  # same availability, new rate
    p = _preview(client, ids["w"], body)
    assert p["invalidates_approved"] is False
    out = _apply(client, ids["w"], body, p["fingerprint"]).json()
    assert out["created"] is True and out["revoked_rosters"] == []
    assert roster_row(db, ids["sep"])[0] == "APPROVED"
    assert approvals(db, ids["sep"]) == [(None, None, None, False)]


@requires_db
def test_stale_base_is_409_and_nothing_is_applied(world):
    client, _, db, ids = world
    body = contract_body("2026-09", all_but(slot(FREE)))
    p = _preview(client, ids["w"], body)

    # Someone else changes the worker after the preview was shown.
    assert client.patch(f"/api/workers/{ids['w']}", json={"expected_version": 1, "full_name": "Renamed"}).status_code == 200
    r = _apply(client, ids["w"], body, p["fingerprint"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "STALE_PREVIEW"
    fresh = r.json()["error"]["details"]
    assert fresh["fingerprint"] != p["fingerprint"] and fresh["affected_rosters"][0]["month"] == "2026-09"
    assert version_count(db, ids["w"]) == 1 and roster_row(db, ids["sep"])[0] == "APPROVED"
    assert approvals(db, ids["sep"]) == [(None, None, None, False)]

    # The fresh preview's fingerprint works.
    assert _apply(client, ids["w"], body, fresh["fingerprint"]).status_code == 200

    # A roster that moved (edit elsewhere) also makes the preview stale.
    p2 = _preview(client, ids["w"], contract_body("2026-10", rate="60.00"))
    with db.cursor() as cur:
        cur.execute("UPDATE rosters SET row_version = row_version + 1 WHERE id = %s", (ids["oct"],))
    stale = _apply(client, ids["w"], contract_body("2026-10", rate="60.00"), p2["fingerprint"])
    assert stale.status_code == 409 and version_count(db, ids["w"]) == 2

    # A fingerprint from one proposal never authorises different content.
    p3 = _preview(client, ids["w"], contract_body("2026-10", rate="61.00"))
    assert _apply(client, ids["w"], contract_body("2026-10", rate="99.00"), p3["fingerprint"]).status_code == 409


@requires_db
def test_identical_contract_creates_no_version(world):
    client, _, db, ids = world
    same = contract_body("2026-09")  # equals v1 (rate 40.00, 0..200, full availability)
    p = _preview(client, ids["w"], same)
    assert p["unchanged"] is True and p["affected_rosters"] == []
    r = _apply(client, ids["w"], same, p["fingerprint"])
    assert r.status_code == 200 and r.json()["created"] is False and r.json()["contract"] is None
    assert version_count(db, ids["w"]) == 1


@requires_db
def test_availability_change_skips_started_shifts(world):
    """A retroactive availability change counts from the first free shift:
    the already-worked Thursday A gets no UNAVAILABLE, so the approved
    roster keeps its approval and nothing is locked."""
    client, uid, db, ids = world
    w = ids["w"]
    change = contract_body("2026-09", all_but(slot(LOCKED)))  # excludes the already-worked Thursday A
    p = _preview(client, w, change)
    assert p["retroactive"] is True and p["locked_violations"] == []
    sep = next(r for r in p["affected_rosters"] if r["month"] == "2026-09")
    assert sep["new_violations"] == [] and sep["revokes_approval"] is False

    assert _apply(client, w, change, p["fingerprint"]).status_code == 200
    roster = client.get("/api/rosters/2026-09").json()
    assert roster["status"] == "APPROVED" and roster["violations"] == []
    assert assignment_count(db, ids["sep"]) == 3

    # P1: a later version for the same month supersedes it; both stay in history.
    fix = contract_body("2026-09")
    p2 = _preview(client, w, fix)
    assert p2["locked_violations"] == [] and p2["affected_rosters"][0]["new_violations"] == []
    out = _apply(client, w, fix, p2["fingerprint"]).json()
    assert out["created"] is True and out["contract"]["version_no"] == 3

    listing = client.get(f"/api/workers/{w}/contracts").json()
    assert [(v["version_no"], v["effective_month"]) for v in listing["versions"]] == [(3, "2026-09"), (2, "2026-09"), (1, "2026-01")]
    assert listing["resolved"]["version_no"] == 3
    assert client.get(f"/api/workers/{w}/contracts?resolved_for=2026-08").json()["resolved"]["version_no"] == 1


@requires_db
def test_history_month_is_listed_but_never_revalidated_or_revoked(world):
    client, _, db, ids = world
    body = contract_body("2026-08", all_but(["MON:A"]))  # Aug 3 (Mon A) is in history
    p = _preview(client, ids["w"], body)
    months = {r["month"]: r for r in p["affected_rosters"]}
    assert set(months) == {"2026-08", "2026-09", "2026-10"}
    assert months["2026-08"]["is_history"] is True
    assert months["2026-08"]["new_violations"] == [] and months["2026-08"]["revokes_approval"] is False
    _apply(client, ids["w"], body, p["fingerprint"])
    assert roster_row(db, ids["aug"])[0] == "DRAFT" and assignment_count(db, ids["aug"]) == 1


@requires_db
def test_contract_endpoints_404_and_auth(world):
    client, _, _, ids = world
    body = contract_body("2026-09")
    assert client.post("/api/workers/9999/contracts/preview", json=body).status_code == 404
    assert client.post("/api/workers/9999/contracts", json={**body, "fingerprint": "x"}).status_code == 404
    assert client.post(f"/api/workers/{ids['w']}/contracts", json=body).status_code == 422  # fingerprint required


@requires_db
def test_availability_change_during_the_running_shift(world):
    """The worker reports, mid-shift, that this weekday's B no longer works
    for them: the running shift (15/09 B, started 08:00) is not flagged,
    the same slot next week is."""
    client, uid, db, ids = world
    w = ids["w"]
    running, next_week = (date(2026, 9, 15), "B"), (date(2026, 9, 22), "B")
    insert_assignment(db, ids["sep"], w, *running, "GENERAL_GUARD")
    change = contract_body("2026-09", all_but(slot(running)))
    p = _preview(client, w, change)
    assert p["locked_violations"] == [] and p["affected_rosters"][0]["new_violations"] == []
    assert _apply(client, w, change, p["fingerprint"]).status_code == 200
    assert client.get("/api/rosters/2026-09").json()["violations"] == []

    insert_assignment(db, ids["sep"], w, *next_week, "GENERAL_GUARD")
    roster = client.get("/api/rosters/2026-09").json()
    assert [(v["code"], v["key"][1]) for v in roster["violations"]] == [("UNAVAILABLE", "2026-09-22")]


@requires_db
def test_max_hours_change_splits_worked_and_fixable_hours(world):
    """Hours already worked above a lowered maximum are a warning; the
    part the free shifts can still fix stays a MAX_HOURS violation."""
    client, uid, db, ids = world
    w, other = ids["w"], ids["other"]
    # W: 10/09 A worked (8 h), 20/09 A upcoming (8 h). Max 0: 8 h over already, 8 h fixable.
    p = _preview(client, w, contract_body("2026-09", max_hours=0))
    sep = p["affected_rosters"][0]
    assert [(v["code"], v["magnitude"]) for v in sep["new_violations"]] == [("MAX_HOURS", 8)]
    assert p["locked_violations"] == [] and sep["revokes_approval"] is True
    assert _apply(client, w, contract_body("2026-09", max_hours=0), p["fingerprint"]).status_code == 200
    roster = client.get("/api/rosters/2026-09").json()
    [v] = roster["violations"]
    assert (v["code"], v["magnitude"]) == ("MAX_HOURS", 8)
    assert [(a["date"], a["shift"]) for a in v["assignments"]] == [("2026-09-20", "A")]
    assert roster["hour_overages"] == [{"worker_id": str(w), "max_hours": 0, "worked_hours": 8, "over_hours": 8}]


@requires_db
def test_max_hours_below_worked_hours_only_warns(planner, db, freeze):
    freeze(NOW)
    client, uid = planner
    ids = seed(db, uid, sep_status="APPROVED")
    other = ids["other"]  # only the worked 10/09 A in September
    body = contract_body("2026-09", max_hours=0)
    p = _preview(client, other, body)
    assert p["locked_violations"] == [] and p["affected_rosters"][0]["new_violations"] == []
    assert p["affected_rosters"][0]["revokes_approval"] is False
    assert _apply(client, other, body, p["fingerprint"]).status_code == 200
    roster = client.get("/api/rosters/2026-09").json()
    assert roster["status"] == "APPROVED" and roster["violations"] == []
    assert roster["hour_overages"] == [{"worker_id": str(other), "max_hours": 0, "worked_hours": 8, "over_hours": 8}]
