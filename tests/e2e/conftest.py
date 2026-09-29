"""End-to-end fixtures: httpx against a running stack (docker compose up).

The base URL comes from `E2E_BASE_URL` (default http://localhost:8080, the
nginx frontend that proxies /api). Passwords come from `PLANNER_PASSWORD` and
`MANAGER_PASSWORD` (defaults: the demo values of .env.example). When the stack
is not reachable the whole suite is skipped with a message saying how to start
it; nothing here starts or stops containers.

The flows in `test_flows.py` are ordered and share state (one future roster),
and expect a clean database (`docker compose down -v` first).
"""
from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

BASE_URL = os.environ.get("E2E_BASE_URL", "http://localhost:8080").rstrip("/")
PLANNER_PASSWORD = os.environ.get("PLANNER_PASSWORD", "planner-demo")
MANAGER_PASSWORD = os.environ.get("MANAGER_PASSWORD", "manager-demo")


def _stack_reachable() -> str | None:
    """Returns None when the stack answers /api/health, else the reason."""
    try:
        r = httpx.get(f"{BASE_URL}/api/health", timeout=5)
    except httpx.HTTPError as exc:
        return f"{type(exc).__name__}: {exc}"
    return None if r.status_code == 200 else f"/api/health returned HTTP {r.status_code}"


def pytest_collection_modifyitems(config, items):
    reason = _stack_reachable()
    if reason is None:
        return
    skip = pytest.mark.skip(
        reason=(
            f"e2e stack not reachable at {BASE_URL} ({reason}). Start it with "
            "`docker compose up -d --build` (or set E2E_BASE_URL) and re-run."
        )
    )
    for item in items:
        item.add_marker(skip)


def month_offset(offset: int) -> str:
    """YYYY-MM for the current Israel month plus `offset` months."""
    now = datetime.now(ZoneInfo("Asia/Jerusalem"))
    index = now.year * 12 + (now.month - 1) + offset
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def _login(username: str, password: str) -> httpx.Client:
    client = httpx.Client(base_url=BASE_URL, timeout=120)
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, f"login as {username} failed: {r.status_code} {r.text}"
    return client


@pytest.fixture(scope="session")
def planner():
    c = _login("planner", PLANNER_PASSWORD)
    yield c
    c.close()


@pytest.fixture(scope="session")
def manager():
    c = _login("manager", MANAGER_PASSWORD)
    yield c
    c.close()


@pytest.fixture(scope="session")
def anon():
    with httpx.Client(base_url=BASE_URL, timeout=30) as c:
        yield c


def _free_months(client: httpx.Client) -> tuple[str, str]:
    """The first future month pair with no roster in it or next to it.

    Earlier runs leave their rosters behind (there is no delete endpoint), so
    each run moves on to months nobody has used. The window is k-1..k+3: the
    two months the flows use (k, k+2) and the months adjacent to them, so a
    leftover neighbour can never change a fingerprint.
    """
    for k in range(2, 62):
        window = [month_offset(k + i) for i in range(-1, 4)]
        statuses = [client.get(f"/api/rosters/{m}").status_code for m in window]
        if all(code == 404 for code in statuses):
            return month_offset(k), month_offset(k + 2)
    pytest.fail("no free block of future months left in 5 years; reset with `docker compose down -v`")


@pytest.fixture(scope="session")
def state(planner) -> dict:
    """Mutable state shared by the ordered flows."""
    month, stale_month = _free_months(planner)
    return {"month": month, "stale_month": stale_month}
