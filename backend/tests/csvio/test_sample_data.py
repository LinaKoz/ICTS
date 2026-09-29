"""§8 T6 / D5 sample data: `sample-data/workers.csv` (23 workers, 9 GG / 9 SCR / 5 SUP)
is imported through the API and a 28-, 30- and 31-day month is generated from it with
the adjacency rule off and on: OPTIMAL, 0 gaps, 0 shortfalls, and an independent check
of every hard constraint. The separate shortage fixture yields proven supervisor gaps."""
from __future__ import annotations

import pathlib
from collections import Counter, defaultdict
from datetime import date

import pytest

from app.csvio.parse import parse_csv
from tests.conftest import requires_db
from tests.csvio.conftest import post_csv
from tests.rosters.helpers import insert_approval
from tests.workers.scenario import NOW

SAMPLE = pathlib.Path(__file__).resolve().parents[3] / "sample-data"
MONTHS = [("2027-02", 28), ("2026-11", 30), ("2026-12", 31)]  # Sep 2026 is "now"; all three are future months
SLOTS_PER_DAY = 15
DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
ORDER = {"A": 0, "B": 1, "C": 2}


def parsed_rows(name: str):
    parsed = parse_csv((SAMPLE / name).read_bytes(), date(2026, 9, 1))
    assert all(not r.errors for r in parsed.rows), [(r.line, r.errors) for r in parsed.rows if r.errors]
    return parsed.rows


def import_file(client, name: str) -> dict:
    prev = post_csv(client, (SAMPLE / name).read_bytes()).json()
    assert prev["counts"]["invalid"] == 0, [r for r in prev["rows"] if r["errors"]]
    r = client.post(f"/api/imports/{prev['id']}/confirm", json={"decisions": {}})
    assert r.status_code == 200, r.text
    return prev


@pytest.fixture()
def world(planner, db, freeze, inline_pool):
    freeze(NOW)
    client, uid = planner
    return client, uid, db


def generate(client, month: str, adjacent: bool) -> dict:
    r = client.post(f"/api/rosters/{month}/generate", json={"forbid_adjacent_shifts": adjacent})
    assert r.status_code == 200, r.text
    return r.json()


@requires_db
@pytest.mark.parametrize("adjacent", [False, True])
def test_workers_csv_generates_every_month_length_with_no_gaps(world, adjacent):
    client, uid, db = world
    rows = parsed_rows("workers.csv")
    assert len(rows) == 23
    assert Counter(r.role for r in rows) == {"GENERAL_GUARD": 9, "SCREENER": 9, "SUPERVISOR": 5}
    assert len({r.national_id for r in rows}) == 23 and rows[0].national_id == "012345674"  # leading zero kept

    prev = import_file(client, "workers.csv")
    assert prev["counts"] == {"new": 23, "changed": 0, "unchanged": 0, "invalid": 0}
    ids = {w["national_id"]: w["id"] for w in client.get("/api/workers").json()}
    assert len(ids) == 23
    by_worker_id = {str(ids[r.national_id]): r for r in rows}

    for month, days in MONTHS:
        out = generate(client, month, adjacent)
        assert out["outcome"] == "solved"
        assert out["coverage"]["status"] == "OPTIMAL" and out["coverage"]["total_uncovered"] == 0
        assert out["min_hours"]["status"] == "OPTIMAL" and out["min_hours"]["total_shortfall"] == 0
        assert out["lexicographically_optimal"] is True
        assert sum(g["missing"] for g in out["coverage_gaps"]) == 0 and out["hour_shortfalls"] == []
        assert out["preexisting_violations"] == []

        assignments = out["assignments"]
        assert len(assignments) == days * SLOTS_PER_DAY
        per_worker = defaultdict(list)
        slots = Counter()
        for a in assignments:
            per_worker[a["worker_id"]].append((date.fromisoformat(a["date"]), a["shift"]))
            slots[(a["date"], a["shift"], a["role"])] += 1
            w = by_worker_id[a["worker_id"]]
            assert w.role == a["role"]  # slot role = worker role
            d = date.fromisoformat(a["date"])
            assert f"{DAYS[d.weekday()]}:{a['shift']}" in w.contract.availability  # availability
        for (d, s, role), n in slots.items():
            assert n == (1 if role == "SUPERVISOR" else 2)  # exactly the demand
        for wid, items in per_worker.items():
            w = by_worker_id[wid]
            assert len(items) * 8 <= w.contract.max_hours  # max hours
            assert len(set(items)) == len(items)
            per_day = Counter(d for d, _ in items)
            assert max(per_day.values()) <= 2  # daily limit
            if adjacent:
                keys = {(d, ORDER[s]) for d, s in items}
                for d, s in keys:
                    assert (d, s + 1) not in keys or s + 1 > 2  # A->B, B->C
                for d, s in items:
                    if s == "C":
                        nxt = date.fromordinal(d.toordinal() + 1)
                        assert (nxt, "A") not in set(items)  # C -> next day A
        for r in rows:  # min hours: every worker reaches it
            got = len(per_worker.get(str(ids[r.national_id]), [])) * 8
            assert got >= r.contract.min_hours, (r.full_name, got, r.contract.min_hours)


@requires_db
def test_generated_sample_roster_saves_and_reads_back_clean(world):
    client, uid, db = world
    import_file(client, "workers.csv")
    out = generate(client, "2026-11", True)
    saved = client.post("/api/rosters/2026-11/save", json={
        "assignments": out["assignments"], "fingerprint": out["fingerprint"], "forbid_adjacent_shifts": True})
    assert saved.status_code == 200, saved.text
    got = client.get("/api/rosters/2026-11").json()
    assert got["violations"] == [] and got["hour_shortfalls"] == [] and sum(g["missing"] for g in got["coverage_gaps"]) == 0
    assert got["forbid_adjacent_shifts"] is True and len(got["assignments"]) == 30 * SLOTS_PER_DAY


@requires_db
@pytest.mark.parametrize("adjacent", [False, True])
def test_shortage_fixture_creates_proven_supervisor_gaps(world, adjacent):
    client, uid, db = world
    import_file(client, "workers.csv")
    clean = generate(client, "2026-11", adjacent)
    assert clean["coverage"]["total_uncovered"] == 0
    saved = client.post("/api/rosters/2026-11/save", json={
        "assignments": clean["assignments"], "fingerprint": clean["fingerprint"], "forbid_adjacent_shifts": adjacent})
    assert saved.status_code == 200
    with db.cursor() as cur:  # approve it (approval endpoint is T8's)
        cur.execute("SELECT id FROM rosters WHERE month = '2026-11-01'")
        rid = cur.fetchone()[0]
        cur.execute("UPDATE rosters SET status = 'APPROVED' WHERE id = %s", (rid,))
    insert_approval(db, rid, uid)

    prev = post_csv(client, (SAMPLE / "contract-changes-shortage.csv").read_bytes()).json()
    assert prev["counts"] == {"new": 0, "changed": 5, "unchanged": 0, "invalid": 0}
    assert all(r["contract_action"] == "NEW_VERSION" and r["role"] == "SUPERVISOR" for r in prev["rows"])
    assert prev["invalidates_approved"] is True  # the approved November roster loses its supervisors
    confirmed = client.post(f"/api/imports/{prev['id']}/confirm", json={"decisions": {}})
    assert confirmed.status_code == 200 and confirmed.json()["result"]["revoked_rosters"] == ["2026-11"]
    with db.cursor() as cur:
        cur.execute("SELECT revoke_cause, revoke_ref FROM roster_approvals WHERE roster_id = %s", (rid,))
        assert cur.fetchall() == [("CONTRACT_CHANGE", f"import:{prev['id']}")]

    for month, days, expected in (("2027-02", 28, 30), ("2026-11", 30, 36), ("2026-12", 31, 39)):
        out = generate(client, month, adjacent)
        assert out["outcome"] == "solved"
        assert out["coverage"]["status"] == "OPTIMAL" and out["coverage"]["total_uncovered"] == expected
        assert out["coverage"]["lower_bound"] == expected  # proven, not just found
        gaps = [g for g in out["coverage_gaps"] if g["missing"]]
        assert gaps and {g["role"] for g in gaps} == {"SUPERVISOR"}
        assert sum(g["proven_missing"] for g in gaps) > 0
        assert out["min_hours"]["total_shortfall"] == 0
