"""Ranked candidates for an unfilled free slot (§6 "Suggestions", bonus 2).

Pure: takes a `Problem` plus the current assignments and returns
candidates; no I/O, no solver. A candidate is an active, contracted
worker of the slot's role whose addition leaves `worsened(before,
after)` empty (availability, daily limit, max hours, adjacency where
the rule applies, ...). Ranked by min-hour deficit (descending), then
assigned hours (ascending), then name.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from app.scheduling.types import Assignment, Problem, Role, Shift, validate_roster, worsened

SlotState = str  # "OPEN" | "FILLED" | "LOCKED"

_ROLE_LABEL = {Role.GENERAL_GUARD: "General guard", Role.SCREENER: "Screener", Role.SUPERVISOR: "Supervisor"}


@dataclass(frozen=True)
class Candidate:
    worker_id: str
    full_name: str
    assigned_hours: int
    min_hours: int
    hours_below_minimum: int
    shifts_that_day: int
    reasons: tuple[str, ...]


def slot_state(problem: Problem, assignments: Sequence[Assignment], d: date, shift: Shift, role: Role) -> SlotState:
    if (d, _order(shift)) < (problem.free_from[0], _order(problem.free_from[1])):
        return "LOCKED"
    demand = problem.demand.get((shift, role), 0)
    filled = sum(1 for a in assignments if a.date == d and a.shift == shift and a.role == role)
    return "OPEN" if filled < demand else "FILLED"


def _order(s: Shift) -> int:
    return {Shift.A: 0, Shift.B: 1, Shift.C: 2}[s]


def suggest(
    problem: Problem,
    assignments: Sequence[Assignment],
    d: date,
    shift: Shift,
    role: Role,
    names: Mapping[str, str],
) -> tuple[SlotState, list[Candidate]]:
    state = slot_state(problem, assignments, d, shift, role)
    if state != "OPEN":
        return state, []

    before = validate_roster(problem, assignments)
    hours = _hours(assignments)

    candidates: list[Candidate] = []
    for w in problem.workers:
        if not w.active or w.role != role:
            continue
        if any(a.worker_id == w.id and a.date == d and a.shift == shift for a in assignments):
            continue
        trial = [*assignments, Assignment(w.id, d, shift, role)]
        if worsened(before, validate_roster(problem, trial)):
            continue
        candidates.append(_candidate(w, assignments, hours, d, shift, role, names))
    return state, _ranked(candidates)


def replacements(
    problem: Problem,
    assignments: Sequence[Assignment],
    target: Assignment,
    names: Mapping[str, str],
    limit: int = 5,
) -> tuple[SlotState, list[Candidate]]:
    """Up to `limit` workers who could take over `target`'s slot. The check
    is the move gate of P10: swapping the worker must not leave the roster
    with a new or worsened violation (an existing one, such as the target
    being inactive, is what the swap is meant to fix). A started shift
    is LOCKED and has no replacements."""
    if (target.date, _order(target.shift)) < (problem.free_from[0], _order(problem.free_from[1])):
        return "LOCKED", []

    before = validate_roster(problem, assignments)
    rest = [a for a in assignments if a != target]
    hours = _hours(rest)

    candidates: list[Candidate] = []
    for w in problem.workers:
        if not w.active or w.role != target.role or w.id == target.worker_id:
            continue
        if any(a.worker_id == w.id and a.date == target.date and a.shift == target.shift for a in rest):
            continue
        swapped = [*rest, Assignment(w.id, target.date, target.shift, target.role)]
        if worsened(before, validate_roster(problem, swapped)):
            continue
        candidates.append(_candidate(w, rest, hours, target.date, target.shift, target.role, names))
    return "FILLED", _ranked(candidates)[:limit]


def _hours(assignments: Sequence[Assignment]) -> dict[str, int]:
    hours: dict[str, int] = {}
    for a in assignments:
        hours[a.worker_id] = hours.get(a.worker_id, 0) + 8
    return hours


def _ranked(candidates: list[Candidate]) -> list[Candidate]:
    return sorted(candidates, key=lambda c: (-c.hours_below_minimum, c.assigned_hours, c.full_name, c.worker_id))


def _candidate(
    w, assignments: Sequence[Assignment], hours: Mapping[str, int], d: date, shift: Shift, role: Role,
    names: Mapping[str, str],
) -> Candidate:
    assigned = hours.get(w.id, 0)
    below = max(0, w.min_hours - assigned)
    that_day = len({a.shift for a in assignments if a.worker_id == w.id and a.date == d})
    reasons = [
        _ROLE_LABEL[role],
        f"available {d.strftime('%a')} {shift.value}",
        f"{assigned}/{w.min_hours} h" + (f" ({below} h below minimum)" if below else " (minimum met)"),
        f"{that_day} shift{'s' if that_day != 1 else ''} that day",
    ]
    return Candidate(w.id, names.get(w.id, w.id), assigned, w.min_hours, below, that_day, tuple(reasons))
