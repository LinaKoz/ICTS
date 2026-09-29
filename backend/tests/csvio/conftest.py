"""Fixtures for the T6 CSV API tests: an app with auth, workers, rosters and
the CSV router, a logged-in planner, and a frozen Israel clock."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.errors import register_exception_handlers
from tests.rosters.conftest import PASSWORD, seed_login_user

TZ = ZoneInfo("Asia/Jerusalem")


def make_app() -> FastAPI:
    import app.models  # noqa: F401
    from app.auth.router import router as auth_router
    from app.csvio.router import router as csv_router
    from app.rosters.router import router as rosters_router
    from app.workers.router import router as workers_router

    app = FastAPI()
    register_exception_handlers(app)
    for r in (auth_router, rosters_router, workers_router, csv_router):
        app.include_router(r)
    return app


@pytest.fixture()
def planner(db):
    user_id = seed_login_user(db, "planner", "PLANNER")
    with TestClient(make_app()) as client:
        assert client.post("/api/auth/login", json={"username": "planner", "password": PASSWORD}).status_code == 200
        yield client, user_id


@pytest.fixture()
def freeze(monkeypatch):
    def _freeze(now: datetime) -> datetime:
        now = now.replace(tzinfo=TZ) if now.tzinfo is None else now
        for target in (
            "app.rosters.problem_builder.now_israel",
            "app.rosters.evaluation.now_israel",
            "app.changes.service.now_israel",
            "app.workers.router.now_israel",
            "app.contracts.router.now_israel",
            "app.csvio.router.now_israel",
        ):
            monkeypatch.setattr(target, lambda now=now: now)
        return now

    return _freeze


def post_csv(client, data: bytes, **kw):
    return client.post("/api/imports", content=data, headers={"content-type": "text/csv"}, **kw)


def count(db, table: str) -> int:
    with db.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {table}")
        return cur.fetchone()[0]


from tests.rosters.conftest import inline_pool  # noqa: E402,F401  (fixture: in-process engine, no spawn)
