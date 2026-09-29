"""Change-set service (§2 `app/changes/`, §6, P1, P2, P5, P7, D9): the one
place that applies worker and contract changes and works out their
impact on rosters. Shared by the worker/contract UI now and by CSV
import confirm (T6) later.

A `ChangeSet` is a list of worker updates (national id, name, role,
status) and contract drafts (new immutable versions). Two entry points:

- `preview_change_set`: dry run. Applies the change set inside a SAVEPOINT,
  evaluates every affected roster with `rosters.evaluation.evaluate`, and
  rolls the savepoint back, so the preview is exactly what apply does.
- `apply_change_set`: takes the scheduling lock, verifies the base
  fingerprint (409 `STALE_PREVIEW` with nothing applied), applies, and
  revalidates. An approved roster that gains a hard violation
  (`worsened(before, after)` non-empty) has its approval revoked through
  `approval.revoke` and returns to DRAFT. Assignments are never touched.
  The caller commits.

Locked vs editable (P2, D8): a new hard violation is *locked* when it
cannot be removed by editing free assignments of that roster, i.e. the
free assignments it involves cannot cover its magnitude (MAX_HOURS
counts 8 hours per assignment). Started shifts are immutable (P3).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.models import ContractVersion
from app.contracts.resolve import resolve_contract
from app.db import take_scheduling_lock
from app.errors import NotFoundError, StalePreviewError
from app.rosters.approval import revoke
from app.rosters.evaluation import evaluate
from app.rosters.models import Roster, RosterAssignment
from app.rosters.problem_builder import _pos, compute_free_from, is_history_month
from app.scheduling.types import Assignment, Violation, ViolationCode, worsened
from app.timeutil import now_israel
from app.workers.models import Worker, WorkerFieldHistory

_HOURS_PER_SHIFT = 8


# --- inputs ------------------------------------------------------------------


@dataclass(frozen=True)
class WorkerUpdate:
    """Desired worker fields; `None` = leave as is. A field equal to the
    current value is a no-op (P5)."""

    worker_id: int
    national_id: str | None = None
    full_name: str | None = None
    role: str | None = None
    status: str | None = None


@dataclass(frozen=True)
class ContractDraft:
    """A proposed new immutable contract version. `availability` is the
    normalised sorted list (`contracts.availability`)."""

    worker_id: int
    effective_month: date
    hourly_rate_ils: Decimal
    min_hours: int
    max_hours: int
    availability: tuple[str, ...]
    source: str = "UI"
    import_id: int | None = None


@dataclass(frozen=True)
class ChangeSet:
    actor_id: int
    worker_updates: tuple[WorkerUpdate, ...] = ()
    contracts: tuple[ContractDraft, ...] = ()
    # Stored on a revoked approval (`roster_approvals.revoke_ref`) for status/role changes.
    worker_change_ref: str | None = None
    # Same for a contract-version change; defaults to `contract_version:{id}` of the first new version.
    contract_change_ref: str | None = None


# --- outputs -----------------------------------------------------------------


@dataclass
class LockedViolation:
    month: date
    violation: Violation
    assignment: Assignment  # the started-shift assignment the violation is about


@dataclass
class AffectedRoster:
    roster_id: int
    month: date
    status: str  # before the change
    version: int
    is_history: bool  # P3: listed, never revalidated or revoked
    worker_ids: list[int]
    assignment_count: int  # assignments of the changed workers in this roster
    new_violations: list[Violation] = field(default_factory=list)
    locked_violations: list[LockedViolation] = field(default_factory=list)
    revokes_approval: bool = False
    no_contract_worker_ids: set[str] = field(default_factory=set)


@dataclass
class PlannedContract:
    draft: ContractDraft
    previous: ContractVersion | None  # resolved at the draft's effective month
    unchanged: bool  # P5: identical to `previous`, no version is created


@dataclass
class ChangeImpact:
    rosters: list[AffectedRoster]
    contracts: list[PlannedContract]
    fingerprint: str

    @property
    def invalidates_approved(self) -> bool:
        return any(r.revokes_approval for r in self.rosters)

    @property
    def locked_violations(self) -> list[LockedViolation]:
        return [lv for r in self.rosters for lv in r.locked_violations]


@dataclass
class ApplyResult:
    impact: ChangeImpact
    new_versions: list[ContractVersion]
    changed_workers: list[Worker]


class StaleChangeSetError(StalePreviewError):
    """The base state moved since the preview. Carries a fresh preview."""

    def __init__(self, message: str, fresh: ChangeImpact) -> None:
        super().__init__(message)
        self.fresh = fresh


# --- helpers -----------------------------------------------------------------


def month_start(now: datetime) -> date:
    return date(now.year, now.month, 1)


def is_retroactive(effective_month: date, now: datetime | None = None) -> bool:
    """P2: an effective month up to the current Israel month applies to
    shifts that have already started (or to read-only history)."""
    return effective_month <= month_start(now or now_israel())


def _contract_matches(previous: ContractVersion, draft: ContractDraft) -> bool:
    return (
        previous.hourly_rate_ils == draft.hourly_rate_ils
        and previous.min_hours == draft.min_hours
        and previous.max_hours == draft.max_hours
        and set(previous.availability) == set(draft.availability)
    )


def is_locked_violation(v: Violation, month: date, free_from: tuple[date, object]) -> bool:
    """See module docstring. Only assignments inside this roster's month
    count: neighbour-month assignments (adjacency pairs) live in another
    roster."""
    in_month = [a for a in v.assignments if (a.date.year, a.date.month) == (month.year, month.month)]
    if not in_month:
        return False
    free = [a for a in in_month if _pos(a.date, a.shift) >= _pos(*free_from)]
    weight = _HOURS_PER_SHIFT if v.code is ViolationCode.MAX_HOURS else 1
    return len(free) * weight < v.magnitude


async def _plan_contracts(session: AsyncSession, cs: ChangeSet) -> list[PlannedContract]:
    planned = []
    for draft in cs.contracts:
        previous = await resolve_contract(session, draft.worker_id, draft.effective_month)
        planned.append(PlannedContract(draft, previous, previous is not None and _contract_matches(previous, draft)))
    return planned


async def _min_months(
    session: AsyncSession, cs: ChangeSet, planned: list[PlannedContract], now: datetime
) -> dict[int, date]:
    """Per touched worker, the first roster month the change can affect:
    a contract from its effective month, a status/role change from the
    current Israel month (P7). Name/ID-only edits affect no roster."""
    out: dict[int, date] = {}
    for p in planned:
        if not p.unchanged:
            wid = p.draft.worker_id
            out[wid] = min(out.get(wid, p.draft.effective_month), p.draft.effective_month)
    for wu in cs.worker_updates:
        if wu.role is None and wu.status is None:
            continue
        worker = await session.get(Worker, wu.worker_id)
        if worker is None:
            raise NotFoundError(f"worker {wu.worker_id} not found")
        if (wu.role is not None and wu.role != worker.role) or (wu.status is not None and wu.status != worker.status):
            out[wu.worker_id] = min(out.get(wu.worker_id, month_start(now)), month_start(now))
    return out


async def _candidate_rosters(
    session: AsyncSession, min_months: dict[int, date]
) -> tuple[list[Roster], dict[int, dict[int, int]]]:
    """Rosters (by month) that contain an assignment of a touched worker
    at or after that worker's first affected month, plus the assignment
    count per (roster, worker)."""
    counts: dict[int, dict[int, int]] = {}
    rosters: dict[int, Roster] = {}
    for wid, m in min_months.items():
        stmt = (
            select(Roster, func.count(RosterAssignment.id))
            .join(RosterAssignment, RosterAssignment.roster_id == Roster.id)
            .where(RosterAssignment.worker_id == wid, Roster.month >= m)
            .group_by(Roster.id)
        )
        for roster, n in (await session.execute(stmt)).all():
            rosters[roster.id] = roster
            counts.setdefault(roster.id, {})[wid] = n
    return sorted(rosters.values(), key=lambda r: r.month), counts


async def _fingerprint(
    session: AsyncSession,
    cs: ChangeSet,
    planned: list[PlannedContract],
    rosters: list[Roster],
    now: datetime,
) -> str:
    """The preview's base: touched workers' row versions and latest
    contract id, the affected rosters' version/status/free_from, and the
    proposed content. A preview is only valid against that exact state."""
    worker_ids = sorted({wu.worker_id for wu in cs.worker_updates} | {c.worker_id for c in cs.contracts})
    workers = []
    for wid in worker_ids:
        w = await session.get(Worker, wid)
        if w is None:
            raise NotFoundError(f"worker {wid} not found")
        latest = (
            await session.execute(select(func.max(ContractVersion.id)).where(ContractVersion.worker_id == wid))
        ).scalar_one()
        workers.append([wid, w.row_version, latest])
    payload = {
        "workers": workers,
        "rosters": [
            [r.month.isoformat(), r.row_version, r.status, [d.isoformat() if hasattr(d, "isoformat") else d.value for d in compute_free_from(r.month, now)]]
            for r in rosters
        ],
        "updates": sorted(
            [wu.worker_id, wu.national_id, wu.full_name, wu.role, wu.status] for wu in cs.worker_updates
        ),
        "contracts": sorted(
            [c.worker_id, c.effective_month.isoformat(), str(c.hourly_rate_ils), c.min_hours, c.max_hours, list(c.availability)]
            for c in cs.contracts
        ),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


async def _evaluate_all(session: AsyncSession, rosters: list[Roster], now: datetime) -> dict[int, tuple[list[Violation], tuple, set[str]] | None]:
    """Violations, free_from and no-contract ids per roster; `None` for
    read-only history (P3)."""
    out: dict[int, tuple[list[Violation], tuple, set[str]] | None] = {}
    for r in rosters:
        if is_history_month(r.month, now):
            out[r.id] = None
            continue
        ev = await evaluate(session, r, now)
        out[r.id] = (ev.violations, ev.built.problem.free_from, {str(i) for i in ev.no_contract_worker_ids})
    return out


async def _apply_ops(
    session: AsyncSession, cs: ChangeSet, planned: list[PlannedContract], now: datetime
) -> tuple[list[ContractVersion], list[Worker]]:
    changed_workers: list[Worker] = []
    for wu in cs.worker_updates:
        worker = await session.get(Worker, wu.worker_id)
        if worker is None:
            raise NotFoundError(f"worker {wu.worker_id} not found")
        dirty = False
        for attr in ("national_id", "full_name"):
            new = getattr(wu, attr)
            if new is not None and new != getattr(worker, attr):
                setattr(worker, attr, new)
                dirty = True
        for field_name, attr in (("STATUS", "status"), ("ROLE", "role")):
            new = getattr(wu, attr)
            old = getattr(worker, attr)
            if new is not None and new != old:
                setattr(worker, attr, new)
                session.add(
                    WorkerFieldHistory(
                        worker_id=worker.id,
                        field=field_name,
                        old_value=old,
                        new_value=new,
                        effective_at=now,
                        changed_by=cs.actor_id,
                    )
                )
                dirty = True
        if dirty:
            worker.row_version += 1
            worker.updated_at = now
            changed_workers.append(worker)
    await session.flush()

    versions: list[ContractVersion] = []
    for p in planned:
        if p.unchanged:
            continue
        d = p.draft
        latest_no = (
            await session.execute(select(func.max(ContractVersion.version_no)).where(ContractVersion.worker_id == d.worker_id))
        ).scalar_one()
        cv = ContractVersion(
            worker_id=d.worker_id,
            version_no=(latest_no or 0) + 1,
            effective_month=d.effective_month,
            hourly_rate_ils=d.hourly_rate_ils,
            min_hours=d.min_hours,
            max_hours=d.max_hours,
            availability=list(d.availability),
            created_by=cs.actor_id,
            source=d.source,
            import_id=d.import_id,
        )
        session.add(cv)
        versions.append(cv)
    await session.flush()
    return versions, changed_workers


def _build_impact(
    rosters: list[Roster],
    counts: dict[int, dict[int, int]],
    before: dict[int, tuple | None],
    after: dict[int, tuple | None],
    planned: list[PlannedContract],
    fingerprint: str,
) -> ChangeImpact:
    affected: list[AffectedRoster] = []
    for r in rosters:
        entry = AffectedRoster(
            roster_id=r.id,
            month=r.month,
            status=r.status,
            version=r.row_version,
            is_history=after[r.id] is None,
            worker_ids=sorted(counts[r.id]),
            assignment_count=sum(counts[r.id].values()),
        )
        if after[r.id] is not None and before[r.id] is not None:
            after_violations, free_from, no_contract = after[r.id]
            entry.no_contract_worker_ids = no_contract
            entry.new_violations = worsened(before[r.id][0], after_violations)
            for v in entry.new_violations:
                if is_locked_violation(v, r.month, free_from):
                    locked = next(
                        (a for a in v.assignments if _pos(a.date, a.shift) < _pos(*free_from)), v.assignments[0]
                    )
                    entry.locked_violations.append(LockedViolation(r.month, v, locked))
            entry.revokes_approval = r.status == "APPROVED" and bool(entry.new_violations)
        affected.append(entry)
    return ChangeImpact(rosters=affected, contracts=planned, fingerprint=fingerprint)


# --- entry points ------------------------------------------------------------


async def preview_change_set(session: AsyncSession, cs: ChangeSet, now: datetime | None = None) -> ChangeImpact:
    """Dry run: nothing is persisted. Leaves the session's transaction
    open (the scheduling lock is released when the caller ends it)."""
    now = now or now_israel()
    await take_scheduling_lock(session)
    planned = await _plan_contracts(session, cs)
    min_months = await _min_months(session, cs, planned, now)
    rosters, counts = await _candidate_rosters(session, min_months)
    fingerprint = await _fingerprint(session, cs, planned, rosters, now)
    before = await _evaluate_all(session, rosters, now)

    savepoint = await session.begin_nested()
    try:
        await _apply_ops(session, cs, planned, now)
        after = await _evaluate_all(session, rosters, now)
        # Built while the change is still visible, then discarded with the savepoint.
        return _build_impact(rosters, counts, before, after, planned, fingerprint)
    finally:
        await savepoint.rollback()


async def apply_change_set(
    session: AsyncSession,
    cs: ChangeSet,
    expected_fingerprint: str | None = None,
    now: datetime | None = None,
) -> ApplyResult:
    """Applies the change set in the caller's transaction (the caller
    commits). With `expected_fingerprint`, a moved base raises
    `StaleChangeSetError` before anything is written."""
    now = now or now_israel()
    await take_scheduling_lock(session)
    planned = await _plan_contracts(session, cs)
    min_months = await _min_months(session, cs, planned, now)
    rosters, counts = await _candidate_rosters(session, min_months)
    fingerprint = await _fingerprint(session, cs, planned, rosters, now)
    if expected_fingerprint is not None and fingerprint != expected_fingerprint:
        fresh = await preview_change_set(session, cs, now)
        raise StaleChangeSetError("the data changed since the preview; review the new preview", fresh)
    before = await _evaluate_all(session, rosters, now)

    versions, changed_workers = await _apply_ops(session, cs, planned, now)
    after = await _evaluate_all(session, rosters, now)
    impact = _build_impact(rosters, counts, before, after, planned, fingerprint)

    contract_ref = f"contract_version:{versions[0].id}" if versions else None
    for r, entry in zip(rosters, impact.rosters):
        if not entry.revokes_approval:
            continue
        # Contract changes win the cause when both kinds are in one set (CSV rows).
        if versions:
            cause, ref = "CONTRACT_CHANGE", cs.contract_change_ref or contract_ref
        else:
            cause, ref = "WORKER_CHANGE", cs.worker_change_ref
        await revoke(session, r, cause=cause, ref=ref, revoked_by=cs.actor_id, now=now)
        r.row_version += 1  # state changed: stale previews/saves must not match
    await session.flush()
    return ApplyResult(impact=impact, new_versions=versions, changed_workers=changed_workers)
