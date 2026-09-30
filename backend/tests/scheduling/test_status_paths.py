"""§4.9 Status paths (mocked `_run_cp_sat`)."""
from datetime import date

import app.scheduling.solver as T
from app.scheduling import (
    EngineErrorResult, NoSolutionWithinLimit, Problem, RawSolve, Role, Shift, Solved, SolverConfig, solve,
)
from tests.scheduling.conftest import make_worker

YEAR, MONTH = 2026, 11
CFG = SolverConfig(time_limit_s=10.0)
FF = (date(YEAR, MONTH, 1), Shift.A)


def _problem():
    demand = {(Shift.A, Role.GENERAL_GUARD): 1}
    worker = make_worker("w1", Role.GENERAL_GUARD, min_hours=0, max_hours=744)
    return Problem(year=YEAR, month=MONTH, demand=demand, workers=[worker], free_from=FF)


def _wrap_with_forced_status(monkeypatch, status):
    real_run = T._run_cp_sat

    def fake_run(model, config):
        raw = real_run(model, config)
        return RawSolve(status, raw.values, raw.objective, raw.bound, raw.wall_time)

    monkeypatch.setattr(T, "_run_cp_sat", fake_run)


def test_optimal_status_path(monkeypatch):
    _wrap_with_forced_status(monkeypatch, "OPTIMAL")
    result = solve(_problem(), CFG)
    assert isinstance(result, Solved)
    assert result.coverage.status == "OPTIMAL"
    assert result.min_hours.status == "OPTIMAL"
    assert result.lexicographically_optimal is True
    assert result.coverage.lower_bound == result.coverage.total_uncovered


def test_feasible_status_path(monkeypatch):
    _wrap_with_forced_status(monkeypatch, "FEASIBLE")
    result = solve(_problem(), CFG)
    assert isinstance(result, Solved)
    assert result.min_hours.status == "FEASIBLE"
    assert result.lexicographically_optimal is False
    assert result.coverage.status in ("OPTIMAL", "FEASIBLE")


def test_feasible_with_tight_bound_gives_optimal_coverage(monkeypatch):
    """FEASIBLE status but the objective bound already equals the achieved
    uncovered count -> coverage is reported OPTIMAL even though the overall
    solver status is FEASIBLE."""
    real_run = T._run_cp_sat

    def fake_run(model, config):
        raw = real_run(model, config)
        return RawSolve("FEASIBLE", raw.values, raw.objective, raw.objective, raw.wall_time)

    monkeypatch.setattr(T, "_run_cp_sat", fake_run)
    result = solve(_problem(), CFG)
    assert isinstance(result, Solved)
    assert result.coverage.status == "OPTIMAL"
    assert result.lexicographically_optimal is False


def test_unknown_no_solution(monkeypatch):
    def fake_run(model, config):
        return RawSolve("UNKNOWN", {}, float("nan"), 0.0, 0.01)

    monkeypatch.setattr(T, "_run_cp_sat", fake_run)
    result = solve(_problem(), CFG)
    assert isinstance(result, NoSolutionWithinLimit)
    assert result.coverage_lower_bound >= 0


def test_model_invalid_engine_error(monkeypatch):
    def fake_run(model, config):
        return RawSolve("MODEL_INVALID", {}, float("nan"), 0.0, 0.0)

    monkeypatch.setattr(T, "_run_cp_sat", fake_run)
    result = solve(_problem(), CFG)
    assert isinstance(result, EngineErrorResult)
    assert result.solver_status == "MODEL_INVALID"


def test_infeasible_engine_error(monkeypatch):
    def fake_run(model, config):
        return RawSolve("INFEASIBLE", {}, float("nan"), 0.0, 0.0)

    monkeypatch.setattr(T, "_run_cp_sat", fake_run)
    result = solve(_problem(), CFG)
    assert isinstance(result, EngineErrorResult)
    assert result.solver_status == "INFEASIBLE"


def test_injected_invalid_solution_rejected_by_gate(monkeypatch):
    """An injected solution that assigns a worker to a slot they are not
    eligible for (no corresponding variable) can't happen via values alone,
    but forcing an over-cap assignment for a fixed-heavy worker is rejected."""
    from app.scheduling import Assignment

    worker = make_worker("w1", Role.GENERAL_GUARD, min_hours=0, max_hours=8)
    fixed = (Assignment("w1", date(YEAR, MONTH, 1), Shift.A, Role.GENERAL_GUARD),)  # already at cap
    p = Problem(year=YEAR, month=MONTH, demand={(Shift.A, Role.GENERAL_GUARD): 1}, workers=[worker],
                free_from=(date(YEAR, MONTH, 2), Shift.A), fixed_assignments=fixed)

    real_run = T._run_cp_sat

    def fake_run(model, config):
        raw = real_run(model, config)
        forced = {k: (1 if k.startswith("x[") else v) for k, v in raw.values.items()}
        return RawSolve(raw.status, forced, raw.objective, raw.bound, raw.wall_time)

    monkeypatch.setattr(T, "_run_cp_sat", fake_run)
    result = solve(p, CFG)
    assert isinstance(result, EngineErrorResult)
