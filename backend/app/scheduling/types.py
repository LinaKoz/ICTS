"""The scheduling engine's shared, frozen contract (§4.2, §4.5, §4.6).

This module is pure stdlib: no sqlalchemy, no fastapi, no other
`app.*` import outside `scheduling`. That independence is enforced by
a test (§4.9 "Independence").

T0 freezes the field names, types and function signatures exactly as
specified in the plan. T1 implements the function bodies; until then
they raise `NotImplementedError`. Do not change shapes without going
through the main session (§9 "Ownership").
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Literal, Union


# --------------------------------------------------------------------------
# §4.1 Domain enums
# --------------------------------------------------------------------------


class Shift(str, Enum):
    A = "A"  # 00:00-08:00
    B = "B"  # 08:00-16:00
    C = "C"  # 16:00-00:00


class Role(str, Enum):
    GENERAL_GUARD = "GENERAL_GUARD"
    SCREENER = "SCREENER"
    SUPERVISOR = "SUPERVISOR"


class Weekday(str, Enum):
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"
    SAT = "SAT"
    SUN = "SUN"


# Demand of 2 GENERAL_GUARD, 2 SCREENER, 1 SUPERVISOR per shift (§4.1, §1).
DEFAULT_DEMAND: dict[tuple[Shift, Role], int] = {
    (Shift.A, Role.GENERAL_GUARD): 2,
    (Shift.A, Role.SCREENER): 2,
    (Shift.A, Role.SUPERVISOR): 1,
    (Shift.B, Role.GENERAL_GUARD): 2,
    (Shift.B, Role.SCREENER): 2,
    (Shift.B, Role.SUPERVISOR): 1,
    (Shift.C, Role.GENERAL_GUARD): 2,
    (Shift.C, Role.SCREENER): 2,
    (Shift.C, Role.SUPERVISOR): 1,
}


# --------------------------------------------------------------------------
# §4.5 Violation codes
# --------------------------------------------------------------------------


class ViolationCode(str, Enum):
    INACTIVE_WORKER = "INACTIVE_WORKER"
    UNKNOWN_WORKER = "UNKNOWN_WORKER"
    WRONG_ROLE = "WRONG_ROLE"
    UNAVAILABLE = "UNAVAILABLE"
    OUT_OF_MONTH = "OUT_OF_MONTH"
    DUPLICATE_ASSIGNMENT = "DUPLICATE_ASSIGNMENT"
    DAILY_LIMIT = "DAILY_LIMIT"
    ADJACENT_SHIFTS = "ADJACENT_SHIFTS"
    MAX_HOURS = "MAX_HOURS"
    OVERSTAFFED = "OVERSTAFFED"


# --------------------------------------------------------------------------
# §4.2 Interface dataclasses
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkerInput:
    """Contract already resolved for the month by the caller."""

    id: str
    role: Role
    active: bool
    availability: frozenset[tuple[Weekday, Shift]]
    min_hours: int
    max_hours: int


@dataclass(frozen=True)
class Assignment:
    """An assignment. `role` is the slot role, snapshotted; the
    validator checks it against the worker's role."""

    worker_id: str
    date: date
    shift: Shift
    role: Role


@dataclass(frozen=True)
class Violation:
    """`key` is the stable scope (§4.5 table); `magnitude` is >= 1."""

    code: ViolationCode
    key: tuple
    magnitude: int
    assignments: tuple[Assignment, ...]


@dataclass(frozen=True)
class Problem:
    year: int
    month: int
    demand: Mapping[tuple[Shift, Role], int]
    workers: Sequence[WorkerInput]
    free_from: tuple[date, Shift]  # (1st, A) <= free_from <= (last day + 1, A)
    fixed_assignments: Sequence[Assignment] = field(default_factory=tuple)  # all before free_from
    neighbor_assignments: Sequence[Assignment] = field(default_factory=tuple)  # boundary days only
    forbid_adjacent_shifts: bool = False  # optional rule (§4.1); off = brief's rules only


@dataclass(frozen=True)
class SolverConfig:
    time_limit_s: float = 10.0  # CP-SAT search time for the single solve
    num_workers: int = 8  # the application passes min(8, cpu_count)
    random_seed: int = 0


@dataclass(frozen=True)
class InputError:
    """One `validate_problem` failure."""

    code: str
    message: str
    details: dict | None = None


@dataclass(frozen=True)
class RawSolve:
    """Test seam: the raw CP-SAT result (§4.2 "Test seam")."""

    status: str
    values: Mapping[str, int]
    objective: float
    bound: float
    wall_time: float


@dataclass(frozen=True)
class CoverageGap:
    date: date
    shift: Shift
    role: Role
    required: int
    assigned: int
    missing: int
    proven_missing: int
    locked: bool


@dataclass(frozen=True)
class HourShortfall:
    worker_id: str
    min_hours: int
    assigned_hours: int
    missing_hours: int


@dataclass(frozen=True)
class CoverageStatus:
    status: Literal["OPTIMAL", "FEASIBLE"]
    total_uncovered: int
    locked_uncovered: int
    lower_bound: int


@dataclass(frozen=True)
class MinHoursStatus:
    status: Literal["OPTIMAL", "FEASIBLE"]
    total_shortfall: int


@dataclass(frozen=True)
class ObjectiveInfo:
    weight: int
    s_max: int
    value: float
    bound: float


@dataclass(frozen=True)
class Metrics:
    """Returned by `roster_metrics`: coverage gaps and hour shortfalls,
    recomputed from the roster."""

    coverage_gaps: tuple[CoverageGap, ...]
    hour_shortfalls: tuple[HourShortfall, ...]
    locked_uncovered: int
    total_uncovered: int


@dataclass(frozen=True)
class Diagnostics:
    """Returned by `diagnose` (§4.7): proven lower bounds, free slots only."""

    role_lower_bounds: Mapping[Role, int]
    total_lower_bound: int
    worker_shortfall_lower_bounds: Mapping[str, int]


@dataclass(frozen=True)
class Timings:
    input_validation_s: float
    diagnostics_s: float
    model_build_s: float
    search_s: float
    roster_validation_s: float
    total_s: float


# --------------------------------------------------------------------------
# §4.6 Result type (discriminated union)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Solved:
    kind: Literal["solved"]
    assignments: tuple[Assignment, ...]  # fixed ones included, unchanged
    coverage_gaps: tuple[CoverageGap, ...]
    hour_shortfalls: tuple[HourShortfall, ...]
    coverage: CoverageStatus
    min_hours: MinHoursStatus
    lexicographically_optimal: bool
    preexisting_violations: tuple[Violation, ...]
    objective: ObjectiveInfo
    free_from: tuple[date, Shift]
    diagnostics: Diagnostics
    timings: Timings
    warnings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class NoSolutionWithinLimit:
    kind: Literal["no_solution_within_limit"]
    coverage_lower_bound: int  # locked_uncovered + max(solver-derived, diagnostic)
    diagnostics: Diagnostics
    timings: Timings


@dataclass(frozen=True)
class InvalidInput:
    kind: Literal["invalid_input"]
    errors: tuple[InputError, ...]


@dataclass(frozen=True)
class EngineErrorResult:
    """Named `EngineErrorResult` here to avoid clashing with
    `app.errors.EngineError` (the HTTP-facing exception); the plan's
    `EngineError` result-union member."""

    kind: Literal["engine_error"]
    solver_status: str
    message: str
    diagnostics: Diagnostics | None
    timings: Timings


ScheduleResult = Union[Solved, NoSolutionWithinLimit, InvalidInput, EngineErrorResult]


# --------------------------------------------------------------------------
# §4.2 Function signatures (stubs; T1 implements bodies)
# --------------------------------------------------------------------------


def solve(problem: Problem, config: SolverConfig) -> ScheduleResult:
    raise NotImplementedError("implemented in T1")


def validate_problem(problem: Problem) -> list[InputError]:
    raise NotImplementedError("implemented in T1")


def validate_roster(problem: Problem, assignments: Sequence[Assignment]) -> list[Violation]:
    raise NotImplementedError("implemented in T1")


def roster_metrics(problem: Problem, assignments: Sequence[Assignment]) -> Metrics:
    raise NotImplementedError("implemented in T1")


def worsened(before: list[Violation], after: list[Violation]) -> list[Violation]:
    raise NotImplementedError("implemented in T1")


def diagnose(problem: Problem) -> Diagnostics:
    raise NotImplementedError("implemented in T1")


def _run_cp_sat(model, config: SolverConfig) -> RawSolve:
    """Test seam (§4.2): the only function that calls into CP-SAT.
    Tests can mock it to force any status."""
    raise NotImplementedError("implemented in T1")
