"""§4.9 Coverage bound arithmetic (pure function)."""
from app.scheduling.types import _coverage_lower_bound


def test_tight_bound_returns_exactly_u_star():
    # objective_bound = W*U* + S* exactly
    weight, s_max, u_star, s_star = 10, 5, 3, 2
    bound = weight * u_star + s_star
    assert _coverage_lower_bound(bound, s_max, weight, locked_uncovered=0, diag_free=0) == u_star


def test_float_noise_does_not_overstate():
    weight, s_max, u_star, s_star = 10, 5, 3, 2
    bound = weight * u_star + s_star + 1e-9
    assert _coverage_lower_bound(bound, s_max, weight, locked_uncovered=0, diag_free=0) == u_star


def test_bound_below_s_max_gives_zero():
    weight, s_max = 10, 50
    bound = 20.0  # well below s_max
    assert _coverage_lower_bound(bound, s_max, weight, locked_uncovered=0, diag_free=0) == 0


def test_locked_uncovered_is_added():
    weight, s_max, u_star, s_star = 10, 5, 3, 2
    bound = weight * u_star + s_star
    assert _coverage_lower_bound(bound, s_max, weight, locked_uncovered=7, diag_free=0) == u_star + 7


def test_result_is_max_with_diagnostic_bound():
    weight, s_max, u_star, s_star = 10, 5, 3, 2
    bound = weight * u_star + s_star
    assert _coverage_lower_bound(bound, s_max, weight, locked_uncovered=0, diag_free=100) == 100
    assert _coverage_lower_bound(bound, s_max, weight, locked_uncovered=0, diag_free=1) == u_star
