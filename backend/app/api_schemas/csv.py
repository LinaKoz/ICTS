"""CSV import/export schemas (§6 "CSV"). New in T6; every existing schema
is untouched. The preview reuses the change-impact shape of T5."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.api_schemas.common import Role
from app.api_schemas.workers import ChangeImpactOut, MonthStr, WorkerStatus

RowClassification = Literal["NEW", "UNCHANGED", "CHANGED", "INVALID"]
ContractAction = Literal["NONE", "NEW_VERSION", "UNCHANGED"]
ImportStatus = Literal["PENDING", "CONFIRMED"]
Decision = Literal["APPROVE", "SKIP"]


class RowErrorOut(BaseModel):
    code: str  # e.g. ID_LENGTH, ID_FORMAT, ID_CHECKSUM, DUPLICATE_IN_FILE, INCOMPLETE_CONTRACT
    message: str
    field: str | None = None


class FieldDiffOut(BaseModel):
    field: str
    old: str | None  # None for a NEW worker or a worker's first contract
    new: str | None


class ImportContractOut(BaseModel):
    hourly_rate_ils: str
    min_hours: int
    max_hours: int
    availability: list[str]  # sorted ["MON:A", ...], same representation as stored contracts


class ImportRowOut(BaseModel):
    line: int  # physical line number in the file
    national_id: str
    full_name: str  # after export-row unescaping
    role: Role | None
    status: WorkerStatus | None
    effective_month: MonthStr | None  # resolved (default: current Israel month); None for worker-only rows
    contract: ImportContractOut | None  # None: worker-only row (D10) or invalid row
    classification: RowClassification
    contract_action: ContractAction
    retroactive: bool  # a new contract version effective in the current or a past month (P2)
    changes: list[FieldDiffOut]
    errors: list[RowErrorOut]
    export_row: bool  # export_format marker was icts-export-v1
    worker_id: int | None  # existing worker, if any


class ImportCountsOut(BaseModel):
    new: int
    changed: int
    unchanged: int
    invalid: int


class ImportResultOut(BaseModel):
    created_workers: int
    updated_workers: int
    contract_versions_created: int
    unchanged: int
    invalid: int
    skipped: int
    revoked_rosters: list[MonthStr]  # approved rosters returned to DRAFT (CONTRACT_CHANGE / WORKER_CHANGE, ref import:{id})


class ImportConfirmRequest(BaseModel):
    """Per-row decision by national ID. NEW and CHANGED rows without an entry
    default to APPROVE; INVALID and UNCHANGED rows are never applied."""

    decisions: dict[str, Decision] = {}


class ImportPreviewOut(ChangeImpactOut):
    id: int
    status: ImportStatus
    created_at: datetime
    default_effective_month: MonthStr  # the current Israel month, frozen for this import (D11)
    counts: ImportCountsOut
    unknown_columns: list[str]  # ignored columns, shown as a warning
    rows: list[ImportRowOut]
    result: "ImportConfirmOut | None" = None
    confirmed_at: datetime | None = None


class ImportConfirmOut(ChangeImpactOut):
    import_id: int
    status: ImportStatus
    confirmed_at: datetime | None = None
    result: ImportResultOut


ImportPreviewOut.model_rebuild()
