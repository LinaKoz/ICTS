"""§8 T3: generate returns each outcome type and a failure never persists;
mocked INFEASIBLE / broken pool give 500 ENGINE_ERROR with the stored
roster untouched; the busy guard gives 429 and is released after
success, error and cancellation."""
from __future__ import annotations

import asyncio
from concurrent.futures.process import BrokenProcessPool
from datetime import date

import pytest

import app.scheduling.types as T
from app.scheduling.types import RawSolve
from tests.conftest import requires_db
from tests.rosters.helpers import insert_assignment, insert_contract, insert_roster, insert_user, insert_worker

MONTH = date(2099, 1, 1)
URL = "/api/rosters/2099-01/generate"


@pytest.fixture(autouse=True)
def _fast_solver(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "solver_time_limit_s", 3.0)
    monkeypatch.setattr(settings, "num_workers", 1)


def _seed_workers(db, user_id: int) -> list[int]:
    ids = []
    for nid, role in (("111111118", "GENERAL_GUARD"), ("222222226", "SCREENER"), ("333333334", "SUPERVISOR")):
        wid = insert_worker(db, nid, role=role)
        insert_contract(db, wid, user_id, effective_month=date(2026, 1, 1), max_hours=200)
        ids.append(wid)
    return ids


def _count(db, table: str) -> int:
    with db.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {table}")
        return cur.fetchone()[0]


def test_generate_requires_login(db):
    from fastapi.testclient import TestClient

    from tests.rosters.conftest import make_app

    with TestClient(make_app()) as client:
        assert client.post(URL, json={}).status_code == 401


@requires_db
def test_generate_solved_outcome_persists_nothing(planner, db, inline_pool):
    client, user_id = planner
    _seed_workers(db, user_id)
    resp = client.post(URL, json={"forbid_adjacent_shifts": False})
    assert resp.status_code == 200
    body = resp.json()
    assert body["outcome"] == "solved"
    assert body["fingerprint"]
    assert body["assignments"] and all("role" in a for a in body["assignments"])
    assert body["costs"]["per_shift"] and body["costs"]["monthly_total_ils"] != "0.00"
    assert body["coverage"]["status"] in ("OPTIMAL", "FEASIBLE")
    assert _count(db, "rosters") == 0 and _count(db, "roster_assignments") == 0


@requires_db
def test_generate_no_solution_within_limit_outcome(planner, db, inline_pool, monkeypatch):
    client, user_id = planner
    _seed_workers(db, user_id)
    monkeypatch.setattr(T, "_run_cp_sat", lambda model, config: RawSolve("UNKNOWN", {}, float("nan"), 0.0, 0.01))
    resp = client.post(URL, json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["outcome"] == "no_solution_within_limit"
    assert body["assignments"] is None and body["fingerprint"] is None
    assert body["coverage_lower_bound"] >= 0
    assert _count(db, "rosters") == 0


@requires_db
def test_generate_invalid_input_is_422(planner, db, inline_pool, monkeypatch):
    client, user_id = planner
    _seed_workers(db, user_id)
    bad = T.InvalidInput(kind="invalid_input", errors=[T.InputError("BAD", "nope")])
    monkeypatch.setattr("app.rosters.generation.solve", lambda problem, config: bad)
    resp = client.post(URL, json={})
    assert resp.status_code == 422
    assert resp.json()["error"]["details"][0]["code"] == "BAD"


@requires_db
def test_generate_mocked_infeasible_is_500_engine_error_and_roster_unchanged(planner, db, inline_pool, monkeypatch):
    client, user_id = planner
    workers = _seed_workers(db, user_id)
    roster_id = insert_roster(db, MONTH, user_id)
    insert_assignment(db, roster_id, workers[0], date(2099, 1, 5), "A", "GENERAL_GUARD")
    monkeypatch.setattr(T, "_run_cp_sat", lambda model, config: RawSolve("INFEASIBLE", {}, float("nan"), 0.0, 0.0))

    resp = client.post(URL, json={})
    assert resp.status_code == 500
    assert resp.json()["error"]["code"] == "ENGINE_ERROR"
    assert _count(db, "roster_assignments") == 1
    with db.cursor() as cur:
        cur.execute("SELECT row_version FROM rosters WHERE id = %s", (roster_id,))
        assert cur.fetchone()[0] == 1


@requires_db
def test_generate_broken_pool_is_500_and_next_generation_succeeds_on_new_executor(planner, db, monkeypatch):
    """A real `EnginePool` whose first executor is dead: 500 ENGINE_ERROR,
    then the very next generation succeeds on the replacement."""
    from concurrent.futures import ThreadPoolExecutor

    import app.engine_pool as ep
    from app.engine_pool import EnginePool, engine_pool
    from tests.rosters.test_engine_pool import _BrokenExecutor

    client, user_id = planner
    _seed_workers(db, user_id)
    broken, healthy = _BrokenExecutor(), ThreadPoolExecutor(1)
    executors = iter([broken, healthy])
    monkeypatch.setattr(EnginePool, "_new_executor", lambda self: next(executors))
    monkeypatch.setattr(ep, "_warm_up", lambda: True)
    asyncio.run(engine_pool.start())
    try:
        first = client.post(URL, json={})
        assert first.status_code == 500 and first.json()["error"]["code"] == "ENGINE_ERROR"
        assert _count(db, "rosters") == 0
        second = client.post(URL, json={})
        assert second.status_code == 200 and second.json()["outcome"] == "solved"
        assert engine_pool._executor is healthy
    finally:
        engine_pool._generating = False
        asyncio.run(engine_pool.shutdown())


@requires_db
def test_generate_history_month_rejected(planner, db, inline_pool):
    client, user_id = planner
    resp = client.post("/api/rosters/2001-01/generate", json={})
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "LOCKED_SHIFT"


# --- busy guard -------------------------------------------------------------


def _call_generate(month="2099-01"):
    from app.auth.models import User
    from app.db import async_session_factory
    from app.rosters.generation import generate
    from app.api_schemas.rosters import GenerateRequest

    async def run():
        async with async_session_factory() as session:
            return await generate(month, GenerateRequest(), User(id=1), session)

    return run()


@requires_db
def test_busy_guard_429_then_released_on_success_error_and_cancellation(db, monkeypatch):
    from app.engine_pool import engine_pool
    from app.errors import EngineError, GenerationInProgressError

    user_id = insert_user(db)
    _seed_workers(db, user_id)
    engine_pool._generating = False

    async def scenario():
        gate = asyncio.Event()
        outcome = {"mode": "block"}

        async def submit(fn, *args):
            if outcome["mode"] == "block":
                await gate.wait()
            if outcome["mode"] == "crash":
                raise BrokenProcessPool("boom")
            return await asyncio.to_thread(fn, *args)

        monkeypatch.setattr(engine_pool, "submit", submit)

        # 1. in flight -> second caller gets 429
        first = asyncio.create_task(_call_generate())
        await asyncio.sleep(0.5)
        assert engine_pool._generating is True
        with pytest.raises(GenerationInProgressError):
            await _call_generate()
        # 2. released after success
        gate.set()
        assert (await first).outcome == "solved"
        assert engine_pool._generating is False
        # 3. released after error
        outcome["mode"] = "crash"
        with pytest.raises(EngineError):
            await _call_generate()
        assert engine_pool._generating is False
        # 4. released after cancellation
        gate.clear()
        outcome["mode"] = "block"
        task = asyncio.create_task(_call_generate())
        await asyncio.sleep(0.5)
        assert engine_pool._generating is True
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert engine_pool._generating is False
        # and a new generation is accepted again
        outcome["mode"] = "run"
        assert (await _call_generate()).outcome == "solved"

    asyncio.run(scenario())
