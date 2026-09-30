"""§4.9 Locked/free separation and feasibility invariant."""
from datetime import date

from app.scheduling import (
    Assignment, Problem, Role, Shift, Solved, SolverConfig, ViolationCode, solve,
)
from tests.scheduling.conftest import make_worker

YEAR, MONTH = 2026, 11
CFG = SolverConfig(time_limit_s=10.0)


def test_mid_month_locked_and_free_gaps():
    """Locked slots (days 1-14) have no worker at all (locked gaps). Free
    slots (day 15 onward) are fully coverable."""
    demand = {(Shift.A, Role.GENERAL_GUARD): 1}
    worker = make_worker("w1", Role.GENERAL_GUARD, min_hours=0, max_hours=744)
    free_from = (date(YEAR, MONTH, 15), Shift.A)
    p = Problem(year=YEAR, month=MONTH, demand=demand, workers=[worker], free_from=free_from)
    result = solve(p, CFG)
    assert isinstance(result, Solved)

    locked_gaps = sum(g.missing for g in result.coverage_gaps if g.locked)
    free_gaps = sum(g.missing for g in result.coverage_gaps if not g.locked)
    assert result.coverage.locked_uncovered == locked_gaps == 14  # days 1-14, all uncovered
    assert free_gaps == 0  # days 15-30 fully covered
    assert result.coverage.total_uncovered == result.coverage.locked_uncovered + free_gaps
    assert result.coverage.lower_bound <= result.coverage.total_uncovered
    # no locked gap counted in the diagnostic's free-only bound
    assert result.diagnostics.total_lower_bound == 0


def test_all_locked_uncovered_free_fully_coverable_lower_bound_equals_locked():
    demand = {(Shift.A, Role.GENERAL_GUARD): 1}
    worker = make_worker("w1", Role.GENERAL_GUARD, min_hours=0, max_hours=744)
    free_from = (date(YEAR, MONTH, 10), Shift.A)
    p = Problem(year=YEAR, month=MONTH, demand=demand, workers=[worker], free_from=free_from)
    result = solve(p, CFG)
    assert isinstance(result, Solved)
    assert result.coverage.lower_bound == result.coverage.locked_uncovered


def test_zero_roster_invariant_retroactive_conflict():
    """Fixed hours exceed the reduced cap, a fixed adjacent pair, and a fixed
    inactive-worker assignment; the free portion has zero demand so x=0 is
    the only (and thus optimal) new-assignment set. Must be OPTIMAL, never
    INFEASIBLE, and every existing violation stays visible."""
    fixed = (
        Assignment("w1", date(YEAR, MONTH, 1), Shift.A, Role.GENERAL_GUARD),
        Assignment("w1", date(YEAR, MONTH, 1), Shift.B, Role.GENERAL_GUARD),  # adjacent pair, rule on
        Assignment("w2", date(YEAR, MONTH, 2), Shift.A, Role.GENERAL_GUARD),  # w2 is inactive
    )
    w1 = make_worker("w1", Role.GENERAL_GUARD, min_hours=0, max_hours=8)  # 16h fixed > 8h cap
    w2 = make_worker("w2", Role.GENERAL_GUARD, active=False)
    free_from = (date(YEAR, MONTH, 5), Shift.A)  # no demand at/after this point -> no free vars
    p = Problem(year=YEAR, month=MONTH, demand={}, workers=[w1, w2], free_from=free_from,
                fixed_assignments=fixed, forbid_adjacent_shifts=True)
    result = solve(p, CFG)
    assert isinstance(result, Solved)
    assert result.coverage.status == "OPTIMAL"
    codes = {v.code for v in result.preexisting_violations}
    assert ViolationCode.MAX_HOURS in codes
    assert ViolationCode.ADJACENT_SHIFTS in codes
    assert ViolationCode.INACTIVE_WORKER in codes
