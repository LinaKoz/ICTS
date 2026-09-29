"""API-surface checks added at integration: strict `YYYY-MM` month, the
worker-name lookup, last-edited metadata, the single §6 error shape for
request-validation errors, and the error/logout responses in OpenAPI."""
from __future__ import annotations

from datetime import date

import pytest

from tests.conftest import requires_db
from tests.rosters.helpers import insert_contract, insert_roster, insert_worker

BAD_MONTHS = ["2026-3", "2026-13", "2026-00", "202603", "2026-03-01", "abcd-ef", "2026-03 "]


@requires_db
@pytest.mark.parametrize("month", BAD_MONTHS)
def test_bad_month_is_422_in_the_error_shape(planner, month):
    client, _ = planner
    for method, suffix, kwargs in (
        ("get", "", {}),
        ("post", "/generate", {"json": {}}),
        ("post", "/save", {"json": {"assignments": [], "fingerprint": "x"}}),
    ):
        resp = getattr(client, method)(f"/api/rosters/{month}{suffix}", **kwargs)
        assert resp.status_code == 422, (month, suffix, resp.text)
        body = resp.json()
        assert body["error"]["code"] == "VALIDATION_ERROR" and "detail" not in body


@requires_db
def test_body_validation_error_uses_the_error_shape(planner):
    client, _ = planner
    resp = client.post("/api/rosters/2099-01/generate", json={"forbid_adjacent_shifts": "maybe"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
    assert resp.json()["error"]["details"][0]["loc"][-1] == "forbid_adjacent_shifts"


def test_parse_month_is_strict():
    from app.errors import BadRequestError
    from app.rosters.problem_builder import parse_month

    assert parse_month("2026-03") == date(2026, 3, 1)
    for bad in BAD_MONTHS:
        with pytest.raises(BadRequestError):
            parse_month(bad)


@requires_db
def test_get_roster_has_worker_names_and_last_edited(planner, db):
    client, user_id = planner
    wid = insert_worker(db, "111111118", full_name="Dana Levi")
    insert_contract(db, wid, user_id, effective_month=date(2026, 1, 1))
    insert_roster(db, date(2099, 1, 1), user_id)

    body = client.get("/api/rosters/2099-01").json()
    assert {w["worker_id"]: w["full_name"] for w in body["workers"]} == {str(wid): "Dana Levi"}
    assert body["updated_by"] == "planner"  # the fixture's display_name
    assert body["updated_at"]


def test_openapi_documents_errors_and_logout():
    from app.main import app

    spec = app.openapi()
    get = spec["paths"]["/api/rosters/{month}"]["get"]
    assert {"401", "403", "404", "422"} <= set(get["responses"])
    ok_schema = spec["paths"]["/api/rosters/{month}/generate"]["post"]["responses"]
    assert {"401", "403", "422", "429", "500"} <= set(ok_schema)
    for status in ("401", "422"):
        assert ok_schema[status]["content"]["application/json"]["schema"]["$ref"].endswith("/ErrorOut")
    save = spec["paths"]["/api/rosters/{month}/save"]["post"]["responses"]
    assert {"400", "409", "422"} <= set(save)
    logout = spec["paths"]["/api/auth/logout"]["post"]["responses"]["200"]
    assert logout["content"]["application/json"]["schema"]["$ref"].endswith("/LogoutOut")
    month = spec["paths"]["/api/rosters/{month}"]["get"]["parameters"][0]
    assert month["schema"]["pattern"] == r"^[0-9]{4}-(0[1-9]|1[0-2])$"
    # FastAPI's default validation body must not leak into the contract
    assert "HTTPValidationError" not in spec["components"]["schemas"]


def test_committed_openapi_is_current():
    import json
    import pathlib

    from app.main import app

    committed = pathlib.Path(__file__).resolve().parents[2] / "openapi.json"
    assert json.loads(committed.read_text()) == json.loads(json.dumps(app.openapi())), (
        "backend/openapi.json is stale; run python scripts/export_openapi.py"
    )
