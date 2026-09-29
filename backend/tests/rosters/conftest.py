"""Fixtures for the T3 roster API tests: a lifespan-less app (routers +
error handlers only), a logged-in client, a frozen Israel clock, and an
in-process stand-in for `engine_pool.submit` (no spawn) so `solve()` and
its `_run_cp_sat` seam can be exercised and mocked."""
from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.security import hash_password
from app.errors import register_exception_handlers

TZ = ZoneInfo("Asia/Jerusalem")
PASSWORD = "s3cret-pw"


def make_app() -> FastAPI:
    from app.auth.router import router as auth_router
    from app.rosters.edits import router as edits_router
    from app.rosters.router import router as rosters_router

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(auth_router)
    app.include_router(rosters_router)
    app.include_router(edits_router)
    return app


def seed_login_user(db, username: str, app_role: str) -> int:
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO users (username, display_name, password_hash, app_role) VALUES (%s, %s, %s, %s) RETURNING id",
            (username, username, hash_password(PASSWORD), app_role),
        )
        return cur.fetchone()[0]


@pytest.fixture()
def planner(db):
    """(client, user_id) logged in as PLANNER; one event loop for the whole test."""
    user_id = seed_login_user(db, "planner", "PLANNER")
    with TestClient(make_app()) as client:
        resp = client.post("/api/auth/login", json={"username": "planner", "password": PASSWORD})
        assert resp.status_code == 200
        yield client, user_id


@pytest.fixture()
def freeze(monkeypatch):
    """`freeze(datetime)` pins `now_israel()` everywhere the roster code reads it."""

    def _freeze(now: datetime) -> datetime:
        now = now.replace(tzinfo=TZ) if now.tzinfo is None else now
        for target in ("app.rosters.problem_builder.now_israel", "app.rosters.evaluation.now_israel"):
            monkeypatch.setattr(target, lambda now=now: now)
        return now

    return _freeze


@pytest.fixture()
def inline_pool(monkeypatch):
    """Replaces `engine_pool.submit` with an in-process call in a thread,
    and resets the busy guard around the test."""
    from app.engine_pool import engine_pool

    async def submit(fn, *args):
        return await asyncio.to_thread(fn, *args)

    monkeypatch.setattr(engine_pool, "submit", submit)
    engine_pool._generating = False
    yield engine_pool
    engine_pool._generating = False


@pytest.fixture()
def fingerprint_for():
    """`fingerprint_for(month, forbid)` computed the way generate/save do."""
    from app.db import async_session_factory
    from app.rosters.problem_builder import build_problem, compute_fingerprint

    def _fp(month, forbid: bool = False) -> str:
        async def run():
            async with async_session_factory() as session:
                built = await build_problem(session, month, forbid)
                return await compute_fingerprint(session, built)

        return asyncio.run(run())

    return _fp
