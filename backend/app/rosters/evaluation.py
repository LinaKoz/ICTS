"""`evaluate(session, roster)` (§3 "Violations, warnings and costs"):
computes violations, coverage gaps and hour shortfalls on read, from
current data, never from anything stored.

Applies the D9(b) override (§3): for locked (already-started)
assignments, the engine's INACTIVE_WORKER/WRONG_ROLE (computed from the
worker's *current* row) are replaced with a check against
`resolve_worker_state(worker_id, shift_start_time)`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.rosters.models import Roster, RosterAssignment
from app.rosters.problem_builder import BuiltProblem, _pos, build_problem, is_history_month
from app.scheduling import Assignment, Metrics, Role, Shift, Violation, ViolationCode, roster_metrics, validate_roster
from app.timeutil import now_israel, shift_start_time
from app.workers.history import load_worker_states, state_at

_LOCKED_CHECK_CODES = (ViolationCode.INACTIVE_WORKER, ViolationCode.WRONG_ROLE)


@dataclass
class Evaluation:
    violations: list[Violation]
    metrics: Metrics
    built: BuiltProblem
    no_contract_worker_ids: list[int] = field(default_factory=list)


async def evaluate(session: AsyncSession, roster: Roster, now: datetime | None = None) -> Evaluation:
    now = now or now_israel()
    built = await build_problem(session, roster.month, roster.forbid_adjacent_shifts, now)
    problem = built.problem

    stmt = select(RosterAssignment).where(RosterAssignment.roster_id == roster.id)
    stored = (await session.execute(stmt)).scalars().all()
    full = [Assignment(str(ra.worker_id), ra.date, Shift(ra.shift), Role(ra.role)) for ra in stored]

    metrics = roster_metrics(problem, full)

    if is_history_month(roster.month, now):
        # P3: past months are read-only history, shown without violation evaluation.
        violations: list[Violation] = []
    else:
        violations = validate_roster(problem, full)
        locked_assignments = [a for a in full if _pos(a.date, a.shift) < _pos(*problem.free_from)]
        violations = await _apply_d9b_override(session, violations, locked_assignments, problem.free_from)

    return Evaluation(violations=violations, metrics=metrics, built=built, no_contract_worker_ids=built.no_contract_worker_ids)


async def _apply_d9b_override(
    session: AsyncSession,
    violations: list[Violation],
    locked_assignments: list[Assignment],
    free_from: tuple,
) -> list[Violation]:
    locked_keys = {(a.worker_id, a.date, a.shift) for a in locked_assignments}
    kept = [
        v
        for v in violations
        if not (v.code in _LOCKED_CHECK_CODES and v.key in locked_keys)
    ]
    current, history = await load_worker_states(session, {int(a.worker_id) for a in locked_assignments})
    for a in locked_assignments:
        cur = current.get(int(a.worker_id))
        if cur is None:
            continue  # worker doesn't exist; the engine's UNKNOWN_WORKER already covers it
        state = state_at(cur, history.get(int(a.worker_id), []), shift_start_time(a.date, a.shift.value))
        if state["status"] == "INACTIVE":
            kept.append(Violation(ViolationCode.INACTIVE_WORKER, (a.worker_id, a.date, a.shift), 1, (a,)))
        if state["role"] != a.role.value:
            kept.append(Violation(ViolationCode.WRONG_ROLE, (a.worker_id, a.date, a.shift), 1, (a,)))
    return kept
