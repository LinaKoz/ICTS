"""§8 T5: worker CRUD, checksum 422, 409 on in-use delete, version conflict."""
from __future__ import annotations

from datetime import date

from tests.conftest import requires_db
from tests.rosters.helpers import insert_assignment, insert_contract, insert_roster, insert_worker

VALID = {"national_id": "111111118", "full_name": "  Alice Guard ", "role": "GENERAL_GUARD"}


def _create(client, **over):
    return client.post("/api/workers", json={**VALID, **over})


@requires_db
def test_requires_login(db):
    from fastapi.testclient import TestClient

    from tests.workers.conftest import make_app

    with TestClient(make_app()) as anon:
        assert anon.get("/api/workers").status_code == 401
        assert anon.post("/api/workers", json=VALID).status_code == 401


@requires_db
def test_create_get_list_filter(planner):
    client, _ = planner
    resp = _create(client)
    assert resp.status_code == 201
    w = resp.json()
    assert (w["national_id"], w["full_name"], w["status"], w["row_version"]) == ("111111118", "Alice Guard", "ACTIVE", 1)
    assert w["current_contract"] is None
    assert _create(client, national_id="222222226", full_name="Bob Screener", role="SCREENER", status="INACTIVE").status_code == 201

    detail = client.get(f"/api/workers/{w['id']}").json()
    assert detail["field_history"] == [] and detail["id"] == w["id"]

    assert [x["full_name"] for x in client.get("/api/workers").json()] == ["Alice Guard", "Bob Screener"]
    assert [x["full_name"] for x in client.get("/api/workers?status=INACTIVE").json()] == ["Bob Screener"]
    assert [x["full_name"] for x in client.get("/api/workers?role=GENERAL_GUARD").json()] == ["Alice Guard"]
    assert [x["full_name"] for x in client.get("/api/workers?q=2222").json()] == ["Bob Screener"]
    assert [x["full_name"] for x in client.get("/api/workers?q=alice").json()] == ["Alice Guard"]
    assert client.get("/api/workers/9999").status_code == 404
    assert client.get("/api/workers?role=NOPE").status_code == 422


@requires_db
def test_create_validation_errors_are_inline_422s(planner):
    client, _ = planner
    bad = _create(client, national_id="111111111")  # 9 digits, bad checksum
    assert bad.status_code == 422
    body = bad.json()["error"]
    assert body["code"] == "VALIDATION_ERROR"
    assert body["details"][0]["loc"] == ["body", "national_id"] and "checksum" in body["details"][0]["message"]

    short = _create(client, national_id="12345674")
    assert short.status_code == 422 and "leading zeros" in short.json()["error"]["details"][0]["message"]

    assert _create(client, full_name="   ").status_code == 422
    assert _create(client, role="BOSS").status_code == 422

    assert _create(client).status_code == 201
    dup = _create(client)
    assert dup.status_code == 422
    assert dup.json()["error"]["details"][0]["type"] == "duplicate"


@requires_db
def test_patch_version_conflict_and_noop(planner):
    client, _ = planner
    w = _create(client).json()
    url = f"/api/workers/{w['id']}"

    ok = client.patch(url, json={"expected_version": 1, "full_name": "Alice G."})
    assert ok.status_code == 200 and ok.json()["changed"] is True
    assert ok.json()["worker"]["row_version"] == 2 and ok.json()["worker"]["full_name"] == "Alice G."

    stale = client.patch(url, json={"expected_version": 1, "full_name": "Other"})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "VERSION_CONFLICT"
    assert stale.json()["error"]["details"] == {"current_version": 2}
    assert client.get(url).json()["full_name"] == "Alice G."

    same = client.patch(url, json={"expected_version": 2, "full_name": "Alice G.", "status": "ACTIVE"})
    assert same.status_code == 200 and same.json()["changed"] is False
    assert same.json()["worker"]["row_version"] == 2  # P5: no update, no bump
    assert client.get(url).json()["field_history"] == []

    assert client.patch(url, json={"full_name": "x"}).status_code == 422  # expected_version is required
    assert client.patch("/api/workers/9999", json={"expected_version": 1}).status_code == 404


@requires_db
def test_patch_national_id_checks(planner):
    client, _ = planner
    a = _create(client).json()
    b = _create(client, national_id="222222226", full_name="B").json()
    url = f"/api/workers/{b['id']}"
    r = client.patch(url, json={"expected_version": 1, "national_id": "111111118"})
    assert r.status_code == 422 and r.json()["error"]["details"][0]["type"] == "duplicate"
    r = client.patch(url, json={"expected_version": 1, "national_id": "123456789"})
    assert r.status_code == 422 and "checksum" in r.json()["error"]["details"][0]["message"]
    r = client.patch(url, json={"expected_version": 1, "national_id": "333333334"})
    assert r.status_code == 200 and r.json()["worker"]["national_id"] == "333333334"
    assert a["id"] != b["id"]


@requires_db
def test_delete_unused_worker(planner):
    client, _ = planner
    w = _create(client).json()
    assert client.delete(f"/api/workers/{w['id']}").status_code == 204
    assert client.get(f"/api/workers/{w['id']}").status_code == 404
    assert client.delete(f"/api/workers/{w['id']}").status_code == 404


@requires_db
def test_delete_in_use_is_409_worker_in_use(planner, db):
    client, uid = planner
    with_contract = insert_worker(db, "111111118", "HasContract")
    insert_contract(db, with_contract, uid)
    r = client.delete(f"/api/workers/{with_contract}")
    assert r.status_code == 409 and r.json()["error"]["code"] == "WORKER_IN_USE"
    assert r.json()["error"]["details"]["contract_versions"] == 1

    with_assignment = insert_worker(db, "222222226", "Assigned")
    roster = insert_roster(db, date(2099, 1, 1), uid)
    insert_assignment(db, roster, with_assignment, date(2099, 1, 2), "A", "GENERAL_GUARD")
    r = client.delete(f"/api/workers/{with_assignment}")
    assert r.status_code == 409 and r.json()["error"]["details"]["assignments"] == 1

    # A status change leaves history, which also blocks deletion (FK RESTRICT, history preserved).
    w = _create(client, national_id="333333334", full_name="Changed").json()
    assert client.patch(f"/api/workers/{w['id']}", json={"expected_version": 1, "status": "INACTIVE"}).status_code == 200
    r = client.delete(f"/api/workers/{w['id']}")
    assert r.status_code == 409 and r.json()["error"]["details"]["history_entries"] == 1
    assert client.get(f"/api/workers/{w['id']}").status_code == 200  # still there
