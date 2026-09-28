"""The scheduling engine's shared, frozen contract (§4.2, §4.5, §4.6).

This module is pure stdlib: no sqlalchemy, no fastapi, no other
`app.*` import outside `scheduling`. That independence is enforced by
a test (§4.9 "Independence").

T0 freezes the field names, types and function signatures exactly as
specified in the plan. T1 implements the function bodies; until then
they raise `NotImplementedError`. Do not change shapes without going
through the main session (§9 "Ownership").
"""
from __future__ import annotations

import calendar
import math
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum
from typing import Literal, Union

from ortools.sat.python import cp_model


# --------------------------------------------------------------------------
# §4.1 Domain enums
# --------------------------------------------------------------------------


class Shift(str, Enum):
    A = "A"  # 00:00-08:00
    B = "B"  # 08:00-16:00
    C = "C"  # 16:00-00:00


class Role(str, Enum):
    GENERAL_GUARD = "GENERAL_GUARD"
    SCREENER = "SCREENER"
    SUPERVISOR = "SUPERVISOR"


class Weekday(str, Enum):
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"
    SAT = "SAT"
    SUN = "SUN"


# Demand of 2 GENERAL_GUARD, 2 SCREENER, 1 SUPERVISOR per shift (§4.1, §1).
DEFAULT_DEMAND: dict[tuple[Shift, Role], int] = {
    (Shift.A, Role.GENERAL_GUARD): 2,
    (Shift.A, Role.SCREENER): 2,
    (Shift.A, Role.SUPERVISOR): 1,
    (Shift.B, Role.GENERAL_GUARD): 2,
    (Shift.B, Role.SCREENER): 2,
    (Shift.B, Role.SUPERVISOR): 1,
    (Shift.C, Role.GENERAL_GUARD): 2,
    (Shift.C, Role.SCREENER): 2,
    (Shift.C, Role.SUPERVISOR): 1,
}


# --------------------------------------------------------------------------
# §4.5 Violation codes
# --------------------------------------------------------------------------


class ViolationCode(str, Enum):
    INACTIVE_WORKER = "INACTIVE_WORKER"
    UNKNOWN_WORKER = "UNKNOWN_WORKER"
    WRONG_ROLE = "WRONG_ROLE"
    UNAVAILABLE = "UNAVAILABLE"
    OUT_OF_MONTH = "OUT_OF_MONTH"
    DUPLICATE_ASSIGNMENT = "DUPLICATE_ASSIGNMENT"
    DAILY_LIMIT = "DAILY_LIMIT"
    ADJACENT_SHIFTS = "ADJACENT_SHIFTS"
    MAX_HOURS = "MAX_HOURS"
    OVERSTAFFED = "OVERSTAFFED"


# --------------------------------------------------------------------------
# §4.2 Interface dataclasses
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkerInput:
    """Contract already resolved for the month by the caller."""

    id: str
    role: Role
    active: bool
    availability: frozenset[tuple[Weekday, Shift]]
    min_hours: int
    max_hours: int


@dataclass(frozen=True)
class Assignment:
    """An assignment. `role` is the slot role, snapshotted; the
    validator checks it against the worker's role."""

    worker_id: str
    date: date
    shift: Shift
    role: Role


@dataclass(frozen=True)
class Violation:
    """`key` is the stable scope (§4.5 table); `magnitude` is >= 1."""

    code: ViolationCode
    key: tuple
    magnitude: int
    assignments: tuple[Assignment, ...]


@dataclass(frozen=True)
class Problem:
    year: int
    month: int
    demand: Mapping[tuple[Shift, Role], int]
    workers: Sequence[WorkerInput]
    free_from: tuple[date, Shift]  # (1st, A) <= free_from <= (last day + 1, A)
    fixed_assignments: Sequence[Assignment] = field(default_factory=tuple)  # all before free_from
    neighbor_assignments: Sequence[Assignment] = field(default_factory=tuple)  # boundary days only
    forbid_adjacent_shifts: bool = False  # optional rule (§4.1); off = brief's rules only


@dataclass(frozen=True)
class SolverConfig:
    time_limit_s: float = 10.0  # CP-SAT search time for the single solve
    num_workers: int = 8  # the application passes min(8, cpu_count)
    random_seed: int = 0


@dataclass(frozen=True)
class InputError:
    """One `validate_problem` failure."""

    code: str
    message: str
    details: dict | None = None


@dataclass(frozen=True)
class RawSolve:
    """Test seam: the raw CP-SAT result (§4.2 "Test seam")."""

    status: str
    values: Mapping[str, int]
    objective: float
    bound: float
    wall_time: float


@dataclass(frozen=True)
class CoverageGap:
    date: date
    shift: Shift
    role: Role
    required: int
    assigned: int
    missing: int
    proven_missing: int
    locked: bool


@dataclass(frozen=True)
class HourShortfall:
    worker_id: str
    min_hours: int
    assigned_hours: int
    missing_hours: int


@dataclass(frozen=True)
class CoverageStatus:
    status: Literal["OPTIMAL", "FEASIBLE"]
    total_uncovered: int
    locked_uncovered: int
    lower_bound: int


@dataclass(frozen=True)
class MinHoursStatus:
    status: Literal["OPTIMAL", "FEASIBLE"]
    total_shortfall: int


@dataclass(frozen=True)
class ObjectiveInfo:
    weight: int
    s_max: int
    value: float
    bound: float


@dataclass(frozen=True)
class Metrics:
    """Returned by `roster_metrics`: coverage gaps and hour shortfalls,
    recomputed from the roster."""

    coverage_gaps: tuple[CoverageGap, ...]
    hour_shortfalls: tuple[HourShortfall, ...]
    locked_uncovered: int
    total_uncovered: int


@dataclass(frozen=True)
class Diagnostics:
    """Returned by `diagnose` (§4.7): proven lower bounds, free slots only."""

    role_lower_bounds: Mapping[Role, int]
    total_lower_bound: int
    worker_shortfall_lower_bounds: Mapping[str, int]


@dataclass(frozen=True)
class Timings:
    input_validation_s: float
    diagnostics_s: float
    model_build_s: float
    search_s: float
    roster_validation_s: float
    total_s: float


# --------------------------------------------------------------------------
# §4.6 Result type (discriminated union)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Solved:
    kind: Literal["solved"]
    assignments: tuple[Assignment, ...]  # fixed ones included, unchanged
    coverage_gaps: tuple[CoverageGap, ...]
    hour_shortfalls: tuple[HourShortfall, ...]
    coverage: CoverageStatus
    min_hours: MinHoursStatus
    lexicographically_optimal: bool
    preexisting_violations: tuple[Violation, ...]
    objective: ObjectiveInfo
    free_from: tuple[date, Shift]
    diagnostics: Diagnostics
    timings: Timings
    warnings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class NoSolutionWithinLimit:
    kind: Literal["no_solution_within_limit"]
    coverage_lower_bound: int  # locked_uncovered + max(solver-derived, diagnostic)
    diagnostics: Diagnostics
    timings: Timings


@dataclass(frozen=True)
class InvalidInput:
    kind: Literal["invalid_input"]
    errors: tuple[InputError, ...]


@dataclass(frozen=True)
class EngineErrorResult:
    """Named `EngineErrorResult` here to avoid clashing with
    `app.errors.EngineError` (the HTTP-facing exception); the plan's
    `EngineError` result-union member."""

    kind: Literal["engine_error"]
    solver_status: str
    message: str
    diagnostics: Diagnostics | None
    timings: Timings


ScheduleResult = Union[Solved, NoSolutionWithinLimit, InvalidInput, EngineErrorResult]


# --------------------------------------------------------------------------
# T1 private helpers (pure; no other app.* imports)
# --------------------------------------------------------------------------

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


# --------------------------------------------------------------------------
# §4.2 Function signatures
# --------------------------------------------------------------------------


def validate_problem(problem: Problem) -> list[InputError]:
    errors: list[InputError] = []

    ids = [w.id for w in problem.workers]
    if len(ids) != len(set(ids)):
        errors.append(InputError("DUPLICATE_WORKER_ID", "worker ids must be unique"))

    for w in problem.workers:
        if not (0 <= w.min_hours <= w.max_hours):
            errors.append(InputError("INVALID_HOURS", f"min_hours must be <= max_hours for {w.id}",
                                      {"worker_id": w.id}))

    known_keys = {(s, r) for s in Shift for r in Role}
    for key, value in problem.demand.items():
        if key not in known_keys:
            errors.append(InputError("UNKNOWN_DEMAND_KEY", f"unknown demand key {key!r}"))
        elif not isinstance(value, int) or isinstance(value, bool) or value < 0:
            errors.append(InputError("INVALID_DEMAND_VALUE", f"demand value for {key!r} must be an int >= 0"))

    if not (1 <= problem.month <= 12):
        errors.append(InputError("INVALID_MONTH", f"month must be 1..12, got {problem.month}"))
        return errors  # month must be valid before anything month-derived is checked
    try:
        first_day, last_day = _month_bounds(problem.year, problem.month)
    except (ValueError, calendar.IllegalMonthError):
        errors.append(InputError("INVALID_MONTH", "invalid year/month"))
        return errors

    lo, hi = _pos(first_day, Shift.A), (_next_month_first_day(problem.year, problem.month), 0)
    ff = _pos(*problem.free_from)
    if not (lo <= ff <= hi):
        errors.append(InputError("FREE_FROM_OUT_OF_RANGE", "free_from must be within the month (+1 day)"))

    seen_fixed: set[tuple[str, date, Shift]] = set()
    for a in problem.fixed_assignments:
        if not (first_day <= a.date <= last_day):
            errors.append(InputError("FIXED_OUT_OF_MONTH", "fixed assignment outside the month",
                                      {"worker_id": a.worker_id, "date": a.date.isoformat()}))
        elif _pos(a.date, a.shift) >= ff:
            errors.append(InputError("FIXED_NOT_LOCKED", "fixed assignment is not before free_from",
                                      {"worker_id": a.worker_id, "date": a.date.isoformat()}))
        key = (a.worker_id, a.date, a.shift)
        if key in seen_fixed:
            errors.append(InputError("DUPLICATE_FIXED_ASSIGNMENT", "duplicate fixed assignment",
                                      {"worker_id": a.worker_id, "date": a.date.isoformat()}))
        seen_fixed.add(key)

    try:
        prev_last = _prev_month_last_day(problem.year, problem.month)
        next_first = _next_month_first_day(problem.year, problem.month)
        for a in problem.neighbor_assignments:
            if a.date not in (prev_last, next_first):
                errors.append(InputError("NEIGHBOR_WRONG_DATE", "neighbor assignment on a wrong date",
                                          {"worker_id": a.worker_id, "date": a.date.isoformat()}))
    except (ValueError, calendar.IllegalMonthError):
        pass

    if not errors:  # weight overflow guard needs valid demand/hours/month
        s_max = sum(w.min_hours for w in problem.workers if w.active)
        weight = s_max + 1
        free_slots = sum(
            _demand_of(problem, s, r)
            for d in _month_days(problem.year, problem.month)
            for s in (Shift.A, Shift.B, Shift.C)
            if _is_free(problem, d, s)
            for r in Role
        )
        if weight * free_slots + s_max >= 2**53:
            errors.append(InputError("WEIGHT_OVERFLOW", "W * free_slots + s_max would exceed 2**53"))

    return errors


def validate_roster(problem: Problem, assignments: Sequence[Assignment]) -> list[Violation]:
    worker_by_id = {w.id: w for w in problem.workers}
    first_day, last_day = _month_bounds(problem.year, problem.month)

    groups: dict[tuple[str, date, Shift], list[Assignment]] = {}
    for a in assignments:
        groups.setdefault((a.worker_id, a.date, a.shift), []).append(a)

    violations: list[Violation] = []

    for (worker_id, d, s), group in groups.items():
        if len(group) > 1:
            violations.append(Violation(ViolationCode.DUPLICATE_ASSIGNMENT, (worker_id, d, s),
                                         len(group) - 1, tuple(group)))
        first = group[0]
        worker = worker_by_id.get(worker_id)
        if worker is None:
            violations.append(Violation(ViolationCode.UNKNOWN_WORKER, (worker_id, d, s), 1, (first,)))
            continue
        if not worker.active:
            violations.append(Violation(ViolationCode.INACTIVE_WORKER, (worker_id, d, s), 1, (first,)))
        if first.role != worker.role:
            violations.append(Violation(ViolationCode.WRONG_ROLE, (worker_id, d, s), 1, (first,)))
        if not (first_day <= d <= last_day):
            violations.append(Violation(ViolationCode.OUT_OF_MONTH, (worker_id, d, s), 1, (first,)))
        if (_weekday(d), s) not in worker.availability:
            violations.append(Violation(ViolationCode.UNAVAILABLE, (worker_id, d, s), 1, (first,)))

    # DAILY_LIMIT: distinct shifts per (worker, date)
    by_worker_day: dict[tuple[str, date], set[Shift]] = {}
    for (worker_id, d, s) in groups:
        by_worker_day.setdefault((worker_id, d), set()).add(s)
    for (worker_id, d), shifts in by_worker_day.items():
        if len(shifts) > 2:
            assns = tuple(groups[(worker_id, d, s)][0] for s in sorted(shifts, key=lambda x: _SHIFT_ORDER[x]))
            violations.append(Violation(ViolationCode.DAILY_LIMIT, (worker_id, d), len(shifts) - 2, assns))

    # ADJACENT_SHIFTS: within-month pairs (only if the rule is on) + neighbor pairs (always)
    present: dict[str, set[tuple[date, Shift]]] = {}
    assn_at: dict[tuple[str, date, Shift], Assignment] = {}
    for (worker_id, d, s), group in groups.items():
        present.setdefault(worker_id, set()).add((d, s))
        assn_at[(worker_id, d, s)] = group[0]
    neighbor_at: dict[tuple[str, date, Shift], Assignment] = {
        (a.worker_id, a.date, a.shift): a for a in problem.neighbor_assignments
    }
    for worker_id, positions in present.items():
        for (d, s) in positions:
            for (d2, s2) in _adjacent_positions(d, s):
                if _pos(d2, s2) <= _pos(d, s):
                    continue  # only report once, from the earlier position
                later_in_month = (d2, s2) in positions
                later_is_neighbor = (worker_id, d2, s2) in neighbor_at
                if not (later_in_month or later_is_neighbor):
                    continue
                both_in_month = later_in_month and (d, s) in positions
                if both_in_month and not problem.forbid_adjacent_shifts:
                    continue
                if later_is_neighbor and (d, s) not in positions:
                    continue  # the earlier position isn't actually present for this worker
                pair_assns = (assn_at[(worker_id, d, s)],
                              neighbor_at[(worker_id, d2, s2)] if later_is_neighbor else assn_at[(worker_id, d2, s2)])
                violations.append(Violation(ViolationCode.ADJACENT_SHIFTS, (worker_id, d, s), 1, pair_assns))
        # neighbor -> in-month direction (earlier position is the neighbor assignment)
        for (nw_id, nd, ns), nassn in neighbor_at.items():
            if nw_id != worker_id:
                continue
            for (d2, s2) in _adjacent_positions(nd, ns):
                if (d2, s2) in positions and _pos(nd, ns) < _pos(d2, s2):
                    violations.append(Violation(ViolationCode.ADJACENT_SHIFTS, (worker_id, nd, ns), 1,
                                                 (nassn, assn_at[(worker_id, d2, s2)])))

    # MAX_HOURS
    hours: dict[str, int] = {}
    for (worker_id, d, s), group in groups.items():
        hours[worker_id] = hours.get(worker_id, 0) + 8 * len(group)
    for worker_id, assigned_hours in hours.items():
        worker = worker_by_id.get(worker_id)
        if worker is not None and assigned_hours > worker.max_hours:
            assns = tuple(g[0] for (wid, d, s), g in groups.items() if wid == worker_id)
            violations.append(Violation(ViolationCode.MAX_HOURS, (worker_id,),
                                         assigned_hours - worker.max_hours, assns))

    # OVERSTAFFED (by the assignment's snapshotted slot role)
    slot_counts: dict[tuple[date, Shift, Role], list[Assignment]] = {}
    for (worker_id, d, s), group in groups.items():
        for a in group:
            slot_counts.setdefault((d, s, a.role), []).append(a)
    for (d, s, r), assns in slot_counts.items():
        required = _demand_of(problem, s, r)
        if len(assns) > required:
            violations.append(Violation(ViolationCode.OVERSTAFFED, (d, s, r), len(assns) - required, tuple(assns)))

    return violations


def roster_metrics(problem: Problem, assignments: Sequence[Assignment]) -> Metrics:
    slot_counts: dict[tuple[date, Shift, Role], int] = {}
    for a in assignments:
        slot_counts[(a.date, a.shift, a.role)] = slot_counts.get((a.date, a.shift, a.role), 0) + 1
    hours: dict[str, int] = {}
    for a in assignments:
        hours[a.worker_id] = hours.get(a.worker_id, 0) + 8

    deficits = _slot_deficits(problem)

    gaps: list[CoverageGap] = []
    locked_uncovered = 0
    total_uncovered = 0
    for d in _month_days(problem.year, problem.month):
        for s in (Shift.A, Shift.B, Shift.C):
            locked = not _is_free(problem, d, s)
            for r in Role:
                required = _demand_of(problem, s, r)
                if required == 0:
                    continue
                assigned = slot_counts.get((d, s, r), 0)
                missing = max(0, required - assigned)
                proven_missing = missing if locked else min(missing, deficits.get((d, s, r), 0))
                gaps.append(CoverageGap(d, s, r, required, assigned, missing, proven_missing, locked))
                if locked:
                    locked_uncovered += missing
                total_uncovered += missing

    shortfalls = []
    for w in problem.workers:
        if not w.active:
            continue
        assigned_hours = hours.get(w.id, 0)
        missing_hours = max(0, w.min_hours - assigned_hours)
        if missing_hours > 0:
            shortfalls.append(HourShortfall(w.id, w.min_hours, assigned_hours, missing_hours))

    return Metrics(tuple(gaps), tuple(shortfalls), locked_uncovered, total_uncovered)


def worsened(before: list[Violation], after: list[Violation]) -> list[Violation]:
    before_mag: dict[tuple, int] = {}
    for v in before:
        k = (v.code, v.key)
        before_mag[k] = max(before_mag.get(k, 0), v.magnitude)
    result = []
    for v in after:
        k = (v.code, v.key)
        if k not in before_mag or v.magnitude > before_mag[k]:
            result.append(v)
    return result


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


def _run_cp_sat(model: cp_model.CpModel, config: SolverConfig) -> RawSolve:
    """Test seam (§4.2): the only function that calls into CP-SAT.
    Tests can mock it to force any status."""
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = config.time_limit_s
    solver.parameters.num_search_workers = config.num_workers
    solver.parameters.random_seed = config.random_seed
    status = solver.Solve(model)
    # Collect values for all named variables we created (x[...] / short[...]).
    values = {}
    proto = model.Proto()
    for i, v in enumerate(proto.variables):
        if v.name:
            values[v.name] = solver.Value(model.GetIntVarFromProtoIndex(i))
    return RawSolve(solver.StatusName(status), values, solver.ObjectiveValue() if status in
                     (cp_model.OPTIMAL, cp_model.FEASIBLE) else float("nan"),
                     solver.BestObjectiveBound(), solver.WallTime())


def _coverage_lower_bound(bound: float, s_max: int, weight: int, locked_uncovered: int, diag_free: int) -> int:
    b = math.ceil(bound - 1e-6)
    lb_free = max(0, _ceil_div(b - s_max, weight))
    return locked_uncovered + max(lb_free, diag_free)


def solve(problem: Problem, config: SolverConfig) -> ScheduleResult:
    t_start = time.perf_counter()

    t0 = time.perf_counter()
    errors = validate_problem(problem)
    input_validation_s = time.perf_counter() - t0
    if errors:
        return InvalidInput(kind="invalid_input", errors=tuple(errors))

    t0 = time.perf_counter()
    diag = diagnose(problem)
    diagnostics_s = time.perf_counter() - t0

    active = [w for w in problem.workers if w.active]
    s_max = sum(w.min_hours for w in active)
    weight = s_max + 1

    t0 = time.perf_counter()
    model = cp_model.CpModel()
    _, fixed_slot, fixed_day, fixed_hours = _fixed_index(problem)
    days = _month_days(problem.year, problem.month)

    x_vars: dict[tuple[str, date, Shift], cp_model.IntVar] = {}
    for w in active:
        for d in days:
            for s in _eligible_free_shifts(problem, w, d):
                x_vars[(w.id, d, s)] = model.NewBoolVar(_var_name_x(w.id, d, s))

    # monthly limit
    for w in active:
        cap_shifts = _remaining_max_shifts(w, fixed_hours)
        my_vars = [v for (wid, d, s), v in x_vars.items() if wid == w.id]
        if my_vars:
            model.Add(sum(my_vars) <= cap_shifts)

    # daily limit
    for w in active:
        for d in days:
            day_vars = [x_vars[(w.id, d, s)] for s in (Shift.A, Shift.B, Shift.C) if (w.id, d, s) in x_vars]
            if day_vars:
                model.Add(sum(day_vars) <= max(0, 2 - fixed_day.get((w.id, d), 0)))

    # adjacency between two free variables (only if the rule is on)
    if problem.forbid_adjacent_shifts:
        seen_pairs = set()
        for (wid, d, s) in list(x_vars):
            for (d2, s2) in _adjacent_positions(d, s):
                if (wid, d2, s2) in x_vars and (wid, d, s) not in seen_pairs and (wid, d2, s2) not in seen_pairs:
                    pair_key = (wid, min((d, s), (d2, s2), key=lambda p: _pos(*p)))
                    if pair_key in seen_pairs:
                        continue
                    seen_pairs.add(pair_key)
                    model.Add(x_vars[(wid, d, s)] + x_vars[(wid, d2, s2)] <= 1)

    # no overstaffing + uncovered expressions (free slots only)
    uncovered_terms = []
    for d in days:
        for s in (Shift.A, Shift.B, Shift.C):
            if not _is_free(problem, d, s):
                continue
            for r in Role:
                required = max(0, _demand_of(problem, s, r) - fixed_slot.get((d, s, r), 0))
                slot_vars = [v for (wid, dd, ss), v in x_vars.items()
                             if dd == d and ss == s and next(w for w in active if w.id == wid).role is r]
                if required == 0 and not slot_vars:
                    continue
                if slot_vars:
                    model.Add(sum(slot_vars) <= required)
                uncovered_terms.append(required - (sum(slot_vars) if slot_vars else 0))

    # short[w]
    short_vars = {}
    for w in active:
        sv = model.NewIntVar(0, w.min_hours, _var_name_short(w.id))
        my_vars = [v for (wid, d, s), v in x_vars.items() if wid == w.id]
        model.Add(sv >= w.min_hours - 8 * (sum(my_vars) if my_vars else 0) - fixed_hours.get(w.id, 0))
        short_vars[w.id] = sv

    model.Minimize(weight * sum(uncovered_terms) + sum(short_vars.values()))
    model_build_s = time.perf_counter() - t0

    t0 = time.perf_counter()
    raw = _run_cp_sat(model, config)
    search_s = time.perf_counter() - t0

    def _timings(roster_validation_s: float) -> Timings:
        return Timings(input_validation_s, diagnostics_s, model_build_s, search_s, roster_validation_s,
                        time.perf_counter() - t_start)

    if raw.status == "UNKNOWN":
        lb = _coverage_lower_bound(raw.bound, s_max, weight, 0, 0)
        # locked_uncovered still contributes; compute it without needing a roster
        locked_uncovered = sum(
            max(0, _demand_of(problem, s, r) - fixed_slot.get((d, s, r), 0)) if not _is_free(problem, d, s) else 0
            for d in days for s in (Shift.A, Shift.B, Shift.C) for r in Role
        )
        lb = _coverage_lower_bound(raw.bound, s_max, weight, locked_uncovered, diag.total_lower_bound)
        return NoSolutionWithinLimit(kind="no_solution_within_limit", coverage_lower_bound=lb,
                                      diagnostics=diag, timings=_timings(0.0))

    if raw.status not in ("OPTIMAL", "FEASIBLE"):
        return EngineErrorResult(kind="engine_error", solver_status=raw.status,
                                  message=f"CP-SAT returned {raw.status}", diagnostics=diag,
                                  timings=_timings(0.0))

    new_assignments = []
    for (wid, d, s), var in x_vars.items():
        if raw.values.get(var.Name(), 0):
            role = next(w for w in active if w.id == wid).role
            new_assignments.append(Assignment(wid, d, s, role))
    full = list(problem.fixed_assignments) + new_assignments

    t0 = time.perf_counter()
    v_fixed = validate_roster(problem, problem.fixed_assignments)
    v_full = validate_roster(problem, full)
    gate_failures = worsened(v_fixed, v_full)
    roster_validation_s = time.perf_counter() - t0

    if gate_failures:
        return EngineErrorResult(kind="engine_error", solver_status=raw.status,
                                  message="validation gate rejected the candidate roster",
                                  diagnostics=diag, timings=_timings(roster_validation_s))

    metrics = roster_metrics(problem, full)
    lower_bound = _coverage_lower_bound(raw.bound, s_max, weight, metrics.locked_uncovered, diag.total_lower_bound)
    coverage_status = "OPTIMAL" if lower_bound == metrics.total_uncovered else "FEASIBLE"
    total_shortfall = sum(hs.missing_hours for hs in metrics.hour_shortfalls)
    min_hours_status = "OPTIMAL" if raw.status == "OPTIMAL" else "FEASIBLE"

    return Solved(
        kind="solved",
        assignments=tuple(full),
        coverage_gaps=metrics.coverage_gaps,
        hour_shortfalls=metrics.hour_shortfalls,
        coverage=CoverageStatus(coverage_status, metrics.total_uncovered, metrics.locked_uncovered, lower_bound),
        min_hours=MinHoursStatus(min_hours_status, total_shortfall),
        lexicographically_optimal=(raw.status == "OPTIMAL"),
        preexisting_violations=tuple(v_full),
        objective=ObjectiveInfo(weight, s_max, raw.objective, raw.bound),
        free_from=problem.free_from,
        diagnostics=diag,
        timings=_timings(roster_validation_s),
    )
