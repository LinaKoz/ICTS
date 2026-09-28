"""§4.9 Fixed assignments and existing violations."""
from datetime import date

from app.scheduling.types import (
    Assignment, Problem, Role, Shift, Solved, SolverConfig, ViolationCode, Weekday, solve,
)
from tests.scheduling.conftest import make_worker

YEAR, MONTH = 2026, 11
CFG = SolverConfig(time_limit_s=10.0)
D1 = date(YEAR, MONTH, 1)
D2 = date(YEAR, MONTH, 2)


def test_retroactive_cap_reduction_fixed_over_new_max_hours():
    """fixed 80h, max_hours lowered to 64: Solved, no new assignments for
    that worker, MAX_HOURS magnitude 16, gate accepts."""
    fixed = tuple(Assignment("w1", date(YEAR, MONTH, d), Shift.A, Role.GENERAL_GUARD) for d in range(1, 11))
    worker = make_worker("w1", Role.GENERAL_GUARD, min_hours=0, max_hours=64)
    p = Problem(year=YEAR, month=MONTH, demand={(Shift.A, Role.GENERAL_GUARD): 1}, workers=[worker],
                free_from=(date(YEAR, MONTH, 15), Shift.A), fixed_assignments=fixed)
    result = solve(p, CFG)
    assert isinstance(result, Solved)
    assert not any(a.worker_id == "w1" and a.date >= date(YEAR, MONTH, 15) for a in result.assignments)
    mh = [v for v in result.preexisting_violations if v.code == ViolationCode.MAX_HOURS]
    assert len(mh) == 1 and mh[0].magnitude == 16


def test_retroactive_cap_reduction_at_most_one_new_shift():
    """fixed 56h with a 64h maximum: at most 1 new shift (8h room left)."""
    fixed = tuple(Assignment("w1", date(YEAR, MONTH, d), Shift.A, Role.GENERAL_GUARD) for d in range(1, 8))
    worker = make_worker("w1", Role.GENERAL_GUARD, min_hours=0, max_hours=64)
    p = Problem(year=YEAR, month=MONTH, demand={(Shift.A, Role.GENERAL_GUARD): 1}, workers=[worker],
                free_from=(date(YEAR, MONTH, 15), Shift.A), fixed_assignments=fixed)
    result = solve(p, CFG)
    assert isinstance(result, Solved)
    new_for_w1 = [a for a in result.assignments if a.worker_id == "w1" and a.date >= date(YEAR, MONTH, 15)]
    assert len(new_for_w1) <= 1


def test_adjacency_to_fixed_shift_rule_on_fixed_b_blocks_free_c():
    worker = make_worker("w1", Role.GENERAL_GUARD, min_hours=0, max_hours=744)
    fixed = (Assignment("w1", D1, Shift.B, Role.GENERAL_GUARD),)
    p = Problem(year=YEAR, month=MONTH, demand={(Shift.C, Role.GENERAL_GUARD): 1}, workers=[worker],
                free_from=(D1, Shift.C), fixed_assignments=fixed, forbid_adjacent_shifts=True)
    result = solve(p, CFG)
    assert isinstance(result, Solved)
    assert not any(a.worker_id == "w1" and a.date == D1 and a.shift == Shift.C for a in result.assignments)


def test_adjacency_to_fixed_shift_rule_on_fixed_c_prev_day_blocks_free_a():
    worker = make_worker("w1", Role.GENERAL_GUARD, min_hours=0, max_hours=744)
    fixed = (Assignment("w1", D1, Shift.C, Role.GENERAL_GUARD),)
    p = Problem(year=YEAR, month=MONTH, demand={(Shift.A, Role.GENERAL_GUARD): 1}, workers=[worker],
                free_from=(D2, Shift.A), fixed_assignments=fixed, forbid_adjacent_shifts=True)
    result = solve(p, CFG)
    assert isinstance(result, Solved)
    assert not any(a.worker_id == "w1" and a.date == D2 and a.shift == Shift.A for a in result.assignments)


def test_adjacency_to_fixed_shift_rule_on_fixed_a_allows_free_c_same_day():
    worker = make_worker("w1", Role.GENERAL_GUARD, min_hours=0, max_hours=744)
    fixed = (Assignment("w1", D1, Shift.A, Role.GENERAL_GUARD),)
    p = Problem(year=YEAR, month=MONTH, demand={(Shift.C, Role.GENERAL_GUARD): 1}, workers=[worker],
                free_from=(D1, Shift.C), fixed_assignments=fixed, forbid_adjacent_shifts=True)
    result = solve(p, CFG)
    assert isinstance(result, Solved)
    assert any(a.worker_id == "w1" and a.date == D1 and a.shift == Shift.C for a in result.assignments)


def test_fixed_shift_with_rule_off_allows_adjacent_free_shift():
    worker = make_worker("w1", Role.GENERAL_GUARD, min_hours=0, max_hours=744)
    fixed = (Assignment("w1", D1, Shift.B, Role.GENERAL_GUARD),)
    p = Problem(year=YEAR, month=MONTH, demand={(Shift.C, Role.GENERAL_GUARD): 1}, workers=[worker],
                free_from=(D1, Shift.C), fixed_assignments=fixed, forbid_adjacent_shifts=False)
    result = solve(p, CFG)
    assert isinstance(result, Solved)
    assert any(a.worker_id == "w1" and a.date == D1 and a.shift == Shift.C for a in result.assignments)


def test_neighbor_month_prev_c_blocks_1st_a():
    worker = make_worker("w1", Role.GENERAL_GUARD, min_hours=0, max_hours=744)
    prev_last = date(YEAR, MONTH - 1, 31)
    neighbor = (Assignment("w1", prev_last, Shift.C, Role.GENERAL_GUARD),)
    for rule in (False, True):
        p = Problem(year=YEAR, month=MONTH, demand={(Shift.A, Role.GENERAL_GUARD): 1}, workers=[worker],
                    free_from=(D1, Shift.A), neighbor_assignments=neighbor, forbid_adjacent_shifts=rule)
        result = solve(p, CFG)
        assert isinstance(result, Solved)
        assert not any(a.worker_id == "w1" and a.date == D1 and a.shift == Shift.A for a in result.assignments)


def test_neighbor_month_next_a_blocks_last_day_c():
    worker = make_worker("w1", Role.GENERAL_GUARD, min_hours=0, max_hours=744)
    last_day = date(YEAR, MONTH, 30)
    next_first = date(YEAR, MONTH + 1, 1)
    neighbor = (Assignment("w1", next_first, Shift.A, Role.GENERAL_GUARD),)
    for rule in (False, True):
        p = Problem(year=YEAR, month=MONTH, demand={(Shift.C, Role.GENERAL_GUARD): 1}, workers=[worker],
                    free_from=(last_day, Shift.C), neighbor_assignments=neighbor, forbid_adjacent_shifts=rule)
        result = solve(p, CFG)
        assert isinstance(result, Solved)
        assert not any(a.worker_id == "w1" and a.date == last_day and a.shift == Shift.C
                       for a in result.assignments)


def test_mid_day_cutoff_daily_limit_counts_fixed_shifts():
    worker = make_worker("w1", Role.GENERAL_GUARD, min_hours=0, max_hours=744)
    fixed = (Assignment("w1", D1, Shift.A, Role.GENERAL_GUARD), Assignment("w1", D1, Shift.B, Role.GENERAL_GUARD))
    p = Problem(year=YEAR, month=MONTH, demand={(Shift.C, Role.GENERAL_GUARD): 1}, workers=[worker],
                free_from=(D1, Shift.C), fixed_assignments=fixed)
    result = solve(p, CFG)
    assert isinstance(result, Solved)
    # A and B unchanged
    assert Assignment("w1", D1, Shift.A, Role.GENERAL_GUARD) in result.assignments
    assert Assignment("w1", D1, Shift.B, Role.GENERAL_GUARD) in result.assignments
    # daily limit (2/day) already used up by the fixed A+B, so C cannot go to w1
    assert not any(a.worker_id == "w1" and a.date == D1 and a.shift == Shift.C for a in result.assignments)


def test_other_existing_violations_returned_unchanged_model_stays_feasible():
    inactive = make_worker("w1", Role.GENERAL_GUARD, active=False)
    fixed = (Assignment("w1", D1, Shift.A, Role.GENERAL_GUARD),)
    p = Problem(year=YEAR, month=MONTH, demand={(Shift.A, Role.GENERAL_GUARD): 1}, workers=[inactive],
                free_from=(D2, Shift.A), fixed_assignments=fixed)
    result = solve(p, CFG)
    assert isinstance(result, Solved)
    assert Assignment("w1", D1, Shift.A, Role.GENERAL_GUARD) in result.assignments
    assert any(v.code == ViolationCode.INACTIVE_WORKER and v.magnitude == 1 for v in result.preexisting_violations)


def test_fully_locked_month_returns_fixed_unchanged_optimal():
    worker = make_worker("w1", Role.GENERAL_GUARD, min_hours=0, max_hours=744)
    fixed = tuple(Assignment("w1", date(YEAR, MONTH, d), Shift.A, Role.GENERAL_GUARD) for d in range(1, 31))
    next_first = date(YEAR, MONTH + 1, 1)
    p = Problem(year=YEAR, month=MONTH, demand={(Shift.A, Role.GENERAL_GUARD): 1}, workers=[worker],
                free_from=(next_first, Shift.A), fixed_assignments=fixed)
    result = solve(p, CFG)
    assert isinstance(result, Solved)
    assert set(result.assignments) == set(fixed)
    assert result.coverage.status == "OPTIMAL"
    assert result.lexicographically_optimal is True


def test_gate_rejects_worse_than_fixed_via_mocked_solution(monkeypatch):
    """An injected solution that adds a shift to a worker already over the
    cap (magnitude 16 -> 24) is rejected, even though the key is the same."""
    import app.scheduling.types as T

    worker = make_worker("w1", Role.GENERAL_GUARD, min_hours=0, max_hours=64)
    fixed = tuple(Assignment("w1", date(YEAR, MONTH, d), Shift.A, Role.GENERAL_GUARD) for d in range(1, 11))  # 80h
    p = Problem(year=YEAR, month=MONTH, demand={(Shift.A, Role.GENERAL_GUARD): 1}, workers=[worker],
                free_from=(date(YEAR, MONTH, 15), Shift.A), fixed_assignments=fixed)

    real_run = T._run_cp_sat

    def fake_run(model, config):
        raw = real_run(model, config)
        # force every x-var to 1 regardless of what the solver actually found,
        # simulating a bad/injected solution that adds another shift for w1.
        forced = {k: (1 if k.startswith("x[") else v) for k, v in raw.values.items()}
        return T.RawSolve(raw.status, forced, raw.objective, raw.bound, raw.wall_time)

    monkeypatch.setattr(T, "_run_cp_sat", fake_run)
    result = T.solve(p, CFG)
    assert result.kind == "engine_error"
