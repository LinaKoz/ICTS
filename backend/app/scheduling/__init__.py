"""The scheduling engine: pure Python + OR-Tools CP-SAT, no database or web imports.

Public API, re-exported here so callers import from `app.scheduling`:

- data contract: `types`
- `validate_problem`, `validate_roster`, `roster_metrics`, `worsened`: `validation`
- `diagnose`: `diagnostics`
- `solve`: `solver` (the CP-SAT model)
"""
from .diagnostics import diagnose
from .solver import solve
from .types import (
    DEFAULT_DEMAND,
    Assignment,
    CoverageGap,
    CoverageStatus,
    Diagnostics,
    EngineErrorResult,
    HourShortfall,
    InputError,
    InvalidInput,
    Metrics,
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
    Violation,
    ViolationCode,
    Weekday,
    WorkerInput,
)
from .validation import roster_metrics, validate_problem, validate_roster, worsened

__all__ = [
    "DEFAULT_DEMAND", "Assignment", "CoverageGap", "CoverageStatus", "Diagnostics", "EngineErrorResult",
    "HourShortfall", "InputError", "InvalidInput", "Metrics", "MinHoursStatus", "NoSolutionWithinLimit",
    "ObjectiveInfo", "Problem", "RawSolve", "Role", "ScheduleResult", "Shift", "Solved", "SolverConfig",
    "Timings", "Violation", "ViolationCode", "Weekday", "WorkerInput",
    "diagnose", "roster_metrics", "solve", "validate_problem", "validate_roster", "worsened",
]
