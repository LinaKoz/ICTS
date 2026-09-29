"""`POST /rosters/{month}/generate` (§6, §2, T3).

Builds the `Problem`, runs `solve()` in the `EnginePool`'s process
pool, and maps the `ScheduleResult` to the API (§4.6 "API mapping").
Persists nothing: a failed or timed-out run can never overwrite an
existing roster.
"""
from __future__ import annotations

import logging
import os
from concurrent.futures.process import BrokenProcessPool

from typing import Annotated

from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_schemas.common import error_responses
from app.api_schemas.rosters import GenerateOutcomeOut, GenerateRequest, ObjectiveOut
from app.auth.models import User
from app.auth.session import require_role
from app.config import settings
from app.db import get_session
from app.engine_pool import engine_pool
from app.errors import EngineError, GenerationInProgressError, LockedShiftError, ValidationAppError
from app.rosters.costs import compute_costs
from app.rosters.problem_builder import MONTH_PATTERN, build_problem, compute_fingerprint, is_history_month, parse_month
from app.rosters.serialize import (
    assignment_to_out,
    costs_to_out,
    coverage_gap_to_out,
    coverage_status_to_out,
    hour_shortfall_to_out,
    load_worker_refs,
    min_hours_status_to_out,
    violation_to_out,
)
from app.scheduling.types import EngineErrorResult, InvalidInput, NoSolutionWithinLimit, Solved, SolverConfig, solve

logger = logging.getLogger(__name__)

router = APIRouter(tags=["rosters"])


@router.post(
    "/{month}/generate",
    response_model=GenerateOutcomeOut,
    responses=error_responses(401, 403, 422, 429, 500),
)
async def generate(
    month: Annotated[str, Path(pattern=MONTH_PATTERN, description="YYYY-MM")],
    body: GenerateRequest,
    _user: User = Depends(require_role("PLANNER", "MANAGER")),
    session: AsyncSession = Depends(get_session),
) -> GenerateOutcomeOut:
    month_date = parse_month(month)
    if is_history_month(month_date):
        raise LockedShiftError("cannot generate a roster for a historical month")

    if not engine_pool.try_begin_generation():
        raise GenerationInProgressError("a generation is already running")
    try:
        built = await build_problem(session, month_date, body.forbid_adjacent_shifts)
        # The fingerprint describes the data the solve *saw*, so it is taken
        # before the solve. Computing it afterwards would bless a roster
        # solved against data that changed while the engine was running.
        fingerprint = await compute_fingerprint(session, built)
        config = SolverConfig(
            time_limit_s=settings.solver_time_limit_s,
            num_workers=min(settings.num_workers, os.cpu_count() or 1),
        )
        try:
            result = await engine_pool.submit(solve, built.problem, config)
        except BrokenProcessPool as exc:
            raise EngineError("the scheduling engine's process pool crashed") from exc
        except Exception as exc:  # noqa: BLE001 - any engine-side crash is an ENGINE_ERROR
            logger.exception("engine call failed")
            raise EngineError(f"the scheduling engine failed: {exc}") from exc
    finally:
        engine_pool.end_generation()

    no_contract_ids = {str(wid) for wid in built.no_contract_worker_ids}

    if isinstance(result, Solved):
        return GenerateOutcomeOut(
            outcome="solved",
            assignments=[assignment_to_out(a) for a in result.assignments],
            coverage_gaps=[coverage_gap_to_out(g) for g in result.coverage_gaps],
            hour_shortfalls=[hour_shortfall_to_out(h) for h in result.hour_shortfalls],
            coverage=coverage_status_to_out(result.coverage),
            min_hours=min_hours_status_to_out(result.min_hours),
            lexicographically_optimal=result.lexicographically_optimal,
            preexisting_violations=[violation_to_out(v, no_contract_ids) for v in result.preexisting_violations],
            objective=ObjectiveOut(**vars(result.objective)),
            costs=costs_to_out(compute_costs(list(result.assignments), built.contract_by_worker_id)),
            workers=await load_worker_refs(session),
            fingerprint=fingerprint,
            warnings=list(result.warnings),
        )

    if isinstance(result, NoSolutionWithinLimit):
        # Not a claim of infeasibility; nothing to save, nothing replaced.
        return GenerateOutcomeOut(outcome="no_solution_within_limit", coverage_lower_bound=result.coverage_lower_bound)

    if isinstance(result, InvalidInput):
        raise ValidationAppError(
            "the scheduling problem is invalid",
            details=[{"code": e.code, "message": e.message, "details": e.details} for e in result.errors],
        )

    assert isinstance(result, EngineErrorResult)
    raise EngineError(result.message, details={"solver_status": result.solver_status})
