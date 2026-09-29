"""§8 T3: busy guard, pool recovery with identity check, warm-up in the
child process, `/api/health` engine state."""
from __future__ import annotations

import asyncio
import os
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures.process import BrokenProcessPool

import pytest
from fastapi.testclient import TestClient

import app.engine_pool as ep
from app.engine_pool import EnginePool


class _BrokenExecutor:
    """Stands in for an executor whose worker process died."""

    def __init__(self) -> None:
        self.shutdown_called = False

    def submit(self, *a, **kw):
        # Fails asynchronously, like a real pool noticing its dead child, so
        # concurrent callers all captured this executor before any of them fails.
        fut: Future = Future()
        threading.Timer(0.05, fut.set_exception, args=(BrokenProcessPool("worker died"),)).start()
        return fut

    def shutdown(self, wait=True, cancel_futures=False):
        self.shutdown_called = True


def _pool_with(monkeypatch, executors: list) -> tuple[EnginePool, list]:
    """A pool whose `_new_executor` hands out `executors` in order."""
    pool = EnginePool()
    created: list = []
    it = iter(executors)

    def new():
        ex = next(it)
        created.append(ex)
        return ex

    monkeypatch.setattr(pool, "_new_executor", new)
    monkeypatch.setattr(ep, "_warm_up", lambda: True)
    return pool, created


def test_broken_pool_raises_then_next_call_succeeds_on_new_executor(monkeypatch):
    broken = _BrokenExecutor()
    healthy = ThreadPoolExecutor(1)
    pool, created = _pool_with(monkeypatch, [broken, healthy])

    async def run():
        await pool.start()
        with pytest.raises(BrokenProcessPool):
            await pool.submit(int, "1")
        assert broken.shutdown_called
        assert pool._executor is healthy
        return await pool.submit(int, "7")

    assert asyncio.run(run()) == 7
    assert created == [broken, healthy]


def test_two_callers_failing_on_same_broken_executor_cause_one_replacement(monkeypatch):
    broken = _BrokenExecutor()
    pool, created = _pool_with(monkeypatch, [broken, ThreadPoolExecutor(1), ThreadPoolExecutor(1)])

    async def run():
        await pool.start()
        results = await asyncio.gather(
            pool.submit(int, "1"), pool.submit(int, "2"), return_exceptions=True
        )
        assert all(isinstance(r, BrokenProcessPool) for r in results)

    asyncio.run(run())
    assert len(created) == 2  # the initial one plus exactly one replacement (identity check)
    assert pool._executor is created[1]


def test_replacement_skipped_when_current_executor_is_not_the_failed_one(monkeypatch):
    stale = _BrokenExecutor()
    current = ThreadPoolExecutor(1)
    pool, created = _pool_with(monkeypatch, [current])

    async def run():
        await pool.start()
        await pool._replace_if_current(stale)  # someone else already replaced `stale`

    asyncio.run(run())
    assert created == [current] and pool._executor is current


def test_busy_guard_blocks_second_and_releases():
    pool = EnginePool()
    assert pool.try_begin_generation() is True
    assert pool.try_begin_generation() is False
    pool.end_generation()
    assert pool.try_begin_generation() is True


def test_warm_up_failure_marks_pool_not_ready(monkeypatch):
    def boom():
        raise RuntimeError("no ortools")

    pool, _ = _pool_with(monkeypatch, [ThreadPoolExecutor(1)])
    monkeypatch.setattr(ep, "_warm_up", boom)
    asyncio.run(pool.start())
    assert pool.ready is False


def test_health_reports_engine_not_ready_after_warm_up_failure(monkeypatch):
    from app.main import app

    def boom():
        raise RuntimeError("no ortools")

    pool, _ = _pool_with(monkeypatch, [ThreadPoolExecutor(1)])
    monkeypatch.setattr(ep, "_warm_up", boom)
    asyncio.run(pool.start())
    monkeypatch.setattr("app.main.engine_pool", pool)

    client = TestClient(app)  # no `with`: the lifespan (alembic, seed, spawn) is not needed here
    assert client.get("/api/health").json() == {"status": "ok", "engine": "not_ready"}

    monkeypatch.setattr(ep, "_warm_up", lambda: True)
    asyncio.run(pool.warm_up())
    assert client.get("/api/health").json() == {"status": "ok", "engine": "ready"}


def test_warm_up_runs_in_child_process_and_imports_ortools():
    async def run():
        pool = EnginePool()
        await pool.start()
        try:
            loop = asyncio.get_running_loop()
            child_pid = await loop.run_in_executor(pool._executor, os.getpid)
            imported = await loop.run_in_executor(
                pool._executor, eval, "'ortools.sat.python.cp_model' in __import__('sys').modules"
            )
            return pool.ready, child_pid, imported
        finally:
            await pool.shutdown()

    ready, child_pid, imported = asyncio.run(run())
    assert ready is True
    assert child_pid != os.getpid()
    assert imported is True
