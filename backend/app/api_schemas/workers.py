"""Worker and contract schemas (§6 "Workers", "Contracts"), plus the
change-impact shapes shared by the contract preview/apply and the worker
PATCH (and, later, the CSV preview). New in T5; the slice schemas in
`common.py`/`rosters.py` are untouched.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.api_schemas.common import Role, Shift, ViolationCode, ViolationOut
from app.contracts.availability import normalize_availability
from app.rosters.problem_builder import MONTH_PATTERN

WorkerStatus = Literal["ACTIVE", "INACTIVE"]
MonthStr = Annotated[str, StringConstraints(pattern=MONTH_PATTERN)]  # strict YYYY-MM
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
NationalId = Annotated[str, StringConstraints(strip_whitespace=True, max_length=32)]


class ContractOut(BaseModel):
    id: int
    worker_id: int
    version_no: int
    effective_month: MonthStr
    hourly_rate_ils: str  # Decimal as a string, 2 places
    min_hours: int
    max_hours: int
    availability: list[str]  # sorted ["MON:A", ...]
    created_at: datetime
    created_by: str  # display name
    source: Literal["UI", "CSV"]
    import_id: int | None


class WorkerOut(BaseModel):
    id: int
    national_id: str
    full_name: str
    role: Role
    status: WorkerStatus
    row_version: int
    created_at: datetime
    updated_at: datetime
    current_contract: ContractOut | None  # resolved for the current Israel month


class FieldChangeOut(BaseModel):
    field: Literal["STATUS", "ROLE"]
    old_value: str
    new_value: str
    effective_at: datetime
    changed_by: str  # display name


class WorkerDetailOut(WorkerOut):
    field_history: list[FieldChangeOut]  # newest first (D9)


class WorkerCreate(BaseModel):
    national_id: NationalId
    full_name: Name
    role: Role
    status: WorkerStatus = "ACTIVE"


class WorkerPatch(BaseModel):
    """Every PATCH needs the `expected_version` the client last saw (409
    `VERSION_CONFLICT` otherwise). Omitted or unchanged fields are no-ops (P5)."""

    expected_version: int
    national_id: NationalId | None = None
    full_name: Name | None = None
    role: Role | None = None
    status: WorkerStatus | None = None


class ContractInput(BaseModel):
    effective_month: MonthStr
    hourly_rate_ils: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    min_hours: int = Field(ge=0, le=744)
    max_hours: int = Field(ge=0, le=744)
    availability: list[str] = Field(min_length=1, description='"DAY:SHIFT" tokens such as "MON:A"')

    @model_validator(mode="after")
    def _check(self) -> "ContractInput":
        if self.min_hours > self.max_hours:
            raise ValueError("min_hours must not exceed max_hours")
        self.availability = normalize_availability(self.availability)
        return self


class ContractApply(ContractInput):
    fingerprint: str  # from the preview this apply was based on


class ContractsOut(BaseModel):
    worker_id: int
    resolved_for: MonthStr
    resolved: ContractOut | None  # the version that applies to `resolved_for`
    versions: list[ContractOut]  # newest first, all kept (P1)


class LockedViolationOut(BaseModel):
    """A new hard violation in an already-started shift that editing
    cannot fix (P2, D8)."""

    month: MonthStr
    worker_id: str
    worker_name: str
    date: date
    shift: Shift
    code: ViolationCode
    magnitude: int


class AffectedRosterOut(BaseModel):
    month: MonthStr
    roster_id: int
    status: Literal["DRAFT", "APPROVED"]  # before the change
    version: int
    is_history: bool  # read-only history (P3): listed, never revalidated
    worker_ids: list[str]
    assignment_count: int
    new_violations: list[ViolationOut]
    locked_violations: list[LockedViolationOut]
    revokes_approval: bool  # preview: would be; apply: was (returned to DRAFT)


class ChangeImpactOut(BaseModel):
    affected_rosters: list[AffectedRosterOut]
    invalidates_approved: bool
    locked_violations: list[LockedViolationOut]  # across all affected rosters


class ContractPreviewOut(ChangeImpactOut):
    worker_id: int
    effective_month: MonthStr
    retroactive: bool  # effective month <= the current Israel month (P2)
    unchanged: bool  # identical to the version resolved at that month: nothing would be created (P5)
    previous: ContractOut | None
    fingerprint: str


class ContractApplyOut(ChangeImpactOut):
    created: bool  # False when identical to the resolved version (P5)
    contract: ContractOut | None
    revoked_rosters: list[MonthStr]


class WorkerUpdateOut(ChangeImpactOut):
    worker: WorkerOut
    changed: bool  # False when nothing differed (no version bump, P5)
