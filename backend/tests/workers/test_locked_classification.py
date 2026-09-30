"""P2/D8: a new violation is `locked` only if editing free assignments cannot fix it."""
from __future__ import annotations

from datetime import date

from app.changes.service import is_locked_violation
from app.scheduling import Assignment, Role, Shift, Violation, ViolationCode

MONTH = date(2026, 9, 1)
FREE_FROM = (date(2026, 9, 15), Shift.C)


def _a(day: int, shift: Shift = Shift.A) -> Assignment:
    return Assignment("1", date(2026, 9, day), shift, Role.GENERAL_GUARD)


def test_single_assignment_violations():
    started = Violation(ViolationCode.UNAVAILABLE, ("1", date(2026, 9, 10), Shift.A), 1, (_a(10),))
    upcoming = Violation(ViolationCode.UNAVAILABLE, ("1", date(2026, 9, 20), Shift.A), 1, (_a(20),))
    assert is_locked_violation(started, MONTH, FREE_FROM) is True
    assert is_locked_violation(upcoming, MONTH, FREE_FROM) is False


def test_max_hours_counts_eight_hours_per_free_assignment():
    # 3 started + 1 upcoming shifts, over the maximum by 16 h: removing the one free shift (8 h) is not enough.
    over16 = Violation(ViolationCode.MAX_HOURS, ("1",), 16, (_a(1), _a(2), _a(3), _a(20)))
    assert is_locked_violation(over16, MONTH, FREE_FROM) is True
    over8 = Violation(ViolationCode.MAX_HOURS, ("1",), 8, (_a(1), _a(2), _a(3), _a(20)))
    assert is_locked_violation(over8, MONTH, FREE_FROM) is False


def test_adjacent_pair_is_fixable_if_either_side_is_free():
    pair = Violation(ViolationCode.ADJACENT_SHIFTS, ("1", date(2026, 9, 15), Shift.B), 1, (_a(15, Shift.B), _a(15, Shift.C)))
    assert is_locked_violation(pair, MONTH, FREE_FROM) is False  # 15/09 C is upcoming
    both_started = Violation(ViolationCode.ADJACENT_SHIFTS, ("1", date(2026, 9, 10), Shift.A), 1, (_a(10), _a(10, Shift.B)))
    assert is_locked_violation(both_started, MONTH, FREE_FROM) is True


def test_neighbour_month_assignment_is_not_editable_here():
    neighbour = Assignment("1", date(2026, 8, 31), Shift.C, Role.GENERAL_GUARD)
    started_pair = Violation(ViolationCode.ADJACENT_SHIFTS, ("1", date(2026, 8, 31), Shift.C), 1, (neighbour, _a(1)))
    assert is_locked_violation(started_pair, MONTH, FREE_FROM) is True
    free_pair = Violation(ViolationCode.ADJACENT_SHIFTS, ("1", date(2026, 8, 31), Shift.C), 1, (neighbour, _a(20)))
    assert is_locked_violation(free_pair, MONTH, FREE_FROM) is False
