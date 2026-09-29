"""ORM/service values to the worker and contract API schemas (T5)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_schemas.workers import (
    AffectedRosterOut,
    ChangeImpactOut,
    ContractOut,
    FieldChangeOut,
    LockedViolationOut,
    WorkerOut,
)
from app.auth.models import User
from app.changes.service import AffectedRoster, ChangeImpact, LockedViolation
from app.contracts.models import ContractVersion
from app.rosters.serialize import violation_to_out
from app.workers.models import Worker, WorkerFieldHistory


async def user_names(session: AsyncSession) -> dict[int, str]:
    return {uid: name for uid, name in (await session.execute(select(User.id, User.display_name))).all()}


async def worker_names(session: AsyncSession) -> dict[str, str]:
    rows = (await session.execute(select(Worker.id, Worker.full_name))).all()
    return {str(wid): name for wid, name in rows}


def month_str(d) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def contract_to_out(cv: ContractVersion, users: dict[int, str]) -> ContractOut:
    return ContractOut(
        id=cv.id,
        worker_id=cv.worker_id,
        version_no=cv.version_no,
        effective_month=month_str(cv.effective_month),
        hourly_rate_ils=f"{cv.hourly_rate_ils:.2f}",
        min_hours=cv.min_hours,
        max_hours=cv.max_hours,
        availability=list(cv.availability),
        created_at=cv.created_at,
        created_by=users.get(cv.created_by, "unknown"),
        source=cv.source,
        import_id=cv.import_id,
    )


def worker_to_out(w: Worker, current: ContractVersion | None, users: dict[int, str]) -> WorkerOut:
    return WorkerOut(
        id=w.id,
        national_id=w.national_id,
        full_name=w.full_name,
        role=w.role,
        status=w.status,
        row_version=w.row_version,
        created_at=w.created_at,
        updated_at=w.updated_at,
        current_contract=contract_to_out(current, users) if current else None,
    )


def history_to_out(h: WorkerFieldHistory, users: dict[int, str]) -> FieldChangeOut:
    return FieldChangeOut(
        field=h.field,
        old_value=h.old_value,
        new_value=h.new_value,
        effective_at=h.effective_at,
        changed_by=users.get(h.changed_by, "unknown"),
    )


def _locked_to_out(lv: LockedViolation, no_contract: set[str], names: dict[str, str]) -> LockedViolationOut:
    a = lv.assignment
    return LockedViolationOut(
        month=month_str(lv.month),
        worker_id=a.worker_id,
        worker_name=names.get(a.worker_id, a.worker_id),
        date=a.date,
        shift=a.shift.value,
        code=violation_to_out(lv.violation, no_contract).code,
        magnitude=lv.violation.magnitude,
    )


def _affected_to_out(r: AffectedRoster, names: dict[str, str]) -> AffectedRosterOut:
    return AffectedRosterOut(
        month=month_str(r.month),
        roster_id=r.roster_id,
        status=r.status,
        version=r.version,
        is_history=r.is_history,
        worker_ids=[str(w) for w in r.worker_ids],
        assignment_count=r.assignment_count,
        new_violations=[violation_to_out(v, r.no_contract_worker_ids) for v in r.new_violations],
        locked_violations=[_locked_to_out(lv, r.no_contract_worker_ids, names) for lv in r.locked_violations],
        revokes_approval=r.revokes_approval,
    )


def impact_fields(impact: ChangeImpact, names: dict[str, str]) -> dict:
    """Keyword arguments for any `ChangeImpactOut` subclass."""
    rosters = [_affected_to_out(r, names) for r in impact.rosters]
    return {
        "affected_rosters": rosters,
        "invalidates_approved": impact.invalidates_approved,
        "locked_violations": [lv for r in rosters for lv in r.locked_violations],
    }


def impact_to_out(impact: ChangeImpact, names: dict[str, str]) -> ChangeImpactOut:
    return ChangeImpactOut(**impact_fields(impact, names))
