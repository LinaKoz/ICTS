"""Process-pool management for the scheduling engine (§2 "Generation execution").

The engine runs in a `ProcessPoolExecutor(max_workers=1, mp_context=spawn)`
so CP-SAT search never blocks the API event loop. The class shape and
API (`submit`, `warm_up`, recovery on `BrokenProcessPool`) were frozen
in T0; T3 adds the generation-in-progress guard and calls `submit`
with `scheduling.solve` (§8 T3 acceptance: "Pool recovery...
identity check").
"""
from __future__ import annotations

import asyncio
import logging
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from typing import Any, Callable

logger = logging.getLogger(__name__)

_SPAWN_CONTEXT = multiprocessing.get_context("spawn")


def _warm_up() -> bool:
    """Runs in the child process at startup. Imports the CP-SAT native
    module and solves a one-variable model, exercising both the import
    and the native solver. Returns True on success.
    """
    from ortools.sat.python import cp_model

    model = cp_model.CpModel()
    x = model.new_int_var(0, 1, "x")
    model.maximize(x)
    solver = cp_model.CpSolver()
    status = solver.solve(model)
    return status in (cp_model.OPTIMAL, cp_model.FEASIBLE)


class EnginePool:
    """Owns the current executor and an `asyncio.Lock` guarding replacement.

    On `BrokenProcessPool`, the failing call takes the lock and
    replaces the executor only if the current one is still the
    executor that failed (identity check) -- a caller that finds a
    newer executor already in place skips the replacement. This keeps
    concurrent failures from creating competing replacements.
    """

    def __init__(self, max_workers: int = 1) -> None:
        self._max_workers = max_workers
        self._executor: ProcessPoolExecutor | None = None
        self._lock = asyncio.Lock()
        self.ready = False
        self._generating = False  # process-local guard: one generation at a time

    def _new_executor(self) -> ProcessPoolExecutor:
        return ProcessPoolExecutor(max_workers=self._max_workers, mp_context=_SPAWN_CONTEXT)

    async def start(self) -> None:
        """Creates the executor and warms it up. Called from the lifespan."""
        self._executor = self._new_executor()
        await self.warm_up()

    async def warm_up(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            assert self._executor is not None
            ok = await loop.run_in_executor(self._executor, _warm_up)
            self.ready = bool(ok)
        except Exception:  # noqa: BLE001 - warm-up failure must not crash startup
            logger.exception("engine warm-up failed; /api/health will report engine: not_ready")
            self.ready = False

    def try_begin_generation(self) -> bool:
        """Non-blocking guard: `True` and marks busy if no generation is
        running, `False` if one already is. No `await` happens between
        the check and the set, so this is race-free on the event loop."""
        if self._generating:
            return False
        self._generating = True
        return True

    def end_generation(self) -> None:
        """Releases the guard. The caller's `finally` must call this on
        success, error and cancellation alike."""
        self._generating = False

    async def submit(self, fn: Callable[..., Any], *args: Any) -> Any:
        """Runs `fn(*args)` in the pool, recovering once from a broken pool."""
        loop = asyncio.get_running_loop()
        executor = self._executor
        try:
            return await loop.run_in_executor(executor, fn, *args)
        except BrokenProcessPool:
            await self._replace_if_current(executor)
            raise

    async def _replace_if_current(self, failed_executor: ProcessPoolExecutor | None) -> None:
        async with self._lock:
            if self._executor is not failed_executor:
                # Someone else already replaced it; nothing to do.
                return
            if failed_executor is not None:
                failed_executor.shutdown(wait=False, cancel_futures=True)
            self._executor = self._new_executor()
            await self.warm_up()

    async def shutdown(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)


engine_pool = EnginePool()
