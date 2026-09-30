"""Input validation, the independent roster validator and roster metrics.

`validate_roster` is the gate every engine result passes and the same
check the application runs on stored rosters and manual edits.
"""
from __future__ import annotations

import calendar
from collections.abc import Sequence
from datetime import date

from ._helpers import (
    _SHIFT_ORDER,
    _adjacent_positions,
    _demand_of,
    _is_free,
    _month_bounds,
    _month_days,
    _next_month_first_day,
    _pos,
    _prev_month_last_day,
    _weekday,
)
from .diagnostics import _slot_deficits
from .types import (
    Assignment,
    CoverageGap,
    HourShortfall,
    InputError,
    Metrics,
    Problem,
    Role,
    Shift,
    Violation,
    ViolationCode,
)


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
