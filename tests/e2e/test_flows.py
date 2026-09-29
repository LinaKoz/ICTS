"""Scripted end-to-end flows against the running stack (see conftest.py).

The tests are ordered and share state: sample import, one future month that
is generated, saved, approved, edited, revoked and re-approved, and the error
shapes. Run them in file order. They can be repeated on the same database:
each run picks future months that hold no roster yet.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path

import httpx
import pytest

SAMPLE_CSV = Path(__file__).resolve().parents[2] / "sample-data" / "workers.csv"
CSV_HEADERS = {"Content-Type": "text/csv"}


# ---- helpers -----------------------------------------------------------------


def error_of(r: httpx.Response, status: int, code: str) -> dict:
    """Asserts the one API error shape and returns its `error` object."""
    assert r.status_code == status, f"expected {status} {code}, got {r.status_code}: {r.text}"
    body = r.json()
    assert set(body) == {"error"}, body
    err = body["error"]
    assert set(err) == {"code", "message", "details"}, err
    assert err["code"] == code, err
    assert isinstance(err["message"], str) and err["message"]
    return err


def import_csv(client: httpx.Client, content: str | bytes) -> dict:
    data = content.encode("utf-8") if isinstance(content, str) else content
    r = client.post("/api/imports", content=data, headers=CSV_HEADERS)
    assert r.status_code == 201, r.text
    return r.json()


def confirm_import(client: httpx.Client, import_id: int, decisions: dict | None = None) -> dict:
    r = client.post(f"/api/imports/{import_id}/confirm", json={"decisions": decisions or {}})
    assert r.status_code == 200, r.text
    return r.json()


def get_roster(client: httpx.Client, month: str) -> dict:
    r = client.get(f"/api/rosters/{month}")
    assert r.status_code == 200, r.text
    return r.json()


def approve(manager: httpx.Client, month: str, reason: str = "e2e approval") -> dict:
    """Approves as the manager, acknowledging soft shortages when there are any."""
    preview = manager.get(f"/api/rosters/{month}/approval-preview").json()
    assert preview["hard_violations"] == [], preview["hard_violations"]
    body = {"expected_version": preview["version"], "reason": reason}
    if preview["requires_acknowledgement"]:
        body |= {"acknowledge_warnings": True, "warnings_fingerprint": preview["warnings_fingerprint"]}
    r = manager.post(f"/api/rosters/{month}/approve", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "APPROVED"
    return r.json()


def contract_input(resolved: dict, month: str, **overrides) -> dict:
    body = {
        "effective_month": month,
        "hourly_rate_ils": resolved["hourly_rate_ils"],
        "min_hours": resolved["min_hours"],
        "max_hours": resolved["max_hours"],
        "availability": resolved["availability"],
    }
    return body | overrides


def apply_contract(client: httpx.Client, worker_id: int, body: dict) -> dict:
    p = client.post(f"/api/workers/{worker_id}/contracts/preview", json=body)
    assert p.status_code == 200, p.text
    a = client.post(f"/api/workers/{worker_id}/contracts", json=body | {"fingerprint": p.json()["fingerprint"]})
    assert a.status_code == 200, a.text
    return {"preview": p.json(), "applied": a.json()}


# ---- health and auth ---------------------------------------------------------


def test_health_reports_a_running_stack(anon):
    r = anon.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_login_roles_and_unauthenticated_access(anon, planner, manager):
    assert planner.get("/api/auth/me").json()["app_role"] == "PLANNER"
    assert manager.get("/api/auth/me").json()["app_role"] == "MANAGER"
    error_of(anon.get("/api/workers"), 401, "UNAUTHORIZED")
    bad = anon.post("/api/auth/login", json={"username": "planner", "password": "wrong"})
    assert bad.status_code == 401


# ---- CSV import, export, round trip -----------------------------------------


def test_import_sample_csv_preview_then_confirm(planner):
    preview = import_csv(planner, SAMPLE_CSV.read_bytes())
    assert preview["status"] == "PENDING"
    counts = preview["counts"]
    assert len(preview["rows"]) == 23
    assert counts["invalid"] == 0
    assert counts["new"] + counts["unchanged"] == 23  # all NEW on a clean database
    before = len(planner.get("/api/workers").json())

    result = confirm_import(planner, preview["id"])["result"]
    assert result["invalid"] == 0
    assert result["created_workers"] == counts["new"]
    assert len(planner.get("/api/workers").json()) == before + counts["new"]

    # Confirming twice never applies twice.
    again = planner.post(f"/api/imports/{preview['id']}/confirm", json={"decisions": {}})
    error_of(again, 409, "ALREADY_CONFIRMED")


def test_export_and_reimport_is_all_unchanged(planner):
    r = planner.get("/api/exports/workers.csv")
    assert r.status_code == 200
    assert r.content.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM for Excel
    total = int(r.headers["X-Worker-Count"])
    assert total >= 23
    header = r.content.decode("utf-8-sig").splitlines()[0]
    assert "export_format" in header.split(",")

    preview = import_csv(planner, r.content)
    counts = preview["counts"]
    assert counts == {"new": 0, "changed": 0, "unchanged": total, "invalid": 0}, counts
    assert all(row["classification"] == "UNCHANGED" for row in preview["rows"])


# ---- roster: generate, save, read ------------------------------------------


def test_generate_a_future_month_and_save_as_draft(planner, state):
    month = state["month"]
    g = planner.post(f"/api/rosters/{month}/generate", json={})
    assert g.status_code == 200, g.text
    out = g.json()
    assert out["outcome"] == "solved"
    assert out["coverage"]["total_uncovered"] == 0 and [g for g in out["coverage_gaps"] if g["missing"] > 0] == []
    assert out["fingerprint"]
    assert out["costs"] is not None

    error_of(planner.get(f"/api/rosters/{month}"), 404, "NOT_FOUND")
    s = planner.post(
        f"/api/rosters/{month}/save",
        json={"assignments": out["assignments"], "fingerprint": out["fingerprint"], "expected_version": None},
    )
    assert s.status_code == 200, s.text
    assert s.json()["status"] == "DRAFT"

    roster = get_roster(planner, month)
    assert roster["status"] == "DRAFT" and roster["is_history"] is False
    assert roster["forbid_adjacent_shifts"] is False  # the optional rule is off by default
    assert len(roster["assignments"]) == len(out["assignments"])
    assert roster["violations"] == []
    assert roster["approval_history"] == []
    assert float(roster["costs"]["monthly_total_ils"]) > 0  # estimated cost from assigned hours and rates
    state["version"] = roster["version"]
    state["assigned_worker"] = int(roster["assignments"][0]["worker_id"])


# ---- approval, edit invalidation, suggestions ---------------------------------


def test_planner_cannot_approve_manager_can(planner, manager, state):
    month = state["month"]
    body = {"expected_version": state["version"]}
    error_of(planner.post(f"/api/rosters/{month}/approve", json=body), 403, "FORBIDDEN")
    approve(manager, month)
    roster = get_roster(manager, month)
    assert roster["status"] == "APPROVED"
    (event,) = roster["approval_history"]
    assert event["approved_by"] and event["revoked_at"] is None
    state["version"] = roster["version"]


def test_editing_an_approved_roster_revokes_it_with_cause_edit(planner, state):
    month = state["month"]
    stored = planner.get(f"/api/rosters/{month}/assignments").json()
    target = next(a for a in stored if a["role"] == "SUPERVISOR")
    body = {"expected_version": state["version"]}
    error_of(
        planner.request("DELETE", f"/api/rosters/{month}/assignments/{target['id']}", json=body),
        409,
        "APPROVED_EDIT_NOT_ACKNOWLEDGED",
    )
    r = planner.request(
        "DELETE",
        f"/api/rosters/{month}/assignments/{target['id']}",
        json=body | {"acknowledge_approved_edit": True},
    )
    assert r.status_code == 200, r.text
    assert r.json()["approval_revoked"] is True and r.json()["status"] == "DRAFT"
    state["version"] = r.json()["version"]
    state["gap"] = target

    roster = get_roster(planner, month)
    assert roster["status"] == "DRAFT"
    (event,) = roster["approval_history"]
    assert event["revoke_cause"] == "EDIT" and event["revoked_by"] and event["revoked_at"]
    assert any(
        g["missing"] > 0 and g["date"] == target["date"] and g["shift"] == target["shift"] and g["role"] == "SUPERVISOR"
        for g in roster["coverage_gaps"]
    )


def test_suggestions_for_the_gap_and_one_click_apply(planner, state):
    month, gap = state["month"], state["gap"]
    r = planner.get(
        f"/api/rosters/{month}/suggestions",
        params={"date": gap["date"], "shift": gap["shift"], "role": gap["role"]},
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["slot_state"] == "OPEN"
    assert out["candidates"], "expected at least one candidate for the open supervisor slot"
    for c in out["candidates"]:
        assert c["reasons"] and c["full_name"]
    ranks = [c["hours_below_minimum"] for c in out["candidates"]]
    assert ranks == sorted(ranks, reverse=True)  # ranked by minimum-hours deficit first

    pick = out["candidates"][0]
    add = planner.post(
        f"/api/rosters/{month}/assignments",
        json={
            "worker_id": pick["worker_id"],
            "date": gap["date"],
            "shift": gap["shift"],
            "role": gap["role"],
            "expected_version": state["version"],
        },
    )
    assert add.status_code == 200, add.text
    state["version"] = add.json()["version"]
    roster = get_roster(planner, month)
    assert not any(
        g["missing"] > 0 and g["date"] == gap["date"] and g["shift"] == gap["shift"] and g["role"] == gap["role"]
        for g in roster["coverage_gaps"]
    )


def test_reapprove_after_the_edit_keeps_the_full_audit_trail(manager, state):
    month = state["month"]
    approve(manager, month)
    roster = get_roster(manager, month)
    causes = [e["revoke_cause"] for e in roster["approval_history"]]
    assert causes == ["EDIT", None]
    state["version"] = roster["version"]


# ---- contract change through the API -----------------------------------------


def test_contract_change_revokes_the_approval_with_contract_change(planner, manager, state):
    month, wid = state["month"], state["assigned_worker"]
    resolved = planner.get(f"/api/workers/{wid}/contracts", params={"resolved_for": month}).json()["resolved"]
    state["original_contract"] = resolved

    # Cap the worker at 0 hours in this month: a hard MAX_HOURS violation.
    body = contract_input(resolved, month, min_hours=0, max_hours=0)
    result = apply_contract(planner, wid, body)
    assert result["preview"]["invalidates_approved"] is True
    applied = result["applied"]
    assert applied["created"] is True and applied["revoked_rosters"] == [month]

    roster = get_roster(planner, month)
    assert roster["status"] == "DRAFT"
    assert any(v["code"] == "MAX_HOURS" for v in roster["violations"])
    event = roster["approval_history"][-1]
    assert event["revoke_cause"] == "CONTRACT_CHANGE"
    assert event["revoke_ref"] == f"contract_version:{applied['contract']['id']}"

    # Hard violations can never be acknowledged away.
    r = manager.post(
        f"/api/rosters/{month}/approve",
        json={"expected_version": roster["version"], "acknowledge_warnings": True, "reason": "please"},
    )
    err = error_of(r, 422, "HARD_VIOLATIONS")
    assert any(v["code"] == "MAX_HOURS" for v in err["details"])

    # A same-month correcting version restores the original values; history keeps both.
    apply_contract(planner, wid, contract_input(resolved, month))
    versions = planner.get(f"/api/workers/{wid}/contracts", params={"resolved_for": month}).json()["versions"]
    assert len(versions) >= 3
    roster = get_roster(planner, month)
    assert not any(v["code"] == "MAX_HOURS" for v in roster["violations"])


# ---- CSV import that invalidates an approved roster --------------------------


def test_csv_import_revokes_the_approval_with_the_import_reference(planner, manager, state):
    month, wid = state["month"], state["assigned_worker"]
    approve(manager, month)
    assert get_roster(planner, month)["status"] == "APPROVED"

    worker = planner.get(f"/api/workers/{wid}").json()
    exported = planner.get("/api/exports/workers.csv", params={"month": month}).content.decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(exported)))
    row = next(r for r in rows if r["national_id"] == worker["national_id"])
    row |= {"effective_month": month, "min_monthly_hours": "0", "max_monthly_hours": "0"}
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(row), lineterminator="\n")
    writer.writeheader()
    writer.writerow(row)

    preview = import_csv(planner, out.getvalue())
    assert preview["counts"]["changed"] == 1 and preview["counts"]["invalid"] == 0
    assert preview["invalidates_approved"] is True
    result = confirm_import(planner, preview["id"])["result"]
    assert result["revoked_rosters"] == [month]

    roster = get_roster(planner, month)
    assert roster["status"] == "DRAFT"
    event = roster["approval_history"][-1]
    assert event["revoke_cause"] == "CONTRACT_CHANGE"
    assert event["revoke_ref"] == f"import:{preview['id']}"

    # Put the worker back the way it was.
    apply_contract(planner, wid, contract_input(state["original_contract"], month))
    assert not any(v["code"] == "MAX_HOURS" for v in get_roster(planner, month)["violations"])


# ---- error shapes -----------------------------------------------------------


def test_hard_violation_edit_returns_422_with_the_violation_list(planner, state):
    month = state["month"]
    roster = get_roster(planner, month)
    guard = next(a for a in roster["assignments"] if a["role"] == "GENERAL_GUARD")
    day = roster["assignments"][0]["date"]
    r = planner.post(
        f"/api/rosters/{month}/assignments",
        json={
            "worker_id": guard["worker_id"],
            "date": day,
            "shift": "A",
            "role": "SUPERVISOR",  # a guard in a supervisor slot
            "expected_version": roster["version"],
        },
    )
    err = error_of(r, 422, "HARD_VIOLATIONS")
    violations = err["details"]
    assert isinstance(violations, list) and violations
    assert {"code", "key", "magnitude", "assignments"} <= set(violations[0])
    assert any(v["code"] == "WRONG_ROLE" for v in violations)
    assert get_roster(planner, month)["version"] == roster["version"]  # nothing changed


def test_stale_version_and_stale_fingerprint_are_409(planner, state):
    month = state["month"]
    stored = planner.get(f"/api/rosters/{month}/assignments").json()
    r = planner.request(
        "DELETE",
        f"/api/rosters/{month}/assignments/{stored[0]['id']}",
        json={"expected_version": 1},
    )
    err = error_of(r, 409, "VERSION_CONFLICT")
    assert err["details"]["current_version"] > 1

    stale = state["stale_month"]
    g = planner.post(f"/api/rosters/{stale}/generate", json={}).json()
    assert g["outcome"] == "solved"
    wid = state["assigned_worker"]
    worker = planner.get(f"/api/workers/{wid}").json()
    renamed = planner.patch(
        f"/api/workers/{wid}", json={"expected_version": worker["row_version"], "full_name": worker["full_name"] + " X"}
    )
    assert renamed.status_code == 200, renamed.text
    try:
        s = planner.post(
            f"/api/rosters/{stale}/save",
            json={"assignments": g["assignments"], "fingerprint": g["fingerprint"], "expected_version": None},
        )
        error_of(s, 409, "STALE_PREVIEW")
    finally:
        back = planner.patch(
            f"/api/workers/{wid}",
            json={"expected_version": renamed.json()["worker"]["row_version"], "full_name": worker["full_name"]},
        )
        assert back.status_code == 200, back.text
    error_of(planner.get(f"/api/rosters/{stale}"), 404, "NOT_FOUND")  # nothing was saved


def test_import_rejects_wrong_content_type_and_missing_columns(planner):
    r = planner.post("/api/imports", json={"a": 1})
    error_of(r, 415, "UNSUPPORTED_MEDIA_TYPE")
    r = planner.post("/api/imports", content=b"foo,bar\n1,2\n", headers=CSV_HEADERS)
    err = error_of(r, 400, "MISSING_COLUMNS")
    assert err["details"]
