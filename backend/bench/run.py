"""§4.8 Benchmark runner. Prints a markdown results table to stdout.

Usage:
    python -m bench.run small
    python -m bench.run scale --sizes 200
    python -m bench.run scale --sizes 200 500 1000 --time-limits 10 60
"""
from __future__ import annotations

import argparse
import dataclasses
import time

from app.scheduling import Solved, SolverConfig, solve

from bench.fixtures import SMALL_FIXTURES, scale_fixture


def _row(name: str, problem, config: SolverConfig) -> dict:
    n_workers = len(problem.workers)
    t0 = time.perf_counter()
    result = solve(problem, config)
    wall = time.perf_counter() - t0
    row = {"name": name, "workers": n_workers, "time_limit_s": config.time_limit_s, "wall_s": round(wall, 3)}
    if isinstance(result, Solved):
        row.update({
            "status": "OPTIMAL" if result.lexicographically_optimal else "FEASIBLE",
            "total_uncovered": result.coverage.total_uncovered,
            "total_shortfall": result.min_hours.total_shortfall,
            "lex_optimal": result.lexicographically_optimal,
            "objective": round(result.objective.value, 1),
            "bound": round(result.objective.bound, 1),
            "coverage_lower_bound": result.coverage.lower_bound,
            "gap": result.coverage.total_uncovered - result.coverage.lower_bound,
            "diagnostic_bound": result.diagnostics.total_lower_bound,
            "input_validation_s": round(result.timings.input_validation_s, 4),
            "model_build_s": round(result.timings.model_build_s, 4),
            "search_s": round(result.timings.search_s, 4),
            "total_s": round(result.timings.total_s, 4),
        })
    else:
        row.update({"status": result.kind, "total_uncovered": None, "total_shortfall": None,
                    "lex_optimal": None, "objective": None, "bound": None,
                    "coverage_lower_bound": getattr(result, "coverage_lower_bound", None),
                    "gap": None, "diagnostic_bound": None, "input_validation_s": None,
                    "model_build_s": None, "search_s": None, "total_s": None})
    return row


def _print_table(rows: list[dict]) -> None:
    cols = ["name", "workers", "time_limit_s", "status", "total_uncovered", "total_shortfall",
            "lex_optimal", "coverage_lower_bound", "gap", "diagnostic_bound",
            "model_build_s", "search_s", "total_s"]
    print("| " + " | ".join(cols) + " |")
    print("|" + "|".join("---" for _ in cols) + "|")
    for r in rows:
        print("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")


def run_small(time_limit_s: float = 10.0) -> list[dict]:
    rows = []
    for name, builder in SMALL_FIXTURES.items():
        for rule in (False, True):
            problem = dataclasses.replace(builder(), forbid_adjacent_shifts=rule)
            config = SolverConfig(time_limit_s=time_limit_s, num_workers=8, random_seed=0)
            rows.append(_row(f"{name}[rule={rule}]", problem, config))
    return rows


def run_scale(sizes: list[int], time_limits: list[float]) -> list[dict]:
    rows = []
    for n in sizes:
        for time_limit_s in time_limits:
            config = SolverConfig(time_limit_s=time_limit_s, num_workers=8, random_seed=0)
            p_ratio = scale_fixture(n, comfortable_ratio=True)
            rows.append(_row(f"scale[n={n}, comfortable_ratio]", p_ratio, config))
            p_fixed = scale_fixture(n, comfortable_ratio=False)
            rows.append(_row(f"scale[n={n}, default_demand]", p_fixed, config))
            p_mid = scale_fixture(n, comfortable_ratio=True, mid_month=True)
            rows.append(_row(f"scale[n={n}, mid_month]", p_mid, config))
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["small", "scale"])
    parser.add_argument("--sizes", nargs="+", type=int, default=[200])
    parser.add_argument("--time-limits", nargs="+", type=float, default=[10.0])
    args = parser.parse_args()

    if args.mode == "small":
        rows = run_small(args.time_limits[0])
    else:
        rows = run_scale(args.sizes, args.time_limits)
    _print_table(rows)


if __name__ == "__main__":
    main()
