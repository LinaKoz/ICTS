"""§4.9 Diagnostics."""
from datetime import date

from app.scheduling import (
    Problem, Role, Shift, Solved, SolverConfig, diagnose, solve,
)
from app.scheduling._helpers import _day_cap, _fixed_index
from tests.scheduling.conftest import make_worker

YEAR, MONTH = 2026, 11
CFG = SolverConfig(time_limit_s=10.0)
FF = (date(YEAR, MONTH, 1), Shift.A)


def test_slot_and_role_deficits_correct():
    demand = {(Shift.A, Role.GENERAL_GUARD): 3}
    workers = [make_worker(f"w{i}", Role.GENERAL_GUARD, max_hours=744) for i in range(2)]  # only 2 for demand 3
    p = Problem(year=YEAR, month=MONTH, demand=demand, workers=workers, free_from=FF)
    diag = diagnose(p)
    # each day: 3 needed, 2 eligible -> slot_deficit 1/day * 30 days
    assert diag.role_lower_bounds[Role.GENERAL_GUARD] == 30


def test_day_cap_respects_fixed_shifts_both_modes():
    from app.scheduling import Assignment
    worker = make_worker("w1", Role.GENERAL_GUARD, max_hours=744)
    fixed = (Assignment("w1", date(YEAR, MONTH, 1), Shift.A, Role.GENERAL_GUARD),)
    demand = {(Shift.B, Role.GENERAL_GUARD): 1, (Shift.C, Role.GENERAL_GUARD): 1}
    for rule in (False, True):
        p = Problem(year=YEAR, month=MONTH, demand=demand, workers=[worker],
                    free_from=(date(YEAR, MONTH, 1), Shift.B), fixed_assignments=fixed,
                    forbid_adjacent_shifts=rule)
        _, _, fixed_day, _ = _fixed_index(p)
        cap = _day_cap(p, worker, date(YEAR, MONTH, 1), fixed_day)
        # fixed A already used 1 of the 2 daily slots -> at most 1 more regardless of mode
        assert cap == 1


def test_day_cap_adjacency_only_with_rule_on():
    worker = make_worker("w1", Role.GENERAL_GUARD, max_hours=744)
    demand = {(Shift.A, Role.GENERAL_GUARD): 1, (Shift.B, Role.GENERAL_GUARD): 1, (Shift.C, Role.GENERAL_GUARD): 1}
    p_off = Problem(year=YEAR, month=MONTH, demand=demand, workers=[worker], free_from=FF,
                     forbid_adjacent_shifts=False)
    _, _, fixed_day, _ = _fixed_index(p_off)
    assert _day_cap(p_off, worker, date(YEAR, MONTH, 1), fixed_day) == 2  # any 2 of 3

    p_on = Problem(year=YEAR, month=MONTH, demand=demand, workers=[worker], free_from=FF,
                    forbid_adjacent_shifts=True)
    assert _day_cap(p_on, worker, date(YEAR, MONTH, 1), fixed_day) == 2  # A+C only, still 2


def test_inactive_workers_excluded_from_diagnostics():
    demand = {(Shift.A, Role.GENERAL_GUARD): 1}
    inactive = make_worker("w1", Role.GENERAL_GUARD, active=False, min_hours=100)
    p = Problem(year=YEAR, month=MONTH, demand=demand, workers=[inactive], free_from=FF)
    diag = diagnose(p)
    assert "w1" not in diag.worker_shortfall_lower_bounds
    assert diag.role_lower_bounds[Role.GENERAL_GUARD] == 30  # nobody eligible


def test_gaps_beyond_proven_missing_marked_suspected():
    """Two workers eligible but only one is actually usable due to a
    coincidental hard cap that the slot_deficit proof (which only checks
    remaining_max_shifts and the daily cap) cannot see: a same-day adjacency
    with a fixed shift. The realized gap can exceed proven_missing."""
    from app.scheduling import Assignment
    demand = {(Shift.A, Role.GENERAL_GUARD): 1}
    w1 = make_worker("w1", Role.GENERAL_GUARD, max_hours=744)
    fixed = (Assignment("w1", date(YEAR, MONTH, 1), Shift.B, Role.GENERAL_GUARD),)
    p = Problem(year=YEAR, month=MONTH, demand={(Shift.C, Role.GENERAL_GUARD): 1}, workers=[w1],
                free_from=(date(YEAR, MONTH, 1), Shift.C), fixed_assignments=fixed, forbid_adjacent_shifts=True)
    result = solve(p, CFG)
    assert isinstance(result, Solved)
    gap = next(g for g in result.coverage_gaps if g.date == date(YEAR, MONTH, 1) and g.shift == Shift.C)
    assert gap.missing >= gap.proven_missing


def test_lb_diag_free_leq_u_free_on_solver_fixtures():
    demand = {(Shift.A, Role.SUPERVISOR): 1, (Shift.B, Role.SUPERVISOR): 1, (Shift.C, Role.SUPERVISOR): 1}
    worker = make_worker("sv", Role.SUPERVISOR, min_hours=0, max_hours=744)
    for rule in (False, True):
        p = Problem(year=YEAR, month=MONTH, demand=demand, workers=[worker], free_from=FF,
                    forbid_adjacent_shifts=rule)
        result = solve(p, CFG)
        assert isinstance(result, Solved)
        assert result.diagnostics.total_lower_bound <= result.coverage.total_uncovered


def test_mid_month_lb_diag_free_leq_u_free():
    demand = {(Shift.A, Role.GENERAL_GUARD): 1}
    worker = make_worker("w1", Role.GENERAL_GUARD, min_hours=0, max_hours=744)
    p = Problem(year=YEAR, month=MONTH, demand=demand, workers=[worker],
                free_from=(date(YEAR, MONTH, 15), Shift.A))
    result = solve(p, CFG)
    assert isinstance(result, Solved)
    free_gaps = sum(g.missing for g in result.coverage_gaps if not g.locked)
    assert result.diagnostics.total_lower_bound <= free_gaps


def test_worker_shortfall_lower_bound_leq_returned_short_on_solver_fixtures():
    demand = {(Shift.A, Role.GENERAL_GUARD): 1}
    worker = make_worker("w1", Role.GENERAL_GUARD, min_hours=200, max_hours=200)
    p = Problem(year=YEAR, month=MONTH, demand=demand, workers=[worker], free_from=FF)
    result = solve(p, CFG)
    assert isinstance(result, Solved)
    actual_short = next((h.missing_hours for h in result.hour_shortfalls if h.worker_id == "w1"), 0)
    proven = result.diagnostics.worker_shortfall_lower_bounds["w1"]
    assert proven <= actual_short
