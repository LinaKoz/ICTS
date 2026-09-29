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
    "NO_CONTRACT_FOR_MONTH",  # application-layer code (§3, C3): an engine UNKNOWN_WORKER
    # whose worker exists but has no contract resolved for the roster's month (P4).
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


class ShiftCostOut(BaseModel):
    date: date
    shift: Shift
    amount_ils: str  # sum over the shift's assignments with a known rate
    unknown_cost_assignments: int  # assignments in this shift whose worker has no contract (P15)


class CostsOut(BaseModel):
    per_shift: list[ShiftCostOut] = []  # P15 "per shift"; added in T3 (default keeps the slice contract backward compatible)
    per_worker: list[WorkerCostOut]
    monthly_total_ils: str
    unknown_cost_worker_count: int
