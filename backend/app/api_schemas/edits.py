"""Manual edit and suggestion schemas (§6 "Rosters", P10, T7)."""
from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

from app.api_schemas.common import Role, Shift


class EditableAssignmentOut(BaseModel):
    """A stored assignment with its row id (the edit endpoints address it)."""

    id: int
    worker_id: str
    date: dt.date
    shift: Shift
    role: Role


class AddAssignmentRequest(BaseModel):
    worker_id: str = Field(pattern=r"^[0-9]+$")
    date: dt.date
    shift: Shift
    role: Role
    expected_version: int
    acknowledge_approved_edit: bool = False


class RemoveAssignmentRequest(BaseModel):
    expected_version: int
    acknowledge_approved_edit: bool = False


class MoveAssignmentRequest(BaseModel):
    """Target slot; any field left out keeps the source's value."""

    worker_id: str | None = Field(default=None, pattern=r"^[0-9]+$")
    date: dt.date | None = None
    shift: Shift | None = None
    role: Role | None = None
    expected_version: int
    acknowledge_approved_edit: bool = False


class SwapAssignmentRequest(BaseModel):
    """Exchange the workers of two assignments of the same role in different slots (the day or shift may differ)."""

    other_assignment_id: int
    expected_version: int
    acknowledge_approved_edit: bool = False


class EditResultOut(BaseModel):
    version: int  # the roster's new row_version
    status: Literal["DRAFT", "APPROVED"]
    approval_revoked: bool  # true when the edit sent an approved roster back to DRAFT (cause EDIT)
    assignment: EditableAssignmentOut | None = None  # the added/moved assignment; None for a removal


class SuggestionOut(BaseModel):
    worker_id: str
    full_name: str
    assigned_hours: int
    min_hours: int
    hours_below_minimum: int
    shifts_that_day: int
    reasons: list[str]


class SuggestionsOut(BaseModel):
    date: dt.date
    shift: Shift
    role: Role
    slot_state: Literal["OPEN", "FILLED", "LOCKED"]  # only OPEN slots get candidates
    candidates: list[SuggestionOut]
