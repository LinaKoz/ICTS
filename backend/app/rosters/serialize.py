"""Maps engine (`scheduling.types`) and `costs.py` values to the API
schemas (§6, C3). The one place that applies the `NO_CONTRACT_FOR_MONTH`
relabeling: an engine `UNKNOWN_WORKER` whose worker exists but was
excluded from the problem for lacking an applicable contract (P4).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_schemas.common import (
    AssignmentOut,
    CostsOut,
    CoverageGapOut,
    CoverageStatusOut,
    HourShortfallOut,
    MinHoursStatusOut,
    ViolationOut,
    ShiftCostOut,
    WorkerCostOut,
    WorkerRefOut,
)
from app.rosters.costs import Costs
from app.workers.models import Worker
from app.scheduling import Assignment, CoverageGap, CoverageStatus, HourShortfall, MinHoursStatus, Violation, ViolationCode


def assignment_to_out(a: Assignment) -> AssignmentOut:
    return AssignmentOut(worker_id=a.worker_id, date=a.date, shift=a.shift.value, role=a.role.value)


def violation_to_out(v: Violation, no_contract_worker_ids: set[str]) -> ViolationOut:
    code = v.code.value
    if v.code is ViolationCode.UNKNOWN_WORKER and v.key and str(v.key[0]) in no_contract_worker_ids:
        code = "NO_CONTRACT_FOR_MONTH"
    return ViolationOut(
        code=code,
        key=list(v.key),
        magnitude=v.magnitude,
        assignments=[assignment_to_out(a) for a in v.assignments],
    )


def coverage_gap_to_out(g: CoverageGap) -> CoverageGapOut:
    return CoverageGapOut(
        date=g.date,
        shift=g.shift.value,
        role=g.role.value,
        required=g.required,
        assigned=g.assigned,
        missing=g.missing,
        proven_missing=g.proven_missing,
        locked=g.locked,
    )


def hour_shortfall_to_out(h: HourShortfall) -> HourShortfallOut:
    return HourShortfallOut(worker_id=h.worker_id, min_hours=h.min_hours, assigned_hours=h.assigned_hours,
                             missing_hours=h.missing_hours)


def coverage_status_to_out(c: CoverageStatus) -> CoverageStatusOut:
    return CoverageStatusOut(status=c.status, total_uncovered=c.total_uncovered,
                              locked_uncovered=c.locked_uncovered, lower_bound=c.lower_bound)


def min_hours_status_to_out(m: MinHoursStatus) -> MinHoursStatusOut:
    return MinHoursStatusOut(status=m.status, total_shortfall=m.total_shortfall)


def costs_to_out(costs: Costs) -> CostsOut:
    return CostsOut(
        per_shift=[
            ShiftCostOut(date=sc.date, shift=sc.shift.value, amount_ils=str(sc.amount_ils),
                         unknown_cost_assignments=sc.unknown_cost_assignments)
            for sc in costs.per_shift
        ],
        per_worker=[
            WorkerCostOut(worker_id=wc.worker_id, hours=wc.hours,
                          amount_ils=str(wc.amount_ils) if wc.amount_ils is not None else None)
            for wc in costs.per_worker
        ],
        monthly_total_ils=str(costs.monthly_total_ils),
        unknown_cost_worker_count=costs.unknown_cost_worker_count,
    )


async def load_worker_refs(session: AsyncSession) -> list[WorkerRefOut]:
    """Name lookup for the grid: every worker, so ids in assignments,
    shortfalls, costs and violations all resolve (inactive workers keep
    their locked shifts, D9)."""
    rows = (await session.execute(select(Worker).order_by(Worker.full_name, Worker.id))).scalars().all()
    return [
        WorkerRefOut(worker_id=str(w.id), full_name=w.full_name, role=w.role, status=w.status) for w in rows
    ]
