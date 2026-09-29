"""§8 T8: automatic invalidation of an approval through CONTRACT_CHANGE and
WORKER_CHANGE, end to end: approve through the API, change the data through
the T5 endpoints, read the audit trail, and see that a roster left with hard
violations can no longer be approved (P7, P11). EDIT and REGENERATE are
covered in tests/rosters/test_approval.py."""
from __future__ import annotations

import pytest

from tests.conftest import requires_db
from tests.workers.conftest import all_but, contract_body
from tests.workers.scenario import FREE, NOW, roster_row, seed, slot


@pytest.fixture()
def world(duo, db, freeze):
    freeze(NOW)
    return duo, db, seed(db, duo.planner_id, sep_status="DRAFT")


def _approve_sep(client, version=1):
    p = client.get("/api/rosters/2026-09/approval-preview").json()
    assert p["hard_violations"] == []
    return client.post(
        "/api/rosters/2026-09/approve",
        json={
            "expected_version": version,
            "acknowledge_warnings": True,
            "reason": "Known gaps, agreed with ops",
            "warnings_fingerprint": p["warnings_fingerprint"],
        },
    )


def _history(client):
    return client.get("/api/rosters/2026-09").json()["approval_history"]


@requires_db
def test_contract_change_revokes_with_the_contract_version_reference(world):
    duo, db, ids = world
    w = ids["w"]
    assert _approve_sep(duo.as_("manager")).status_code == 200
    assert roster_row(db, ids["sep"]) == ("APPROVED", 1)

    planner = duo.as_("planner")
    body = contract_body("2026-09", all_but(slot(FREE)))  # W becomes unavailable for the upcoming shift
    fp = planner.post(f"/api/workers/{w}/contracts/preview", json=body).json()["fingerprint"]
    out = planner.post(f"/api/workers/{w}/contracts", json={**body, "fingerprint": fp})
    assert out.status_code == 200 and out.json()["revoked_rosters"] == ["2026-09"], out.text
    version_id = out.json()["contract"]["id"]

    (ev,) = _history(planner)
    assert (ev["revoke_cause"], ev["revoke_ref"], ev["revoked_by"]) == ("CONTRACT_CHANGE", f"contract_version:{version_id}", "planner")
    assert ev["approved_by"] == "manager" and ev["roster_version"] == 1 and ev["reason"] == "Known gaps, agreed with ops"
    assert ev["acknowledged_warnings"]["coverage_gaps"] and ev["revoked_at"] is not None
    status, version = roster_row(db, ids["sep"])
    assert status == "DRAFT" and version == 2  # the revoke bumped the version (fingerprint input)

    # A hard violation remains: no approval, whatever is acknowledged.
    manager = duo.as_("manager")
    p = manager.get("/api/rosters/2026-09/approval-preview").json()
    assert [v["code"] for v in p["hard_violations"]] == ["UNAVAILABLE"] and p["can_approve"] is False
    resp = manager.post(
        "/api/rosters/2026-09/approve",
        json={"expected_version": 2, "acknowledge_warnings": True, "reason": "x", "warnings_fingerprint": p["warnings_fingerprint"]},
    )
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "HARD_VIOLATIONS"

    # A same-month correcting version (P1) clears the violation; approving again adds a second history entry.
    fix = contract_body("2026-09", all_but([]))
    fp = planner.post(f"/api/workers/{w}/contracts/preview", json=fix).json()["fingerprint"]
    assert planner.post(f"/api/workers/{w}/contracts", json={**fix, "fingerprint": fp}).status_code == 200
    _, version = roster_row(db, ids["sep"])
    assert _approve_sep(duo.as_("manager"), version).status_code == 200
    first, second = _history(duo.client)
    assert first["revoke_cause"] == "CONTRACT_CHANGE" and second["revoke_cause"] is None
    assert second["roster_version"] == version > first["roster_version"]


@requires_db
def test_worker_change_revokes_with_the_worker_reference(world):
    duo, db, ids = world
    w = ids["w"]
    assert _approve_sep(duo.as_("manager")).status_code == 200

    planner = duo.as_("planner")
    r = planner.patch(f"/api/workers/{w}", json={"expected_version": 1, "status": "INACTIVE"})
    assert r.status_code == 200 and r.json()["invalidates_approved"] is True, r.text

    (ev,) = _history(planner)
    assert (ev["revoke_cause"], ev["revoke_ref"], ev["revoked_by"]) == ("WORKER_CHANGE", f"worker:{w}", "planner")
    assert roster_row(db, ids["sep"])[0] == "DRAFT"
    p = duo.as_("manager").get("/api/rosters/2026-09/approval-preview").json()
    assert [v["code"] for v in p["hard_violations"]] == ["INACTIVE_WORKER"] and p["can_approve"] is False


@requires_db
def test_a_change_that_adds_no_violation_leaves_the_approval_in_place(world):
    duo, db, ids = world
    assert _approve_sep(duo.as_("manager")).status_code == 200
    planner = duo.as_("planner")
    body = contract_body("2026-09", rate="55.00")
    fp = planner.post(f"/api/workers/{ids['w']}/contracts/preview", json=body).json()["fingerprint"]
    assert planner.post(f"/api/workers/{ids['w']}/contracts", json={**body, "fingerprint": fp}).status_code == 200
    (ev,) = _history(planner)
    assert ev["revoke_cause"] is None and roster_row(db, ids["sep"])[0] == "APPROVED"


@requires_db
def test_csv_import_confirm_revokes_with_the_import_reference(world):
    """CONTRACT_CHANGE through a confirmed CSV import: the audit trail points at the import."""
    from tests.csvio.helpers import FULL, csv_text, row
    from tests.workers.scenario import FREE, slot

    duo, db, ids = world
    assert _approve_sep(duo.as_("manager")).status_code == 200

    planner = duo.as_("planner")
    blocked = set(slot(FREE))  # W becomes unavailable for the upcoming September shift
    availability = "|".join(
        f"{d}:{''.join(s for s in 'ABC' if f'{d}:{s}' not in blocked)}"
        for d in ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
    )
    data = csv_text(FULL, [row("111111118", "Alice Guard", month="2026-09", av=availability)])
    prev = planner.post("/api/imports", content=data, headers={"content-type": "text/csv"})
    assert prev.status_code == 201, prev.text
    import_id = prev.json()["id"]
    assert prev.json()["invalidates_approved"] is True
    done = planner.post(f"/api/imports/{import_id}/confirm", json={"decisions": {}})
    assert done.status_code == 200 and done.json()["result"]["revoked_rosters"] == ["2026-09"], done.text

    (ev,) = _history(planner)
    assert (ev["revoke_cause"], ev["revoke_ref"], ev["revoked_by"]) == ("CONTRACT_CHANGE", f"import:{import_id}", "planner")
    assert roster_row(db, ids["sep"])[0] == "DRAFT"
    p = duo.as_("manager").get("/api/rosters/2026-09/approval-preview").json()
    assert [v["code"] for v in p["hard_violations"]] == ["UNAVAILABLE"] and p["can_approve"] is False
