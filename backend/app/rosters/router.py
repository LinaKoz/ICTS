"""`GET /rosters/{month}` (§6): roster + assignments + violations +
gaps + shortfalls + costs + approval history + `is_history` +
`free_from` + `forbid_adjacent_shifts`. Aggregates the other roster
routers (`generation.py`, `save.py`) under one include in `main.py`.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_schemas.common import error_responses
from app.api_schemas.rosters import RosterOut
from app.auth.models import User
from app.auth.session import require_role
from app.db import get_session
from app.errors import NotFoundError
from app.rosters.approval import load_approval_history
from app.rosters.costs import compute_costs
from app.rosters.evaluation import evaluate
from app.rosters.generation import router as generate_router
from app.rosters.models import Roster, RosterAssignment
from app.rosters.problem_builder import MONTH_PATTERN, is_history_month, parse_month
from app.rosters.save import router as save_router
from app.rosters.serialize import assignment_to_out, coverage_gap_to_out, costs_to_out, hour_shortfall_to_out, load_worker_refs, violation_to_out
from app.scheduling import Assignment, Role, Shift

router = APIRouter(prefix="/api/rosters", tags=["rosters"])
router.include_router(generate_router)
router.include_router(save_router)


@router.get("/{month}", response_model=RosterOut, responses=error_responses(401, 403, 404, 422))
async def get_roster(
    month: Annotated[str, Path(pattern=MONTH_PATTERN, description="YYYY-MM")],
    _user: User = Depends(require_role("PLANNER", "MANAGER")),
    session: AsyncSession = Depends(get_session),
) -> RosterOut:
    month_date = parse_month(month)
    roster = (await session.execute(select(Roster).where(Roster.month == month_date))).scalar_one_or_none()
    if roster is None:
        raise NotFoundError(f"no roster for {month}")

    stmt = select(RosterAssignment).where(RosterAssignment.roster_id == roster.id)
    stored = (await session.execute(stmt)).scalars().all()
    assignments = [Assignment(str(ra.worker_id), ra.date, Shift(ra.shift), Role(ra.role)) for ra in stored]

    ev = await evaluate(session, roster)
    updated_by = await session.get(User, roster.updated_by)
    no_contract_ids = {str(wid) for wid in ev.no_contract_worker_ids}
    costs = compute_costs(assignments, ev.built.contract_by_worker_id)

    approval_history = await load_approval_history(session, roster.id)

    return RosterOut(
        month=roster.month,
        status=roster.status,
        version=roster.row_version,
        is_history=is_history_month(month_date),
        free_from=(ev.built.problem.free_from[0], ev.built.problem.free_from[1].value),
        forbid_adjacent_shifts=roster.forbid_adjacent_shifts,
        assignments=[assignment_to_out(a) for a in assignments],
        violations=[violation_to_out(v, no_contract_ids) for v in ev.violations],
        coverage_gaps=[coverage_gap_to_out(g) for g in ev.metrics.coverage_gaps],
        hour_shortfalls=[hour_shortfall_to_out(h) for h in ev.metrics.hour_shortfalls],
        costs=costs_to_out(costs),
        workers=await load_worker_refs(session),
        updated_at=roster.updated_at,
        updated_by=updated_by.display_name if updated_by else "unknown",
        approval_history=approval_history,
    )
