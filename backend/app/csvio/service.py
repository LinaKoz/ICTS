"""CSV import preview and confirm (§6 "CSV", P8, P9, P14).

Preview classifies each parsed row against the database (NEW, UNCHANGED,
CHANGED, INVALID), builds ONE change set for the existing workers it would
touch and asks `changes.service.preview_change_set` for the impact (affected
rosters, `invalidates_approved`, `locked_violations`). The whole preview plus
the base state it was computed from is stored in `csv_imports.preview`.

Confirm runs in one transaction: scheduling lock, flip PENDING -> CONFIRMED
(409 `ALREADY_CONFIRMED` if it did not flip), stale check of the stored base
(409 `STALE_PREVIEW` with a fresh preview, nothing applied), create new workers,
then `changes.service.apply_change_set` for updates and contract versions
(which revalidates rosters and revokes approvals), then store the result.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_schemas.csv import (
    FieldDiffOut,
    ImportConfirmOut,
    ImportContractOut,
    ImportCountsOut,
    ImportPreviewOut,
    ImportResultOut,
    ImportRowOut,
    RowErrorOut,
)
from app.changes.service import (
    ChangeSet,
    ContractDraft,
    WorkerUpdate,
    affected_rosters,
    apply_change_set,
    is_retroactive,
    preview_change_set,
)
from app.contracts.models import ContractVersion
from app.contracts.resolve import resolve_contracts_for_workers
from app.csvio.models import CsvImport
from app.csvio.parse import ParsedContract, ParsedRow, RowError, per_day_form
from app.db import take_scheduling_lock
from app.errors import AlreadyConfirmedError, NotFoundError, StalePreviewError, ValidationAppError
from app.rosters.models import Roster
from app.rosters.problem_builder import compute_free_from
from app.workers.models import Worker
from app.workers.serialize import impact_fields, month_str, worker_names

DEFAULT_DECISION = "APPROVE"


class StaleImportError(StalePreviewError):
    """The base state moved since the preview was computed."""


@dataclass
class _Classified:
    row: ParsedRow
    classification: str
    contract_action: str = "NONE"
    changes: list[FieldDiffOut] = field(default_factory=list)
    worker_id: int | None = None  # ids and versions, not ORM objects: the preview's savepoint rollback expires them
    worker_version: int | None = None
    retroactive: bool = False


def _fmt_contract(c: ContractVersion | ParsedContract | None) -> dict[str, str] | None:
    if c is None:
        return None
    return {
        "hourly_rate_ils": f"{Decimal(c.hourly_rate_ils):.2f}",
        "min_monthly_hours": str(c.min_hours),
        "max_monthly_hours": str(c.max_hours),
        "availability": per_day_form(list(c.availability)),
    }


def _same_contract(prev: ContractVersion, new: ParsedContract) -> bool:
    """P5: same rule as the change-set service."""
    return (
        prev.hourly_rate_ils == new.hourly_rate_ils
        and prev.min_hours == new.min_hours
        and prev.max_hours == new.max_hours
        and set(prev.availability) == set(new.availability)
    )


async def _classify(
    session: AsyncSession, rows: list[ParsedRow], now: datetime
) -> tuple[list[_Classified], dict[int, int]]:
    """Classifies rows; also returns each existing worker's latest contract id."""
    valid = [r for r in rows if not r.errors]
    workers: dict[str, Worker] = {}
    if valid:
        found = await session.execute(select(Worker).where(Worker.national_id.in_([r.national_id for r in valid])))
        workers = {w.national_id: w for w in found.scalars()}
    latest: dict[int, int] = {}
    if workers:
        stmt = (
            select(ContractVersion.worker_id, func.max(ContractVersion.id))
            .where(ContractVersion.worker_id.in_([w.id for w in workers.values()]))
            .group_by(ContractVersion.worker_id)
        )
        latest = {wid: cid for wid, cid in (await session.execute(stmt)).all()}
    # One bulk resolve per distinct effective month (same rule as `resolve_contract`).
    resolved: dict[date, dict[int, ContractVersion]] = {}
    for m in {r.effective_month for r in valid if r.contract and r.national_id in workers}:
        resolved[m] = await resolve_contracts_for_workers(session, [w.id for w in workers.values()], m)

    out: list[_Classified] = []
    for r in rows:
        if r.errors:
            out.append(_Classified(r, "INVALID"))
            continue
        w = workers.get(r.national_id)
        c = _Classified(r, "NEW" if w is None else "UNCHANGED", worker_id=w.id if w else None, worker_version=w.row_version if w else None)
        prev = resolved.get(r.effective_month, {}).get(w.id) if (w and r.contract) else None
        if w is None:
            c.changes = [
                FieldDiffOut(field=f, old=None, new=v)
                for f, v in (("full_name", r.full_name), ("role", r.role), ("status", r.status))
            ]
        else:
            for f, old, new in (
                ("full_name", w.full_name, r.full_name),
                ("role", w.role, r.role),
                ("status", w.status, r.status),
            ):
                if old != new:
                    c.changes.append(FieldDiffOut(field=f, old=old, new=new))
        if r.contract:
            if prev is not None and _same_contract(prev, r.contract):
                c.contract_action = "UNCHANGED"
            else:
                c.contract_action = "NEW_VERSION"
                old_c, new_c = _fmt_contract(prev), _fmt_contract(r.contract)
                for f in ("hourly_rate_ils", "min_monthly_hours", "max_monthly_hours", "availability"):
                    if old_c is None or old_c[f] != new_c[f]:
                        c.changes.append(FieldDiffOut(field=f, old=old_c[f] if old_c else None, new=new_c[f]))
                c.retroactive = is_retroactive(r.effective_month, now)
        if w is not None and (c.changes or c.contract_action == "NEW_VERSION"):
            c.classification = "CHANGED"
        out.append(c)
    return out, latest


def _row_out(c: _Classified) -> ImportRowOut:
    r = c.row
    return ImportRowOut(
        line=r.line,
        national_id=r.national_id,
        full_name=r.full_name,
        role=r.role,
        status=r.status,
        effective_month=month_str(r.effective_month) if r.effective_month else None,
        contract=ImportContractOut(
            hourly_rate_ils=f"{r.contract.hourly_rate_ils:.2f}",
            min_hours=r.contract.min_hours,
            max_hours=r.contract.max_hours,
            availability=list(r.contract.availability),
        )
        if r.contract
        else None,
        classification=c.classification,
        contract_action=c.contract_action,
        retroactive=c.retroactive,
        changes=c.changes,
        errors=[RowErrorOut(code=e.code, message=e.message, field=e.field) for e in r.errors],
        export_row=r.export_row,
        worker_id=c.worker_id,
    )


def _draft(c: _Classified, worker_id: int, import_id: int | None) -> ContractDraft:
    r = c.row
    assert r.contract is not None and r.effective_month is not None
    return ContractDraft(
        worker_id=worker_id,
        effective_month=r.effective_month,
        hourly_rate_ils=r.contract.hourly_rate_ils,
        min_hours=r.contract.min_hours,
        max_hours=r.contract.max_hours,
        availability=tuple(r.contract.availability),
        source="CSV",
        import_id=import_id,
    )


def _update(c: _Classified) -> WorkerUpdate | None:
    diffs = {d.field: d.new for d in c.changes if d.field in ("full_name", "role", "status")}
    if not diffs or c.worker_id is None or c.classification == "NEW":
        return None
    return WorkerUpdate(worker_id=c.worker_id, **diffs)


def _change_set(items: list[_Classified], actor_id: int, import_id: int | None) -> ChangeSet:
    """One change set: worker updates and contract drafts for the given rows.
    In a preview, NEW workers do not exist yet and cannot affect a roster, so
    they are skipped (`worker_id is None`); at confirm they have been created."""
    updates, contracts = [], []
    for c in items:
        if c.worker_id is None:
            continue
        if (u := _update(c)) is not None:
            updates.append(u)
        if c.contract_action == "NEW_VERSION":
            contracts.append(_draft(c, c.worker_id, import_id))
    ref = f"import:{import_id}" if import_id is not None else None
    return ChangeSet(actor_id=actor_id, worker_updates=tuple(updates), contracts=tuple(contracts), worker_change_ref=ref, contract_change_ref=ref)


def rows_from_stored(preview: dict) -> list[ParsedRow]:
    """Rebuilds parsed rows from a stored preview (fresh preview after a stale confirm)."""
    out = []
    for r in preview["rows"]:
        contract = r["contract"]
        out.append(
            ParsedRow(
                line=r["line"],
                national_id=r["national_id"],
                full_name=r["full_name"],
                role=r["role"],
                status=r["status"],
                effective_month=date.fromisoformat(r["effective_month"] + "-01") if r["effective_month"] else None,
                contract=ParsedContract(
                    Decimal(contract["hourly_rate_ils"]), contract["min_hours"], contract["max_hours"], contract["availability"]
                )
                if contract
                else None,
                errors=[RowError(e["code"], e["message"], e.get("field")) for e in r["errors"]],
                export_row=r["export_row"],
            )
        )
    return out


def _free_from(month: date, now: datetime) -> list:
    d, s = compute_free_from(month, now)
    return [d.isoformat(), getattr(s, "value", s)]


async def create_preview(
    session: AsyncSession,
    rows: list[ParsedRow],
    unknown_columns: list[str],
    actor_id: int,
    now: datetime,
    default_month: date,
) -> ImportPreviewOut:
    """Classifies, computes the impact, stores a PENDING import and returns
    the preview. Takes the scheduling lock; the caller commits."""
    await take_scheduling_lock(session)
    classified, latest = await _classify(session, rows, now)
    actionable = [c for c in classified if c.classification in ("NEW", "CHANGED")]
    impact = await preview_change_set(session, _change_set(actionable, actor_id, None), now)

    record = CsvImport(created_by=actor_id, preview={})
    session.add(record)
    await session.flush()
    await session.refresh(record)

    counts = {k: sum(1 for c in classified if c.classification == k) for k in ("NEW", "CHANGED", "UNCHANGED", "INVALID")}
    out = ImportPreviewOut(
        id=record.id,
        status="PENDING",
        created_at=record.created_at,
        default_effective_month=month_str(default_month),
        counts=ImportCountsOut(
            new=counts["NEW"], changed=counts["CHANGED"], unchanged=counts["UNCHANGED"], invalid=counts["INVALID"]
        ),
        unknown_columns=unknown_columns,
        rows=[_row_out(c) for c in classified],
        **impact_fields(impact, await worker_names(session)),
    )
    base = {
        "workers": {
            c.row.national_id: [c.worker_id, c.worker_version, latest.get(c.worker_id)]
            for c in classified
            if c.worker_id is not None
        },
        "new": [c.row.national_id for c in classified if c.classification == "NEW"],
        "rosters": {
            str(r.roster_id): [r.month.isoformat(), r.version, r.status, _free_from(r.month, now)] for r in impact.rosters
        },
    }
    record.preview = {**out.model_dump(mode="json"), "base": base}
    await session.flush()
    return out


def preview_from_record(record: CsvImport) -> ImportPreviewOut:
    data = {k: v for k, v in record.preview.items() if k not in ("base", "result")}
    data["status"] = record.status
    data["confirmed_at"] = record.confirmed_at
    data["result"] = record.result
    return ImportPreviewOut.model_validate(data)


async def get_import(session: AsyncSession, import_id: int) -> CsvImport:
    record = await session.get(CsvImport, import_id)
    if record is None:
        raise NotFoundError(f"import {import_id} not found")
    return record


async def _stale_reasons(
    session: AsyncSession, base: dict, approved: set[str], cs: ChangeSet, now: datetime
) -> list[str]:
    reasons: list[str] = []
    for nid, (wid, version, latest_cid) in base["workers"].items():
        if nid not in approved:
            continue
        w = await session.get(Worker, wid)
        cur = (
            await session.execute(select(func.max(ContractVersion.id)).where(ContractVersion.worker_id == wid))
        ).scalar_one()
        if w is None or w.row_version != version or cur != latest_cid:
            reasons.append(f"worker {nid} changed")
    new_ids = [n for n in base["new"] if n in approved]
    if new_ids:
        taken = (await session.execute(select(Worker.national_id).where(Worker.national_id.in_(new_ids)))).scalars().all()
        reasons += [f"worker {n} was created" for n in taken]
    for rid, (month, version, status, free_from) in base["rosters"].items():
        r = await session.get(Roster, int(rid))
        if r is None or r.row_version != version or r.status != status or _free_from(r.month, now) != free_from:
            reasons.append(f"roster {month[:7]} changed")
    # A roster the approved rows touch now but the preview never showed (e.g.
    # saved with one of these workers after the preview) is a moved base too.
    for r in await affected_rosters(session, cs, now):
        if str(r.id) not in base["rosters"]:
            reasons.append(f"roster {r.month:%Y-%m} is now affected")
    return reasons


def _from_stored(row: dict, stored: ParsedRow) -> _Classified:
    return _Classified(
        row=stored,
        classification=row["classification"],
        contract_action=row["contract_action"],
        changes=[FieldDiffOut(**d) for d in row["changes"]],
        worker_id=row["worker_id"],
        retroactive=row["retroactive"],
    )


async def confirm_import(
    session: AsyncSession, import_id: int, decisions: dict[str, str], actor_id: int, now: datetime
) -> ImportConfirmOut:
    """Applies the approved rows. Raises `AlreadyConfirmedError` (details =
    the stored result) or `StaleImportError`; the caller rolls back on any
    exception, which also undoes the PENDING -> CONFIRMED flip."""
    await take_scheduling_lock(session)
    flipped = (
        await session.execute(
            update(CsvImport)
            .where(CsvImport.id == import_id, CsvImport.status == "PENDING")
            .values(status="CONFIRMED", confirmed_at=now, confirmed_by=actor_id)
            .returning(CsvImport.id)
        )
    ).scalar_one_or_none()
    record = await get_import(session, import_id)
    if flipped is None:
        raise AlreadyConfirmedError("this import was already confirmed", details=record.result)
    await session.refresh(record)

    stored = record.preview
    base = stored["base"]
    known = {r["national_id"] for r in stored["rows"]}
    unknown = sorted(set(decisions) - known)
    if unknown:
        raise ValidationAppError(
            "decisions name national IDs that are not in this import",
            details=[{"loc": ["body", "decisions", n], "message": "not in this import", "type": "unknown_row"} for n in unknown],
        )

    parsed = rows_from_stored(stored)
    approved: list[_Classified] = []
    skipped = 0
    for raw, p in zip(stored["rows"], parsed):
        if raw["classification"] not in ("NEW", "CHANGED"):
            continue
        if decisions.get(p.national_id, DEFAULT_DECISION) != "APPROVE":
            skipped += 1
            continue
        approved.append(_from_stored(raw, p))

    reasons = await _stale_reasons(
        session, base, {c.row.national_id for c in approved}, _change_set(approved, actor_id, import_id), now
    )
    if reasons:
        raise StaleImportError("the data changed since the preview; review the new preview", details=reasons)

    # New workers first, so their contract drafts can reference ids.
    created = 0
    new_workers: list[tuple[_Classified, Worker]] = []
    for c in approved:
        if c.classification == "NEW":
            r = c.row
            w = Worker(national_id=r.national_id, full_name=r.full_name, role=r.role, status=r.status)
            session.add(w)
            new_workers.append((c, w))
            created += 1
    await session.flush()
    for c, w in new_workers:
        c.worker_id = w.id

    result = await apply_change_set(session, _change_set(approved, actor_id, import_id), None, now)

    revoked = [r for r in result.impact.rosters if r.revokes_approval]
    counts = stored["counts"]
    out = ImportConfirmOut(
        import_id=import_id,
        status="CONFIRMED",
        confirmed_at=now,
        result=ImportResultOut(
            created_workers=created,
            updated_workers=len(result.changed_workers),
            contract_versions_created=len(result.new_versions),
            unchanged=counts["unchanged"],
            invalid=counts["invalid"],
            skipped=skipped,
            revoked_rosters=[month_str(r.month) for r in revoked],
        ),
        **impact_fields(result.impact, await worker_names(session)),
    )
    record.result = out.model_dump(mode="json")
    await session.flush()
    return out


async def fresh_preview(session: AsyncSession, import_id: int, actor_id: int, now: datetime) -> ImportPreviewOut:
    """A new PENDING import recomputed from the stored rows against current data."""
    record = await get_import(session, import_id)
    return await create_preview(
        session,
        rows_from_stored(record.preview),
        record.preview["unknown_columns"],
        actor_id,
        now,
        date.fromisoformat(record.preview["default_effective_month"] + "-01"),
    )
