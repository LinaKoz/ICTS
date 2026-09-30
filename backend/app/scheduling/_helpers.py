"""Private calendar and eligibility helpers shared by the engine modules.

Pure functions over `types`; no ortools, no other `app.*` imports.
"""
from __future__ import annotations

import calendar
from collections.abc import Mapping
from datetime import date, timedelta

from .types import Problem, Role, Shift, Weekday, WorkerInput

_SHIFT_ORDER: dict[Shift, int] = {Shift.A: 0, Shift.B: 1, Shift.C: 2}
_WEEKDAYS: tuple[Weekday, ...] = tuple(Weekday)  # MON..SUN, matches date.weekday() 0..6


def _pos(d: date, s: Shift) -> tuple[date, int]:
    return (d, _SHIFT_ORDER[s])


def _weekday(d: date) -> Weekday:
    return _WEEKDAYS[d.weekday()]


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    """(first day, last day) of the month."""
    last_day_num = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day_num)


def _month_days(year: int, month: int) -> list[date]:
    first, last = _month_bounds(year, month)
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def _prev_month_last_day(year: int, month: int) -> date:
    first = date(year, month, 1)
    return first - timedelta(days=1)


def _next_month_first_day(year: int, month: int) -> date:
    last_day_num = calendar.monthrange(year, month)[1]
    return date(year, month, last_day_num) + timedelta(days=1)


def _demand_of(problem: Problem, s: Shift, r: Role) -> int:
    return problem.demand.get((s, r), 0)


def _adjacent_positions(d: date, s: Shift) -> list[tuple[date, Shift]]:
    """Positions adjacent to (d, s), regardless of month bounds (§4.1, §4.3)."""
    if s is Shift.A:
        return [(d - timedelta(days=1), Shift.C), (d, Shift.B)]
    if s is Shift.B:
        return [(d, Shift.A), (d, Shift.C)]
    return [(d, Shift.B), (d + timedelta(days=1), Shift.A)]


def _is_free(problem: Problem, d: date, s: Shift) -> bool:
    return _pos(d, s) >= _pos(*problem.free_from)


def _fixed_index(problem: Problem):
    """(fixed_set, fixed_slot, fixed_day, fixed_hours) built once from fixed_assignments."""
    fixed_set: set[tuple[str, date, Shift]] = set()
    fixed_slot: dict[tuple[date, Shift, Role], int] = {}
    fixed_day: dict[tuple[str, date], int] = {}
    fixed_hours: dict[str, int] = {}
    for a in problem.fixed_assignments:
        fixed_set.add((a.worker_id, a.date, a.shift))
        fixed_slot[(a.date, a.shift, a.role)] = fixed_slot.get((a.date, a.shift, a.role), 0) + 1
        fixed_day[(a.worker_id, a.date)] = fixed_day.get((a.worker_id, a.date), 0) + 1
        fixed_hours[a.worker_id] = fixed_hours.get(a.worker_id, 0) + 8
    return fixed_set, fixed_slot, fixed_day, fixed_hours


def _blocked_adjacent(problem: Problem) -> dict[str, set[tuple[date, Shift]]]:
    """Per-worker positions where a new variable must not be created because
    they are adjacent to a fixed assignment (only if the rule is on) or a
    neighbor assignment (always) - §4.3."""
    blocked: dict[str, set[tuple[date, Shift]]] = {}
    if problem.forbid_adjacent_shifts:
        for a in problem.fixed_assignments:
            blocked.setdefault(a.worker_id, set()).update(_adjacent_positions(a.date, a.shift))
    for a in problem.neighbor_assignments:
        blocked.setdefault(a.worker_id, set()).update(_adjacent_positions(a.date, a.shift))
    return blocked


def _eligible_free_shifts(problem: Problem, worker: WorkerInput, d: date) -> list[Shift]:
    """Free shifts on day d for which a variable would exist for this worker."""
    fixed_set, _, _, _ = _fixed_index(problem)
    blocked = _blocked_adjacent(problem).get(worker.id, set())
    out = []
    for s in (Shift.A, Shift.B, Shift.C):
        if not _is_free(problem, d, s):
            continue
        if (_weekday(d), s) not in worker.availability:
            continue
        if _demand_of(problem, s, worker.role) <= 0:
            continue
        if (worker.id, d, s) in fixed_set:
            continue
        if (d, s) in blocked:
            continue
        out.append(s)
    return out


def _day_cap(problem: Problem, worker: WorkerInput, d: date, fixed_day: Mapping[tuple[str, date], int]) -> int:
    remaining = max(0, 2 - fixed_day.get((worker.id, d), 0))
    shifts = _eligible_free_shifts(problem, worker, d)
    if problem.forbid_adjacent_shifts:
        k = 2 if (Shift.A in shifts and Shift.C in shifts) else min(len(shifts), 1)
    else:
        k = len(shifts)
    return min(remaining, k)


def _remaining_max_shifts(worker: WorkerInput, fixed_hours: Mapping[str, int]) -> int:
    return max(0, worker.max_hours - fixed_hours.get(worker.id, 0)) // 8


def _worker_cap(problem: Problem, worker: WorkerInput, fixed_hours: Mapping[str, int]) -> int:
    remaining_max_shifts = _remaining_max_shifts(worker, fixed_hours)
    fixed_day = _fixed_index(problem)[2]
    day_caps = sum(_day_cap(problem, worker, d, fixed_day) for d in _month_days(problem.year, problem.month)
                   if _is_free(problem, d, Shift.A) or _is_free(problem, d, Shift.B) or _is_free(problem, d, Shift.C))
    return min(remaining_max_shifts, day_caps)


def _ceil_div(a: int, b: int) -> int:
    return -(-a // b)


def _var_name_x(worker_id: str, d: date, s: Shift) -> str:
    return f"x[{worker_id}|{d.isoformat()}|{s.value}]"


def _var_name_short(worker_id: str) -> str:
    return f"short[{worker_id}]"
