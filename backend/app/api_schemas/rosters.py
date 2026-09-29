"""Roster vertical-slice schemas (§6 "Rosters"): generate response,
save request, and roster read response.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from app.api_schemas.common import (
    AssignmentOut,
    CostsOut,
    CoverageGapOut,
    CoverageStatusOut,
    HourShortfallOut,
    MinHoursStatusOut,
    Shift,
    ViolationOut,
    WorkerRefOut,
)


class GenerateRequest(BaseModel):
    forbid_adjacent_shifts: bool = False


class ObjectiveOut(BaseModel):
    weight: int
    s_max: int
    value: float
    bound: float


class GenerateOutcomeOut(BaseModel):
    """The engine outcome mapped to the API (§4.6 "API mapping")."""

    outcome: Literal["solved", "no_solution_within_limit", "invalid_input", "engine_error"]
    assignments: list[AssignmentOut] | None = None
    coverage_gaps: list[CoverageGapOut] | None = None
    hour_shortfalls: list[HourShortfallOut] | None = None
    coverage: CoverageStatusOut | None = None
    min_hours: MinHoursStatusOut | None = None
    lexicographically_optimal: bool | None = None
    preexisting_violations: list[ViolationOut] | None = None
    objective: ObjectiveOut | None = None
    costs: CostsOut | None = None
    workers: list[WorkerRefOut] | None = None  # name lookup for every worker id in this response
    fingerprint: str | None = None
    coverage_lower_bound: int | None = None  # NoSolutionWithinLimit only
    errors: list[dict] | None = None  # InvalidInput only
    message: str | None = None  # EngineError only
    warnings: list[str] = []


class SaveRequest(BaseModel):
    assignments: list[AssignmentOut]
    fingerprint: str
    expected_version: int | None = None
    replace_existing: bool = False
    forbid_adjacent_shifts: bool = False


class SaveResponseOut(BaseModel):
    roster_id: int
    version: int
    status: Literal["DRAFT", "APPROVED"]


class ApprovalEventOut(BaseModel):
    approved_by: str
    approved_at: str
    reason: str | None
    revoked_at: str | None
    revoke_cause: Literal["EDIT", "REGENERATE", "CONTRACT_CHANGE", "WORKER_CHANGE"] | None


class RosterOut(BaseModel):
    month: date
    status: Literal["DRAFT", "APPROVED"]
    version: int
    is_history: bool
    free_from: tuple[date, Shift]
    forbid_adjacent_shifts: bool
    assignments: list[AssignmentOut]
    violations: list[ViolationOut]
    coverage_gaps: list[CoverageGapOut]
    hour_shortfalls: list[HourShortfallOut]
    costs: CostsOut
    workers: list[WorkerRefOut]  # name lookup for every worker id in this response
    updated_at: datetime  # last save/edit of this roster
    updated_by: str  # display name of whoever made it
    approval_history: list[ApprovalEventOut]
