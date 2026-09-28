"""Pydantic models shared by the vertical-slice endpoints (§6, §4.2, §4.5, §4.6).

These mirror `app.scheduling.types` for the API boundary. Every
assignment schema carries `role` (C1, §11). Only the vertical-slice
endpoints (meta, generate, save, roster read) are covered here; the
rest are added through the main session before each later task
starts on them (§9 "Ownership").
"""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel

Shift = Literal["A", "B", "C"]
Role = Literal["GENERAL_GUARD", "SCREENER", "SUPERVISOR"]
ViolationCode = Literal[
    "INACTIVE_WORKER",
    "UNKNOWN_WORKER",
    "WRONG_ROLE",
    "UNAVAILABLE",
    "OUT_OF_MONTH",
    "DUPLICATE_ASSIGNMENT",
    "DAILY_LIMIT",
    "ADJACENT_SHIFTS",
    "MAX_HOURS",
    "OVERSTAFFED",
]


class AssignmentOut(BaseModel):
    worker_id: str
    date: date
    shift: Shift
    role: Role  # every assignment schema carries role (§6, C1)


class ViolationOut(BaseModel):
    code: ViolationCode
    key: list
    magnitude: int
    assignments: list[AssignmentOut]


class CoverageGapOut(BaseModel):
    date: date
    shift: Shift
    role: Role
    required: int
    assigned: int
    missing: int
    proven_missing: int
    locked: bool


class HourShortfallOut(BaseModel):
    worker_id: str
    min_hours: int
    assigned_hours: int
    missing_hours: int


class CoverageStatusOut(BaseModel):
    status: Literal["OPTIMAL", "FEASIBLE"]
    total_uncovered: int
    locked_uncovered: int
    lower_bound: int


class MinHoursStatusOut(BaseModel):
    status: Literal["OPTIMAL", "FEASIBLE"]
    total_shortfall: int


class WorkerCostOut(BaseModel):
    worker_id: str
    hours: int
    amount_ils: str | None  # Decimal serialized as string; None = "cost unknown" (P15)


class CostsOut(BaseModel):
    per_worker: list[WorkerCostOut]
    monthly_total_ils: str
    unknown_cost_worker_count: int
