"""Cheap, proven lower bounds on uncovered positions (§4.7).

Used by `solve` as a fallback coverage bound and by `roster_metrics` for
`proven_missing`. Pure Python; no solver call.
"""
from __future__ import annotations

from datetime import date

from ._helpers import (
    _demand_of,
    _eligible_free_shifts,
    _fixed_index,
    _is_free,
    _month_days,
    _remaining_max_shifts,
    _worker_cap,
)
from .types import Diagnostics, Problem, Role, Shift


def _slot_deficits(problem: Problem) -> dict[tuple[date, Shift, Role], int]:
    """§4.7 slot_deficit(d,s,r) for every free slot."""
    _, fixed_slot, fixed_day, fixed_hours = _fixed_index(problem)
    active = [w for w in problem.workers if w.active]
    out: dict[tuple[date, Shift, Role], int] = {}
    for d in _month_days(problem.year, problem.month):
        for s in (Shift.A, Shift.B, Shift.C):
            if not _is_free(problem, d, s):
                continue
            for r in Role:
                required = max(0, _demand_of(problem, s, r) - fixed_slot.get((d, s, r), 0))
                if required == 0:
                    continue
                eligible = 0
                for w in active:
                    if w.role != r:
                        continue
                    if s not in _eligible_free_shifts(problem, w, d):
                        continue
                    if _remaining_max_shifts(w, fixed_hours) < 1:
                        continue
                    if max(0, 2 - fixed_day.get((w.id, d), 0)) < 1:
                        continue
                    eligible += 1
                out[(d, s, r)] = max(0, required - eligible)
    return out


def diagnose(problem: Problem) -> Diagnostics:
    _, fixed_slot, fixed_day, fixed_hours = _fixed_index(problem)
    active = [w for w in problem.workers if w.active]
    deficits = _slot_deficits(problem)

    caps = {w.id: _worker_cap(problem, w, fixed_hours) for w in active}

    role_lower_bounds: dict[Role, int] = {}
    for r in Role:
        slot_sum = sum(v for (d, s, rr), v in deficits.items() if rr is r)
        remaining_demand_r = 0
        for d in _month_days(problem.year, problem.month):
            for s in (Shift.A, Shift.B, Shift.C):
                if _is_free(problem, d, s):
                    remaining_demand_r += max(0, _demand_of(problem, s, r) - fixed_slot.get((d, s, r), 0))
        cap_sum = sum(caps[w.id] for w in active if w.role is r)
        role_deficit = max(0, remaining_demand_r - cap_sum)
        role_lower_bounds[r] = max(slot_sum, role_deficit)

    worker_shortfall_lower_bounds = {
        w.id: max(0, w.min_hours - fixed_hours.get(w.id, 0) - 8 * caps[w.id]) for w in active
    }

    return Diagnostics(role_lower_bounds, sum(role_lower_bounds.values()), worker_shortfall_lower_bounds)
