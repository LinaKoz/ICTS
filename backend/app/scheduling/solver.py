"""The CP-SAT model: `solve(problem, config) -> ScheduleResult`.

Objective (README "Scheduling design"): minimise
`W * sum(uncovered) + sum(short)` with `W = S_max + 1`, which ranks
coverage strictly before minimum hours. Every returned roster passes the
independent validator gate in `validation`.
"""
from __future__ import annotations

import math
import time
from datetime import date

from ortools.sat.python import cp_model

from ._helpers import (
    _adjacent_positions,
    _ceil_div,
    _demand_of,
    _eligible_free_shifts,
    _fixed_index,
    _is_free,
    _month_days,
    _pos,
    _remaining_max_shifts,
    _var_name_short,
    _var_name_x,
)
from .diagnostics import diagnose
from .types import (
    Assignment,
    CoverageStatus,
    EngineErrorResult,
    InvalidInput,
    MinHoursStatus,
    NoSolutionWithinLimit,
    ObjectiveInfo,
    Problem,
    RawSolve,
    Role,
    ScheduleResult,
    Shift,
    Solved,
    SolverConfig,
    Timings,
)
from .validation import roster_metrics, validate_problem, validate_roster, worsened


def _run_cp_sat(model: cp_model.CpModel, config: SolverConfig) -> RawSolve:
    """Test seam (§4.2): the only function that calls into CP-SAT.
    Tests can mock it to force any status."""
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = config.time_limit_s
    solver.parameters.num_search_workers = config.num_workers
    solver.parameters.random_seed = config.random_seed
    status = solver.Solve(model)
    # Collect values for all named variables we created (x[...] / short[...]).
    values = {}
    proto = model.Proto()
    for i, v in enumerate(proto.variables):
        if v.name:
            values[v.name] = solver.Value(model.GetIntVarFromProtoIndex(i))
    return RawSolve(solver.StatusName(status), values, solver.ObjectiveValue() if status in
                     (cp_model.OPTIMAL, cp_model.FEASIBLE) else float("nan"),
                     solver.BestObjectiveBound(), solver.WallTime())


def _coverage_lower_bound(bound: float, s_max: int, weight: int, locked_uncovered: int, diag_free: int) -> int:
    b = math.ceil(bound - 1e-6)
    lb_free = max(0, _ceil_div(b - s_max, weight))
    return locked_uncovered + max(lb_free, diag_free)


def solve(problem: Problem, config: SolverConfig) -> ScheduleResult:
    t_start = time.perf_counter()

    t0 = time.perf_counter()
    errors = validate_problem(problem)
    input_validation_s = time.perf_counter() - t0
    if errors:
        return InvalidInput(kind="invalid_input", errors=tuple(errors))

    t0 = time.perf_counter()
    diag = diagnose(problem)
    diagnostics_s = time.perf_counter() - t0

    active = [w for w in problem.workers if w.active]
    s_max = sum(w.min_hours for w in active)
    weight = s_max + 1

    t0 = time.perf_counter()
    model = cp_model.CpModel()
    _, fixed_slot, fixed_day, fixed_hours = _fixed_index(problem)
    days = _month_days(problem.year, problem.month)

    x_vars: dict[tuple[str, date, Shift], cp_model.IntVar] = {}
    for w in active:
        for d in days:
            for s in _eligible_free_shifts(problem, w, d):
                x_vars[(w.id, d, s)] = model.NewBoolVar(_var_name_x(w.id, d, s))

    # monthly limit
    for w in active:
        cap_shifts = _remaining_max_shifts(w, fixed_hours)
        my_vars = [v for (wid, d, s), v in x_vars.items() if wid == w.id]
        if my_vars:
            model.Add(sum(my_vars) <= cap_shifts)

    # daily limit
    for w in active:
        for d in days:
            day_vars = [x_vars[(w.id, d, s)] for s in (Shift.A, Shift.B, Shift.C) if (w.id, d, s) in x_vars]
            if day_vars:
                model.Add(sum(day_vars) <= max(0, 2 - fixed_day.get((w.id, d), 0)))

    # adjacency between two free variables (only if the rule is on)
    if problem.forbid_adjacent_shifts:
        seen_pairs = set()
        for (wid, d, s) in list(x_vars):
            for (d2, s2) in _adjacent_positions(d, s):
                if (wid, d2, s2) in x_vars and (wid, d, s) not in seen_pairs and (wid, d2, s2) not in seen_pairs:
                    pair_key = (wid, min((d, s), (d2, s2), key=lambda p: _pos(*p)))
                    if pair_key in seen_pairs:
                        continue
                    seen_pairs.add(pair_key)
                    model.Add(x_vars[(wid, d, s)] + x_vars[(wid, d2, s2)] <= 1)

    # no overstaffing + uncovered expressions (free slots only)
    uncovered_terms = []
    for d in days:
        for s in (Shift.A, Shift.B, Shift.C):
            if not _is_free(problem, d, s):
                continue
            for r in Role:
                required = max(0, _demand_of(problem, s, r) - fixed_slot.get((d, s, r), 0))
                slot_vars = [v for (wid, dd, ss), v in x_vars.items()
                             if dd == d and ss == s and next(w for w in active if w.id == wid).role is r]
                if required == 0 and not slot_vars:
                    continue
                if slot_vars:
                    model.Add(sum(slot_vars) <= required)
                uncovered_terms.append(required - (sum(slot_vars) if slot_vars else 0))

    # short[w]
    short_vars = {}
    for w in active:
        sv = model.NewIntVar(0, w.min_hours, _var_name_short(w.id))
        my_vars = [v for (wid, d, s), v in x_vars.items() if wid == w.id]
        model.Add(sv >= w.min_hours - 8 * (sum(my_vars) if my_vars else 0) - fixed_hours.get(w.id, 0))
        short_vars[w.id] = sv

    model.Minimize(weight * sum(uncovered_terms) + sum(short_vars.values()))
    model_build_s = time.perf_counter() - t0

    t0 = time.perf_counter()
    raw = _run_cp_sat(model, config)
    search_s = time.perf_counter() - t0

    def _timings(roster_validation_s: float) -> Timings:
        return Timings(input_validation_s, diagnostics_s, model_build_s, search_s, roster_validation_s,
                        time.perf_counter() - t_start)

    if raw.status == "UNKNOWN":
        # locked_uncovered still contributes; compute it without needing a roster
        locked_uncovered = sum(
            max(0, _demand_of(problem, s, r) - fixed_slot.get((d, s, r), 0)) if not _is_free(problem, d, s) else 0
            for d in days for s in (Shift.A, Shift.B, Shift.C) for r in Role
        )
        lb = _coverage_lower_bound(raw.bound, s_max, weight, locked_uncovered, diag.total_lower_bound)
        return NoSolutionWithinLimit(kind="no_solution_within_limit", coverage_lower_bound=lb,
                                      diagnostics=diag, timings=_timings(0.0))

    if raw.status not in ("OPTIMAL", "FEASIBLE"):
        return EngineErrorResult(kind="engine_error", solver_status=raw.status,
                                  message=f"CP-SAT returned {raw.status}", diagnostics=diag,
                                  timings=_timings(0.0))

    new_assignments = []
    for (wid, d, s), var in x_vars.items():
        if raw.values.get(var.Name(), 0):
            role = next(w for w in active if w.id == wid).role
            new_assignments.append(Assignment(wid, d, s, role))
    full = list(problem.fixed_assignments) + new_assignments

    t0 = time.perf_counter()
    v_fixed = validate_roster(problem, problem.fixed_assignments)
    v_full = validate_roster(problem, full)
    gate_failures = worsened(v_fixed, v_full)
    roster_validation_s = time.perf_counter() - t0

    if gate_failures:
        return EngineErrorResult(kind="engine_error", solver_status=raw.status,
                                  message="validation gate rejected the candidate roster",
                                  diagnostics=diag, timings=_timings(roster_validation_s))

    metrics = roster_metrics(problem, full)
    lower_bound = _coverage_lower_bound(raw.bound, s_max, weight, metrics.locked_uncovered, diag.total_lower_bound)
    coverage_status = "OPTIMAL" if lower_bound == metrics.total_uncovered else "FEASIBLE"
    total_shortfall = sum(hs.missing_hours for hs in metrics.hour_shortfalls)
    min_hours_status = "OPTIMAL" if raw.status == "OPTIMAL" else "FEASIBLE"

    return Solved(
        kind="solved",
        assignments=tuple(full),
        coverage_gaps=metrics.coverage_gaps,
        hour_shortfalls=metrics.hour_shortfalls,
        coverage=CoverageStatus(coverage_status, metrics.total_uncovered, metrics.locked_uncovered, lower_bound),
        min_hours=MinHoursStatus(min_hours_status, total_shortfall),
        lexicographically_optimal=(raw.status == "OPTIMAL"),
        preexisting_violations=tuple(v_full),
        objective=ObjectiveInfo(weight, s_max, raw.objective, raw.bound),
        free_from=problem.free_from,
        diagnostics=diag,
        timings=_timings(roster_validation_s),
    )
