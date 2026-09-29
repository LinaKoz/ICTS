"""Approval (§3 `roster_approvals`, §6, P11, P12, T8): grant, manual
revoke, the preview the UI acknowledges against, the audit-trail read,
and `revoke(...)`, which every automatic invalidation goes through:

- EDIT: `edits.py` (T7), ref None
- REGENERATE: `save.py` (replace of an approved roster), ref None
- CONTRACT_CHANGE: `changes/service.py` (contract apply; CSV confirm uses
  the same change set), ref `contract_version:{id}`
- WORKER_CHANGE: `changes/service.py` (role/status change), ref `worker:{id}`
- MANUAL: the manager's revoke endpoint below

Soft shortages (coverage gaps, minimum-hour shortfalls) can be
acknowledged; hard violations never can (P11). The acknowledgement is
bound to the shortages the manager saw by `warnings_fingerprint`.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_schemas.approval import ApprovalPreviewOut, ApprovalResultOut, ApproveRequest, RevokeRequest
from app.api_schemas.common import CoverageGapOut, HourShortfallOut, error_responses
from app.api_schemas.rosters import AcknowledgedWarningsOut, ApprovalEventOut
from app.auth.models import User
from app.auth.session import require_role
from app.db import get_session, take_scheduling_lock
from app.errors import (
    AlreadyApprovedError,
    HardViolationsError,
    LockedShiftError,
    NotApprovedError,
    NotFoundError,
    StalePreviewError,
    VersionConflictError,
    WarningsNotAcknowledgedError,
)
from app.rosters.evaluation import Evaluation, evaluate
from app.rosters.models import Roster, RosterApproval
from app.rosters.problem_builder import MONTH_PATTERN, is_history_month, parse_month
from app.rosters.serialize import coverage_gap_to_out, hour_shortfall_to_out, violation_to_out

REVOKE_CAUSES = ("EDIT", "REGENERATE", "CONTRACT_CHANGE", "WORKER_CHANGE", "MANUAL")

router = APIRouter(prefix="/api/rosters", tags=["approval"])


async def revoke(
    session: AsyncSession,
    roster: Roster,
    cause: str,
    ref: str | None,
    revoked_by: int,
    now: datetime | None = None,
    reason: str | None = None,
) -> None:
    """Revokes the roster's current (unrevoked) approval, if any, and
    returns the roster to DRAFT. A no-op on the approval row if the
    roster has none -- the roster is still forced to DRAFT."""
    now = now or datetime.now(timezone.utc)
    stmt = (
        select(RosterApproval)
        .where(RosterApproval.roster_id == roster.id, RosterApproval.revoked_at.is_(None))
        .order_by(RosterApproval.approved_at.desc())
        .limit(1)
    )
    approval = (await session.execute(stmt)).scalar_one_or_none()
    if approval is not None:
        approval.revoked_at = now
        approval.revoked_by = revoked_by
        approval.revoke_cause = cause
        approval.revoke_ref = ref
        approval.revoke_reason = reason
    roster.status = "DRAFT"


# --- soft shortages and their fingerprint ------------------------------------


def warnings_fingerprint(gaps: list[CoverageGapOut], shortfalls: list[HourShortfallOut]) -> str:
    """sha256 over the canonical, sorted soft-shortage set. Independent of
    engine ordering; changes when any gap or shortfall (or its size) does."""
    gap_rows = sorted(
        [g.date.isoformat(), g.shift, g.role, g.required, g.assigned, g.locked] for g in gaps
    )
    shortfall_rows = sorted(
        [s.worker_id, s.min_hours, s.assigned_hours, s.missing_hours] for s in shortfalls
    )
    payload = json.dumps({"gaps": gap_rows, "shortfalls": shortfall_rows}, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def soft_shortages(ev: Evaluation) -> tuple[list[CoverageGapOut], list[HourShortfallOut]]:
    # `metrics.coverage_gaps` lists every demanded slot (covered ones have missing == 0).
    gaps = [coverage_gap_to_out(g) for g in ev.metrics.coverage_gaps if g.missing > 0]
    shortfalls = [hour_shortfall_to_out(h) for h in ev.metrics.hour_shortfalls if h.missing_hours > 0]
    return gaps, shortfalls


def _hard_violations(ev: Evaluation) -> list:
    no_contract = {str(w) for w in ev.no_contract_worker_ids}
    return [violation_to_out(v, no_contract) for v in ev.violations]


# --- audit trail ---------------------------------------------------------------


async def load_approval_history(session: AsyncSession, roster_id: int) -> list[ApprovalEventOut]:
    """Every approval of the roster (with its revocation, if any), oldest first."""
    rows = (
        (
            await session.execute(
                select(RosterApproval)
                .where(RosterApproval.roster_id == roster_id)
                .order_by(RosterApproval.approved_at, RosterApproval.id)
            )
        )
        .scalars()
        .all()
    )
    user_ids = {r.approved_by for r in rows} | {r.revoked_by for r in rows if r.revoked_by is not None}
    names: dict[int, str] = {}
    if user_ids:
        users = (await session.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()
        names = {u.id: u.display_name for u in users}
    return [_event_out(r, names) for r in rows]


def _event_out(r: RosterApproval, names: dict[int, str]) -> ApprovalEventOut:
    return ApprovalEventOut(
        approved_by=names.get(r.approved_by, "unknown"),
        approved_at=r.approved_at.isoformat(),
        reason=r.reason,
        revoked_at=r.revoked_at.isoformat() if r.revoked_at else None,
        revoke_cause=r.revoke_cause,  # type: ignore[arg-type]
        id=r.id,
        roster_version=r.roster_version,
        acknowledged_warnings=AcknowledgedWarningsOut.model_validate(r.acknowledged_warnings)
        if r.acknowledged_warnings
        else None,
        revoke_ref=r.revoke_ref,
        revoked_by=names.get(r.revoked_by, "unknown") if r.revoked_by is not None else None,
        revoke_reason=r.revoke_reason,
    )


# --- endpoints ---------------------------------------------------------------

MonthPath = Annotated[str, Path(pattern=MONTH_PATTERN, description="YYYY-MM")]


async def _load_roster(session: AsyncSession, month: str) -> Roster:
    roster = (await session.execute(select(Roster).where(Roster.month == parse_month(month)))).scalar_one_or_none()
    if roster is None:
        raise NotFoundError(f"no roster for {month}")
    return roster


@router.get(
    "/{month}/approval-preview",
    response_model=ApprovalPreviewOut,
    responses=error_responses(401, 403, 404, 422),
)
async def approval_preview(
    month: MonthPath,
    _user: User = Depends(require_role("PLANNER", "MANAGER")),
    session: AsyncSession = Depends(get_session),
) -> ApprovalPreviewOut:
    """The hard violations and soft shortages approval would face, and the
    fingerprint to send back with the acknowledgement."""
    roster = await _load_roster(session, month)
    history = is_history_month(roster.month)
    ev = await evaluate(session, roster)
    hard = _hard_violations(ev)
    gaps, shortfalls = soft_shortages(ev)
    return ApprovalPreviewOut(
        version=roster.row_version,
        status=roster.status,  # type: ignore[arg-type]
        is_history=history,
        hard_violations=hard,
        coverage_gaps=gaps,
        hour_shortfalls=shortfalls,
        warnings_fingerprint=warnings_fingerprint(gaps, shortfalls),
        requires_acknowledgement=bool(gaps or shortfalls),
        can_approve=roster.status == "DRAFT" and not history and not hard,
    )


@router.post(
    "/{month}/approve",
    response_model=ApprovalResultOut,
    responses=error_responses(401, 403, 404, 409, 422),
)
async def approve(
    month: MonthPath,
    body: ApproveRequest,
    user: User = Depends(require_role("MANAGER")),
    session: AsyncSession = Depends(get_session),
) -> ApprovalResultOut:
    await take_scheduling_lock(session)
    roster = await _load_roster(session, month)
    if roster.row_version != body.expected_version:
        raise VersionConflictError(
            f"the roster is at version {roster.row_version}, not {body.expected_version}; reload it",
            details={"current_version": roster.row_version},
        )
    if is_history_month(roster.month):
        raise LockedShiftError("rosters of past months are read-only history and cannot be approved")
    if roster.status == "APPROVED":
        raise AlreadyApprovedError("this roster is already approved")

    ev = await evaluate(session, roster)
    hard = _hard_violations(ev)
    if hard:  # P11: never acknowledgeable, whatever the request says
        raise HardViolationsError(
            "the roster has hard violations and cannot be approved",
            details=[v.model_dump(mode="json") for v in hard],
        )

    gaps, shortfalls = soft_shortages(ev)
    fingerprint = warnings_fingerprint(gaps, shortfalls)
    reason = (body.reason or "").strip() or None
    snapshot: dict | None = None
    if gaps or shortfalls:
        if not body.acknowledge_warnings or reason is None or body.warnings_fingerprint is None:
            raise WarningsNotAcknowledgedError(
                "the roster has coverage gaps or hour shortfalls: approving needs acknowledge_warnings, "
                "a reason and the warnings_fingerprint of the shortages shown",
                details={"warnings_fingerprint": fingerprint, "coverage_gaps": len(gaps), "hour_shortfalls": len(shortfalls)},
            )
        snapshot = AcknowledgedWarningsOut(
            warnings_fingerprint=fingerprint, coverage_gaps=gaps, hour_shortfalls=shortfalls
        ).model_dump(mode="json")
    if body.warnings_fingerprint is not None and body.warnings_fingerprint != fingerprint:
        raise StalePreviewError(
            "the shortages changed since you reviewed them; review the current list",
            details={"warnings_fingerprint": fingerprint},
        )

    approval = RosterApproval(
        roster_id=roster.id,
        roster_version=roster.row_version,
        approved_by=user.id,
        approved_at=datetime.now(timezone.utc),
        acknowledged_warnings=snapshot,
        reason=reason,
    )
    session.add(approval)
    roster.status = "APPROVED"
    await session.flush()
    event = _event_out(approval, {user.id: user.display_name})
    await session.commit()
    return ApprovalResultOut(version=roster.row_version, status="APPROVED", event=event)


@router.post(
    "/{month}/revoke",
    response_model=ApprovalResultOut,
    responses=error_responses(401, 403, 404, 409, 422),
)
async def revoke_approval(
    month: MonthPath,
    body: RevokeRequest,
    user: User = Depends(require_role("MANAGER")),
    session: AsyncSession = Depends(get_session),
) -> ApprovalResultOut:
    """Manager revokes the current approval by hand (cause MANUAL); the roster returns to DRAFT."""
    await take_scheduling_lock(session)
    roster = await _load_roster(session, month)
    if roster.row_version != body.expected_version:
        raise VersionConflictError(
            f"the roster is at version {roster.row_version}, not {body.expected_version}; reload it",
            details={"current_version": roster.row_version},
        )
    if roster.status != "APPROVED":
        raise NotApprovedError("this roster is not approved")
    reason = (body.reason or "").strip() or None
    await revoke(session, roster, cause="MANUAL", ref=None, revoked_by=user.id, reason=reason)
    await session.flush()
    history = await load_approval_history(session, roster.id)
    await session.commit()
    return ApprovalResultOut(version=roster.row_version, status="DRAFT", event=history[-1])
