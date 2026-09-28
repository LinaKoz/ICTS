"""§8 T2 "Verification": login/me/logout work; `require_role` returns 403.

`test_require_role_*_no_db` exercise `require_role`'s own logic
directly (no FastAPI request cycle, no DB). The rest go through the
real HTTP endpoints against a real Postgres and are marked `@requires_db`.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.auth.models import User
from app.auth.security import hash_password
from app.auth.session import require_role
from app.errors import register_exception_handlers
from tests.conftest import requires_db


def _make_app() -> FastAPI:
    from app.auth.router import router as auth_router

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(auth_router)

    @app.get("/api/planner-only")
    async def planner_only(user: User = Depends(require_role("PLANNER"))) -> dict:
        return {"username": user.username}

    return app


def _seed_user(db, username: str, password: str, app_role: str) -> None:
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO users (username, display_name, password_hash, app_role) VALUES (%s, %s, %s, %s)",
            (username, username.title(), hash_password(password), app_role),
        )


# --- require_role, pure unit tests (no DB) ----------------------------------


def test_require_role_allows_matching_role_no_db():
    dep = require_role("PLANNER", "MANAGER")
    user = User(id=1, username="p", display_name="P", password_hash="x", app_role="PLANNER")
    result = asyncio.run(dep(user=user))
    assert result is user


def test_require_role_rejects_wrong_role_no_db():
    from app.errors import ForbiddenError

    dep = require_role("MANAGER")
    user = User(id=1, username="p", display_name="P", password_hash="x", app_role="PLANNER")
    with pytest.raises(ForbiddenError) as excinfo:
        asyncio.run(dep(user=user))
    assert excinfo.value.status_code == 403


# --- login / me / logout, against a real DB ---------------------------------


@requires_db
def test_login_me_logout_round_trip(db):
    _seed_user(db, "planner", "s3cret-pw", "PLANNER")
    client = TestClient(_make_app())

    resp = client.post("/api/auth/login", json={"username": "planner", "password": "s3cret-pw"})
    assert resp.status_code == 200
    assert resp.json()["username"] == "planner"
    assert resp.json()["app_role"] == "PLANNER"
    assert "session" in resp.cookies

    resp = client.get("/api/auth/me")
    assert resp.status_code == 200
    assert resp.json()["username"] == "planner"

    resp = client.post("/api/auth/logout")
    assert resp.status_code == 200

    resp = client.get("/api/auth/me")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHORIZED"


@requires_db
def test_login_wrong_password_rejected(db):
    _seed_user(db, "planner", "s3cret-pw", "PLANNER")
    client = TestClient(_make_app())
    resp = client.post("/api/auth/login", json={"username": "planner", "password": "wrong"})
    assert resp.status_code == 401


@requires_db
def test_login_unknown_user_rejected(db):
    client = TestClient(_make_app())
    resp = client.post("/api/auth/login", json={"username": "nobody", "password": "x"})
    assert resp.status_code == 401


@requires_db
def test_me_without_cookie_is_401(db):
    client = TestClient(_make_app())
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


@requires_db
def test_require_role_403_over_http(db):
    _seed_user(db, "manager", "s3cret-pw", "MANAGER")
    client = TestClient(_make_app())
    client.post("/api/auth/login", json={"username": "manager", "password": "s3cret-pw"})

    resp = client.get("/api/planner-only")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


@requires_db
def test_require_role_200_for_matching_role_over_http(db):
    _seed_user(db, "planner", "s3cret-pw", "PLANNER")
    client = TestClient(_make_app())
    client.post("/api/auth/login", json={"username": "planner", "password": "s3cret-pw"})

    resp = client.get("/api/planner-only")
    assert resp.status_code == 200
    assert resp.json()["username"] == "planner"
