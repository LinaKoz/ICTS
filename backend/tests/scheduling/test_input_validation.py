"""§4.9 Input and demand."""
from datetime import date

from app.scheduling.types import (
    Assignment, DEFAULT_DEMAND, Problem, Role, Shift, Weekday,
    validate_problem, validate_roster, diagnose, roster_metrics,
)
from tests.scheduling.conftest import FULL_AVAILABILITY, make_worker


def base_problem(**overrides):
    kwargs = dict(
        year=2026, month=11,
        demand=DEFAULT_DEMAND,
        workers=[make_worker("w1", Role.GENERAL_GUARD, min_hours=0, max_hours=160)],
        free_from=(date(2026, 11, 1), Shift.A),
    )
    kwargs.update(overrides)
    return Problem(**kwargs)


def test_duplicate_worker_ids_rejected():
    workers = [make_worker("w1", Role.GENERAL_GUARD), make_worker("w1", Role.SCREENER)]
    errs = validate_problem(base_problem(workers=workers))
    assert any(e.code == "DUPLICATE_WORKER_ID" for e in errs)


def test_min_greater_than_max_rejected():
    workers = [make_worker("w1", Role.GENERAL_GUARD, min_hours=100, max_hours=50)]
    errs = validate_problem(base_problem(workers=workers))
    assert any(e.code == "INVALID_HOURS" for e in errs)


def test_negative_demand_rejected():
    demand = dict(DEFAULT_DEMAND)
    demand[(Shift.A, Role.GENERAL_GUARD)] = -1
    errs = validate_problem(base_problem(demand=demand))
    assert any(e.code == "INVALID_DEMAND_VALUE" for e in errs)


def test_non_integer_demand_rejected():
    demand = dict(DEFAULT_DEMAND)
    demand[(Shift.A, Role.GENERAL_GUARD)] = 2.5
    errs = validate_problem(base_problem(demand=demand))
    assert any(e.code == "INVALID_DEMAND_VALUE" for e in errs)


def test_unknown_demand_key_rejected():
    demand = dict(DEFAULT_DEMAND)
    demand[("X", "Y")] = 1
    errs = validate_problem(base_problem(demand=demand))
    assert any(e.code == "UNKNOWN_DEMAND_KEY" for e in errs)


def test_free_from_out_of_range_rejected():
    errs = validate_problem(base_problem(free_from=(date(2026, 10, 31), Shift.A)))
    assert any(e.code == "FREE_FROM_OUT_OF_RANGE" for e in errs)
    errs = validate_problem(base_problem(free_from=(date(2026, 12, 2), Shift.A)))
    assert any(e.code == "FREE_FROM_OUT_OF_RANGE" for e in errs)


def test_fixed_assignment_at_or_after_free_from_rejected():
    fixed = (Assignment("w1", date(2026, 11, 5), Shift.A, Role.GENERAL_GUARD),)
    errs = validate_problem(base_problem(free_from=(date(2026, 11, 1), Shift.A), fixed_assignments=fixed))
    assert any(e.code == "FIXED_NOT_LOCKED" for e in errs)


def test_fixed_assignment_outside_month_rejected():
    fixed = (Assignment("w1", date(2026, 10, 5), Shift.A, Role.GENERAL_GUARD),)
    errs = validate_problem(base_problem(free_from=(date(2026, 11, 15), Shift.A), fixed_assignments=fixed))
    assert any(e.code == "FIXED_OUT_OF_MONTH" for e in errs)


def test_duplicate_fixed_assignment_rejected():
    fixed = (Assignment("w1", date(2026, 11, 1), Shift.A, Role.GENERAL_GUARD),
              Assignment("w1", date(2026, 11, 1), Shift.A, Role.GENERAL_GUARD))
    errs = validate_problem(base_problem(free_from=(date(2026, 11, 15), Shift.A), fixed_assignments=fixed))
    assert any(e.code == "DUPLICATE_FIXED_ASSIGNMENT" for e in errs)


def test_neighbor_assignment_wrong_date_rejected():
    neighbor = (Assignment("w1", date(2026, 11, 15), Shift.C, Role.GENERAL_GUARD),)
    errs = validate_problem(base_problem(neighbor_assignments=neighbor))
    assert any(e.code == "NEIGHBOR_WRONG_DATE" for e in errs)


def test_neighbor_assignment_correct_dates_accepted():
    neighbor = (Assignment("w1", date(2026, 10, 31), Shift.C, Role.GENERAL_GUARD),
                Assignment("w1", date(2026, 12, 1), Shift.A, Role.GENERAL_GUARD))
    errs = validate_problem(base_problem(neighbor_assignments=neighbor))
    assert errs == []


def test_weight_overflow_guard():
    workers = [make_worker("w1", Role.GENERAL_GUARD, min_hours=2**50, max_hours=2**50)]
    errs = validate_problem(base_problem(workers=workers))
    assert any(e.code == "WEIGHT_OVERFLOW" for e in errs)


def test_omitted_demand_entry_no_assignments_no_gap_overstaffing_flagged():
    demand = {(Shift.A, Role.SUPERVISOR): 1}  # everything else omitted -> 0
    workers = [make_worker("w1", Role.GENERAL_GUARD)]
    problem = base_problem(demand=demand, workers=workers)
    assert validate_problem(problem) == []

    metrics = roster_metrics(problem, [])
    assert all(g.required > 0 for g in metrics.coverage_gaps)  # omitted slots produce no gap entries at all
    assert not any(g.shift == Shift.B and g.role == Role.GENERAL_GUARD for g in metrics.coverage_gaps)

    hand_made = [Assignment("w1", date(2026, 11, 1), Shift.B, Role.GENERAL_GUARD)]
    violations = validate_roster(problem, hand_made)
    assert any(v.code == "OVERSTAFFED" and v.key == (date(2026, 11, 1), Shift.B, Role.GENERAL_GUARD)
               for v in violations)

    diag = diagnose(problem)
    assert diag.role_lower_bounds.get(Role.GENERAL_GUARD, 0) == 0
