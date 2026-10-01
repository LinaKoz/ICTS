"""Fixtures for the T5 workers/contracts/change-set tests: a lifespan-less
app (auth, rosters, workers routers), logged-in clients, a frozen Israel
clock (patched everywhere the change-set and roster code reads it), and a
small seeded month."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.errors import register_exception_handlers
from tests.rosters.conftest import PASSWORD, make_duo, seed_login_user

TZ = ZoneInfo("Asia/Jerusalem")
DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


def make_app() -> FastAPI:
    import app.models  # noqa: F401  (registers every table, as app.main does)
    from app.auth.router import router as auth_router
    from app.csvio.router import router as csv_router
    from app.rosters.approval import router as approval_router
    from app.rosters.edits import router as edits_router
    from app.rosters.router import router as rosters_router
    from app.workers.router import router as workers_router

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(auth_router)
    app.include_router(rosters_router)
    app.include_router(workers_router)
    app.include_router(edits_router)
    app.include_router(approval_router)
    app.include_router(csv_router)
    return app


@pytest.fixture()
def planner(db):
    """(client, user_id) logged in as PLANNER."""
    user_id = seed_login_user(db, "planner", "PLANNER")
    with TestClient(make_app()) as client:
        assert client.post("/api/auth/login", json={"username": "planner", "password": PASSWORD}).status_code == 200
        yield client, user_id


@pytest.fixture()
def duo(db):
    yield from make_duo(db, make_app())


@pytest.fixture()
def freeze(monkeypatch):
    """`freeze(datetime)` pins `now_israel()` for the change-set, routers and roster code."""

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


def tokens(*pairs: tuple[date, str]) -> list[str]:
    return [f"{DAYS[d.weekday()]}:{s}" for d, s in pairs]


def all_but(excluded: list[str]) -> list[str]:
    return [f"{d}:{s}" for d in DAYS for s in "ABC" if f"{d}:{s}" not in excluded]


def contract_body(effective_month: str, availability: list[str] | None = None, rate: str = "40.00", **kw) -> dict:
    return {
        "effective_month": effective_month,
        "hourly_rate_ils": rate,
        "min_hours": kw.get("min_hours", 0),
        "max_hours": kw.get("max_hours", 200),
        "availability": availability if availability is not None else all_but([]),
    }
