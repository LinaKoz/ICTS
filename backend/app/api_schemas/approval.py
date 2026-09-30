"""Approval schemas (§6 "Rosters" approve, P11, T8)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.api_schemas.common import CoverageGapOut, HourShortfallOut, ViolationOut
from app.api_schemas.rosters import ApprovalEventOut


class ApproveRequest(BaseModel):
    expected_version: int
    acknowledge_warnings: bool = False
    reason: str | None = None
    # From the approval preview the UI showed; required when soft shortages exist.
    warnings_fingerprint: str | None = None


class RevokeRequest(BaseModel):
    expected_version: int
    reason: str | None = Field(default=None, max_length=500)  # why the manager withdraws the approval


class ApprovalPreviewOut(BaseModel):
    """What approving would need right now, computed from current data."""

    version: int
    status: Literal["DRAFT", "APPROVED"]
    is_history: bool
    hard_violations: list[ViolationOut]  # never acknowledgeable; any entry blocks approval
    coverage_gaps: list[CoverageGapOut]  # soft shortages (locked and upcoming)
    hour_shortfalls: list[HourShortfallOut]  # soft shortages
    warnings_fingerprint: str  # deterministic hash of the soft-shortage set
    requires_acknowledgement: bool  # soft shortages exist
    can_approve: bool  # DRAFT, not history, and no hard violations


class ApprovalResultOut(BaseModel):
    version: int
    status: Literal["DRAFT", "APPROVED"]
    event: ApprovalEventOut
