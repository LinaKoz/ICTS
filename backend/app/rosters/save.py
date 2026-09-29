"""`POST /rosters/{month}/save` (§6, T3).

Under the scheduling advisory lock: recomputes and checks the
fingerprint (409 `STALE_PREVIEW` on mismatch), rejects a body that
disagrees with stored started-shift assignments (422 `LOCKED_SHIFT`),
requires `replace_existing` + a matching version to replace an
existing roster (409 `VERSION_CONFLICT`), runs the validation gate
(422 `HARD_VIOLATIONS`), and saves as DRAFT -- revoking (`REGENERATE`)
an approval if one existed.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_schemas.rosters import SaveRequest, SaveResponseOut
from app.auth.models import User
from app.auth.session import require_role
from app.db import get_session, take_scheduling_lock
from app.errors import BadRequestError, HardViolationsError, LockedShiftError, StalePreviewError, VersionConflictError
from app.rosters.approval import revoke
from app.rosters.models import Roster, RosterAssignment
from app.rosters.problem_builder import _pos, build_problem, compute_fingerprint, is_history_month, parse_month
from app.rosters.serialize import violation_to_out
from app.scheduling.types import Assignment, Role, Shift, validate_roster, worsened

router = APIRouter(tags=["rosters"])


@router.post("/{month}/save", response_model=SaveResponseOut)
async def save(
    month: str,
    body: SaveRequest,
    user: User = Depends(require_role("PLANNER", "MANAGER")),
    session: AsyncSession = Depends(get_session),
) -> SaveResponseOut:
    month_date = parse_month(month)
    if is_history_month(month_date):
        raise LockedShiftError("cannot save a roster for a historical month")

    if any(not a.worker_id.isdigit() for a in body.assignments):
        raise BadRequestError("assignment worker_id must be a numeric worker id")

    await take_scheduling_lock(session)

    built = await build_problem(session, month_date, body.forbid_adjacent_shifts)
    fingerprint = await compute_fingerprint(session, built)
    if fingerprint != body.fingerprint:
        raise StalePreviewError("the roster's underlying data changed since generation; reload the preview")

    roster = built.roster
    free_from = built.problem.free_from

    locked_stored = {(a.worker_id, a.date, a.shift, a.role) for a in built.problem.fixed_assignments}
    locked_body = {
        (a.worker_id, a.date, Shift(a.shift), Role(a.role))
        for a in body.assignments
        if _pos(a.date, Shift(a.shift)) < _pos(*free_from)
    }
    if locked_body != locked_stored:
        raise LockedShiftError("assignments in already-started shifts must match the stored roster")

    if roster is not None:
        if not body.replace_existing or body.expected_version != roster.row_version:
            raise VersionConflictError("a roster already exists for this month; set replace_existing and expected_version")

    no_contract_ids = {str(wid) for wid in built.no_contract_worker_ids}
    after_assignments = [Assignment(a.worker_id, a.date, Shift(a.shift), Role(a.role)) for a in body.assignments]
    before_violations = validate_roster(built.problem, built.problem.fixed_assignments)
    after_violations = validate_roster(built.problem, after_assignments)
    gate_failures = worsened(before_violations, after_violations)
    if gate_failures:
        raise HardViolationsError(
            "the roster introduces new or worsened hard violations",
            details=[
                violation_to_out(v, no_contract_ids).model_dump(mode="json") for v in gate_failures
            ],
        )

    was_approved = roster is not None and roster.status == "APPROVED"
    if roster is None:
        roster = Roster(
            month=month_date,
            status="DRAFT",
            forbid_adjacent_shifts=body.forbid_adjacent_shifts,
            row_version=1,
            updated_by=user.id,
        )
        session.add(roster)
        await session.flush()
    else:
        roster.row_version += 1
        roster.forbid_adjacent_shifts = body.forbid_adjacent_shifts
        roster.updated_by = user.id
        roster.updated_at = func.now()
        if was_approved:
            await revoke(session, roster, cause="REGENERATE", ref=None, revoked_by=user.id)
        roster.status = "DRAFT"

    await session.execute(delete(RosterAssignment).where(RosterAssignment.roster_id == roster.id))
    for a in body.assignments:
        session.add(
            RosterAssignment(roster_id=roster.id, worker_id=int(a.worker_id), date=a.date, shift=a.shift, role=a.role)
        )

    await session.commit()
    return SaveResponseOut(roster_id=roster.id, version=roster.row_version, status=roster.status)
