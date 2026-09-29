"""`GET /rosters/{month}` (§6): roster + assignments + violations +
gaps + shortfalls + costs + approval history + `is_history` +
`free_from` + `forbid_adjacent_shifts`. Aggregates the other roster
routers (`generation.py`, `save.py`) under one include in `main.py`.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_schemas.rosters import ApprovalEventOut, RosterOut
from app.auth.models import User
from app.auth.session import require_role
from app.db import get_session
from app.errors import NotFoundError
from app.rosters.costs import compute_costs
from app.rosters.evaluation import evaluate
from app.rosters.generation import router as generate_router
from app.rosters.models import Roster, RosterApproval, RosterAssignment
from app.rosters.problem_builder import is_history_month, parse_month
from app.rosters.save import router as save_router
from app.rosters.serialize import assignment_to_out, coverage_gap_to_out, costs_to_out, hour_shortfall_to_out, violation_to_out
from app.scheduling.types import Assignment, Role, Shift

router = APIRouter(prefix="/api/rosters", tags=["rosters"])
router.include_router(generate_router)
router.include_router(save_router)


@router.get("/{month}", response_model=RosterOut)
async def get_roster(
    month: str,
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
    no_contract_ids = {str(wid) for wid in ev.no_contract_worker_ids}
    costs = compute_costs(assignments, ev.built.contract_by_worker_id)

    approvals = (
        (
            await session.execute(
                select(RosterApproval).where(RosterApproval.roster_id == roster.id).order_by(RosterApproval.approved_at.desc())
            )
        )
        .scalars()
        .all()
    )
    approval_history = [
        ApprovalEventOut(
            approved_by=str(ap.approved_by),
            approved_at=ap.approved_at.isoformat(),
            reason=ap.reason,
            revoked_at=ap.revoked_at.isoformat() if ap.revoked_at else None,
            revoke_cause=ap.revoke_cause,
        )
        for ap in approvals
    ]

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
        approval_history=approval_history,
    )
