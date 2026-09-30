"""Origin check for state-changing requests (app/csrf.py)."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.csrf import OriginCheckMiddleware


@pytest.fixture()
def client():
    app = FastAPI()
    app.add_middleware(OriginCheckMiddleware)

    @app.post("/w")
    def write() -> dict:
        return {"ok": True}

    @app.get("/r")
    def read() -> dict:
        return {"ok": True}

    return TestClient(app, base_url="http://localhost:8080")


def test_post_without_origin_passes(client):
    assert client.post("/w").status_code == 200


def test_post_same_origin_passes(client):
    assert client.post("/w", headers={"origin": "http://localhost:8080"}).status_code == 200


@pytest.mark.parametrize(
    "origin", ["http://evil.example", "http://localhost:3000", "http://localhost", "null"]
)
def test_post_cross_origin_is_403(client, origin):
    resp = client.post("/w", headers={"origin": origin})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "CSRF_REJECTED"


def test_get_is_never_checked(client):
    assert client.get("/r", headers={"origin": "http://evil.example"}).status_code == 200
