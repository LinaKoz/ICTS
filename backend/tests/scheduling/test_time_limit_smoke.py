"""§4.9 Real tiny time-limit smoke test (no mocking, real CP-SAT search)."""
from datetime import date

from app.scheduling import (
    NoSolutionWithinLimit, Problem, Role, Shift, Solved, SolverConfig, solve, validate_roster, worsened,
)
from tests.scheduling.conftest import make_worker

YEAR, MONTH = 2026, 11


def test_tiny_time_limit_never_claims_infeasibility_and_gate_always_passes():
    demand = {(Shift.A, Role.GENERAL_GUARD): 1}
    worker = make_worker("w1", Role.GENERAL_GUARD, min_hours=0, max_hours=744)
    p = Problem(year=YEAR, month=MONTH, demand=demand, workers=[worker], free_from=(date(YEAR, MONTH, 1), Shift.A))
    config = SolverConfig(time_limit_s=0.001, num_workers=1)
    result = solve(p, config)
    assert isinstance(result, (Solved, NoSolutionWithinLimit))
    if isinstance(result, Solved):
        v_fixed = validate_roster(p, p.fixed_assignments)
        v_full = validate_roster(p, result.assignments)
        assert worsened(v_fixed, v_full) == []
