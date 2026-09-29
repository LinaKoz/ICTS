"""§8 T6 acceptance: partial success, duplicates, repeated confirm, stale,
approved-roster invalidation with the import id, decisions, worker-only rows."""
from __future__ import annotations

from datetime import date

import pytest

from tests.conftest import requires_db
from tests.csvio.conftest import count, post_csv
from tests.csvio.helpers import ALL_DAYS, FULL, csv_text, row, valid_id
from tests.rosters.helpers import insert_contract, insert_worker
from tests.workers.scenario import FREE, LOCKED, NOW, approvals, assignment_count, roster_row, seed, slot

A, B, C = valid_id(1000001), valid_id(1000002), valid_id(1000003)


@pytest.fixture()
def world(planner, db, freeze):
    freeze(NOW)
    client, uid = planner
    return client, uid, db


def confirm(client, import_id, decisions=None):
    return client.post(f"/api/imports/{import_id}/confirm", json={"decisions": decisions or {}})


def rows_by_id(preview):
    return {r["national_id"]: r for r in preview["rows"]}


def q(db, sql, *args):
    with db.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchall()


@requires_db
def test_partial_success_duplicates_and_apply(world):
    client, uid, db = world
    data = csv_text(FULL, [
        row(A, "Alice", "Guard", month="2026-10"),
        row("12345674", "Short Id"),  # ID_LENGTH
        row(B, "Bob One"), row(B, "Bob Two"),  # duplicate in file
        row(C, "Cleo", "Screener", status="Inactive", month="2026-10", av="MON:AB"),
    ])
    resp = post_csv(client, data)
    assert resp.status_code == 201, resp.text
    prev = resp.json()
    assert prev["counts"] == {"new": 2, "changed": 0, "unchanged": 0, "invalid": 3}
    rows = prev["rows"]
    assert [r["classification"] for r in rows] == ["NEW", "INVALID", "INVALID", "INVALID", "NEW"]
    assert rows[1]["errors"][0]["code"] == "ID_LENGTH"
    assert [r["errors"][0]["code"] for r in rows[2:4]] == ["DUPLICATE_IN_FILE"] * 2
    assert prev["status"] == "PENDING" and prev["default_effective_month"] == "2026-09"
    assert count(db, "workers") == 0  # preview writes nothing

    r = confirm(client, prev["id"])
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    assert (result["created_workers"], result["contract_versions_created"], result["invalid"], result["skipped"]) == (2, 2, 3, 0)
    assert q(db, "SELECT national_id, role, status FROM workers ORDER BY national_id") == [
        (A, "GENERAL_GUARD", "ACTIVE"), (C, "SCREENER", "INACTIVE")]
    versions = q(db, "SELECT effective_month, hourly_rate_ils, source, import_id, availability FROM contract_versions ORDER BY id")
    assert [(v[2], v[3]) for v in versions] == [("CSV", prev["id"])] * 2
    assert versions[1][4] == ["MON:A", "MON:B"] and versions[0][0] == date(2026, 10, 1)


@requires_db
def test_repeated_confirm_is_409_with_stored_result_and_applies_nothing_twice(world):
    client, uid, db = world
    prev = post_csv(client, csv_text(FULL, [row(A)])).json()
    first = confirm(client, prev["id"])
    assert first.status_code == 200
    second = confirm(client, prev["id"])
    assert second.status_code == 409 and second.json()["error"]["code"] == "ALREADY_CONFIRMED"
    assert second.json()["error"]["details"]["result"] == first.json()["result"]
    assert count(db, "workers") == 1 and count(db, "contract_versions") == 1
    got = client.get(f"/api/imports/{prev['id']}").json()
    assert got["status"] == "CONFIRMED" and got["result"]["result"]["created_workers"] == 1


@requires_db
def test_confirm_unknown_import_404_and_unknown_decision_422(world):
    client, _, db = world
    assert confirm(client, 999).status_code == 404
    assert client.get("/api/imports/999").status_code == 404
    prev = post_csv(client, csv_text(FULL, [row(A)])).json()
    r = confirm(client, prev["id"], {B: "SKIP"})
    assert r.status_code == 422 and count(db, "workers") == 0
    # the failed confirm rolled back the PENDING -> CONFIRMED flip
    assert q(db, "SELECT status FROM csv_imports") == [("PENDING",)]
    assert confirm(client, prev["id"]).status_code == 200


@requires_db
def test_decisions_skip_rows(world):
    client, _, db = world
    prev = post_csv(client, csv_text(FULL, [row(A, "Alice"), row(B, "Bob"), row("1", "Bad")])).json()
    r = confirm(client, prev["id"], {B: "SKIP"})
    assert r.status_code == 200
    assert r.json()["result"]["skipped"] == 1 and r.json()["result"]["created_workers"] == 1
    assert [w[0] for w in q(db, "SELECT national_id FROM workers")] == [A]


@requires_db
def test_stale_worker_edit_gives_409_nothing_applied_and_fresh_preview(world):
    client, uid, db = world
    w = client.post("/api/workers", json={"national_id": A, "full_name": "Alice", "role": "GENERAL_GUARD"}).json()
    prev = post_csv(client, csv_text(FULL, [row(A, "Alice Renamed"), row(B, "Bob")])).json()
    assert prev["counts"]["changed"] == 1 and prev["counts"]["new"] == 1
    assert client.patch(f"/api/workers/{w['id']}", json={"expected_version": 1, "full_name": "Alice Other"}).status_code == 200

    r = confirm(client, prev["id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "STALE_PREVIEW"
    fresh = r.json()["error"]["details"]["preview"]
    assert fresh["id"] != prev["id"] and fresh["status"] == "PENDING"
    assert rows_by_id(fresh)[A]["changes"][0] == {"field": "full_name", "old": "Alice Other", "new": "Alice Renamed"}
    assert q(db, "SELECT full_name FROM workers") == [("Alice Other",)]  # nothing applied (Bob not created)
    assert count(db, "contract_versions") == 0
    assert q(db, "SELECT status FROM csv_imports ORDER BY id") == [("PENDING",), ("PENDING",)]
    assert confirm(client, fresh["id"]).status_code == 200
    assert q(db, "SELECT count(*) FROM workers") == [(2,)]


@requires_db
def test_stale_when_a_new_worker_appears_or_a_roster_changes(world):
    client, uid, db = world
    prev = post_csv(client, csv_text(FULL, [row(A)])).json()
    client.post("/api/workers", json={"national_id": A, "full_name": "Sneaky", "role": "SCREENER"})
    r = confirm(client, prev["id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "STALE_PREVIEW"
    assert q(db, "SELECT full_name FROM workers") == [("Sneaky",)]

    ids = seed(db, uid)
    w = q(db, "SELECT national_id FROM workers WHERE id = %s", ids["w"])[0][0]
    prev = post_csv(client, csv_text(FULL, [row(w, "Alice Guard", month="2026-09", av=ALL_DAYS.replace("THU:ABC", "THU:BC"))])).json()
    assert prev["affected_rosters"]
    with db.cursor() as cur:  # someone edits the September roster meanwhile
        cur.execute("UPDATE rosters SET row_version = row_version + 1 WHERE id = %s", (ids["sep"],))
    r = confirm(client, prev["id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "STALE_PREVIEW"
    assert q(db, "SELECT count(*) FROM contract_versions WHERE import_id IS NOT NULL") == [(0,)]


@requires_db
def test_confirmed_import_sends_approved_roster_to_draft_with_import_ref(world):
    client, uid, db = world
    ids = seed(db, uid)  # Sep APPROVED (started LOCKED shift + upcoming FREE shift), Oct DRAFT
    nid = q(db, "SELECT national_id FROM workers WHERE id = %s", ids["w"])[0][0]
    blocked = set(slot(FREE))
    av = "|".join(f"{d}:{''.join(s for s in 'ABC' if f'{d}:{s}' not in blocked)}" for d in ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")).replace("SUN:BC", "SUN:BC")
    prev = post_csv(client, csv_text(FULL, [row(nid, "Alice Guard", month="2026-09", av=av)])).json()
    assert prev["counts"]["changed"] == 1 and rows_by_id(prev)[nid]["retroactive"] is True
    assert prev["invalidates_approved"] is True
    sep = next(r for r in prev["affected_rosters"] if r["month"] == "2026-09")
    assert sep["revokes_approval"] and [v["code"] for v in sep["new_violations"]] == ["UNAVAILABLE"]
    assert roster_row(db, ids["sep"])[0] == "APPROVED"  # preview writes nothing

    before_assignments = assignment_count(db, ids["sep"])
    r = confirm(client, prev["id"])
    assert r.status_code == 200, r.text
    assert r.json()["result"]["revoked_rosters"] == ["2026-09"] and r.json()["invalidates_approved"] is True
    assert roster_row(db, ids["sep"])[0] == "DRAFT"
    assert assignment_count(db, ids["sep"]) == before_assignments  # nothing rescheduled
    (cause, ref, revoked_by, revoked) = approvals(db, ids["sep"])[0]
    assert (cause, ref, revoked_by, revoked) == ("CONTRACT_CHANGE", f"import:{prev['id']}", uid, True)


@requires_db
def test_worker_only_import_status_change_revokes_with_worker_change(world):
    client, uid, db = world
    ids = seed(db, uid)
    nid = q(db, "SELECT national_id FROM workers WHERE id = %s", ids["w"])[0][0]
    prev = post_csv(client, csv_text(["national_id", "full_name", "role", "status"], [[nid, "Alice Guard", "guard", "Inactive"]])).json()
    assert prev["invalidates_approved"] is True and rows_by_id(prev)[nid]["contract"] is None
    assert confirm(client, prev["id"]).status_code == 200
    assert approvals(db, ids["sep"])[0][:2] == ("WORKER_CHANGE", f"import:{prev['id']}")
    assert count(db, "contract_versions") == 2  # the seed's two, no new versions
    assert q(db, "SELECT count(*) FROM worker_field_history WHERE worker_id = %s", ids["w"]) == [(1,)]


@requires_db
def test_worker_only_rows_create_worker_without_contract_and_keep_existing_contract(world):
    client, uid, db = world
    existing = insert_worker(db, A, "Alice", "GENERAL_GUARD")
    insert_contract(db, existing, uid, effective_month=date(2026, 1, 1))
    prev = post_csv(client, csv_text(["national_id", "full_name", "role"], [[A, "Alice", "Guard"], [B, "Bob", "Supervisor"]])).json()
    assert prev["counts"] == {"new": 1, "changed": 0, "unchanged": 1, "invalid": 0}
    assert rows_by_id(prev)[B]["contract"] is None and rows_by_id(prev)[B]["effective_month"] is None
    assert confirm(client, prev["id"]).status_code == 200
    assert q(db, "SELECT count(*) FROM contract_versions") == [(1,)]
    assert q(db, "SELECT role FROM workers WHERE national_id = %s", B) == [("SUPERVISOR",)]


@requires_db
def test_classification_uses_p5_and_both_availability_forms_are_unchanged(world):
    client, uid, db = world
    w = insert_worker(db, A, "Alice", "GENERAL_GUARD")
    insert_contract(db, w, uid, effective_month=date(2026, 10, 1), rate="45.50", min_hours=10, max_hours=120,
                    availability=["MON:A", "MON:C", "SUN:A", "SUN:C"])
    per_day = csv_text(FULL, [row(A, "Alice", month="2026-10", rate="45.5", lo="10", hi="120", av="SUN:CA|MON:AC")])
    brief = csv_text(["national_id", "full_name", "role", "effective_month", "hourly_rate_ils", "min_monthly_hours",
                      "max_monthly_hours", "available_days", "available_shifts"],
                     [[A, "Alice", "guard", "2026-10", "45.50", "10", "120", "Sunday|Mon", "Morning|Evening"]])
    for data in (per_day, brief):
        prev = post_csv(client, data).json()
        assert prev["counts"]["unchanged"] == 1, prev
        assert rows_by_id(prev)[A]["contract_action"] == "UNCHANGED"
    changed = post_csv(client, csv_text(FULL, [row(A, "Alice", month="2026-10", rate="46", lo="10", hi="120", av="SUN:AC|MON:AC")])).json()
    r = rows_by_id(changed)[A]
    assert r["classification"] == "CHANGED" and r["contract_action"] == "NEW_VERSION"
    assert [c["field"] for c in r["changes"]] == ["hourly_rate_ils"]
    assert r["changes"][0] == {"field": "hourly_rate_ils", "old": "45.50", "new": "46.00"}


@requires_db
def test_effective_month_default_resolved_in_preview_from_frozen_clock(world):
    client, _, db = world
    data = csv_text(["national_id", "full_name", "role", "hourly_rate_ils", "min_monthly_hours", "max_monthly_hours", "availability"],
                    [[A, "Alice", "guard", "40", "0", "100", "MON:A"]])
    prev = post_csv(client, data).json()
    assert rows_by_id(prev)[A]["effective_month"] == "2026-09" and rows_by_id(prev)[A]["status"] == "ACTIVE"
    assert confirm(client, prev["id"]).status_code == 200
    assert q(db, "SELECT effective_month FROM contract_versions") == [(date(2026, 9, 1),)]


@requires_db
def test_unknown_columns_reported_as_warning(world):
    client, _, _ = world
    prev = post_csv(client, csv_text(["national_id", "full_name", "role", "Badge"], [[A, "Alice", "guard", "x"]])).json()
    assert prev["unknown_columns"] == ["Badge"]


@requires_db
def test_meta_aliases_match_parser():
    from app.csvio.parse import HEADER_ALIASES, ROLE_ALIASES, normalize_header
    from app.routers.meta import _HEADER_ALIASES, _ROLE_ALIASES

    flat = {a: c for c, al in _HEADER_ALIASES.items() for a in al}
    assert flat == HEADER_ALIASES
    for canon, names in _ROLE_ALIASES.items():
        for n in names:
            assert ROLE_ALIASES[" ".join(n.lower().replace("-", " ").split())] == canon
    assert normalize_header(" Israeli ID ") == "national_id"
