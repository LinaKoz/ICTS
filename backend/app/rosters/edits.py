"""Manual edits (add, remove, move) and suggestions (§6, P3, P10, T7).

Every edit runs in one transaction under the scheduling advisory lock:
1. version check (409 `VERSION_CONFLICT`),
2. a touched started shift (or a historical month) is 422 `LOCKED_SHIFT`,
3. the P10 repair rule: `worsened(before, after)` must be empty (422
   `HARD_VIOLATIONS`); a plain removal always passes,
4. an approved roster needs `acknowledge_approved_edit` (409
   `APPROVED_EDIT_NOT_ACKNOWLEDGED`) and goes back to DRAFT through
   `approval.revoke(cause="EDIT")`,
5. `rosters.row_version` is incremented in the same transaction, so the
   generate/save fingerprint of the adjacent months changes too.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_schemas.common import error_responses
from app.api_schemas.edits import (
    AddAssignmentRequest,
    EditableAssignmentOut,
    EditResultOut,
    MoveAssignmentRequest,
    RemoveAssignmentRequest,
    SuggestionOut,
    SuggestionsOut,
    SwapAssignmentRequest,
)
from app.auth.models import User
from app.auth.session import require_role
from app.db import get_session, take_scheduling_lock
from app.errors import (
    ApprovedEditNotAcknowledgedError,
    BadRequestError,
    HardViolationsError,
    LockedShiftError,
    NotFoundError,
    ValidationAppError,
    VersionConflictError,
)
from app.rosters.approval import revoke
from app.rosters.models import Roster, RosterAssignment
from app.rosters.problem_builder import MONTH_PATTERN, BuiltProblem, _pos, build_problem, is_history_month, parse_month
from app.rosters.serialize import load_worker_refs, violation_to_out
from app.rosters.suggestions import replacements, suggest
from app.scheduling import Assignment, Role, Shift, Violation, ViolationCode, validate_roster, worsened
from app.workers.models import Worker

router = APIRouter(prefix="/api/rosters", tags=["rosters"])

MonthPath = Annotated[str, Path(pattern=MONTH_PATTERN, description="YYYY-MM")]


def _to_assignment(ra: RosterAssignment) -> Assignment:
    return Assignment(str(ra.worker_id), ra.date, Shift(ra.shift), Role(ra.role))


def _out(ra: RosterAssignment) -> EditableAssignmentOut:
    return EditableAssignmentOut(id=ra.id, worker_id=str(ra.worker_id), date=ra.date, shift=ra.shift, role=ra.role)


async def _load_stored(session: AsyncSession, roster: Roster) -> list[RosterAssignment]:
    stmt = select(RosterAssignment).where(RosterAssignment.roster_id == roster.id).order_by(RosterAssignment.id)
    return list((await session.execute(stmt)).scalars().all())


async def _begin_edit(
    session: AsyncSession, month: str, expected_version: int
) -> tuple[Roster, BuiltProblem, list[RosterAssignment]]:
    """Lock, load, check the version. Everything read afterwards is
    consistent with the lock."""
    month_date = parse_month(month)
    if is_history_month(month_date):
        raise LockedShiftError("rosters of past months are read-only history")
    await take_scheduling_lock(session)
    roster = (await session.execute(select(Roster).where(Roster.month == month_date))).scalar_one_or_none()
    if roster is None:
        raise NotFoundError(f"no roster for {month}")
    if roster.row_version != expected_version:
        raise VersionConflictError(
            f"the roster is at version {roster.row_version}, not {expected_version}; reload it",
            details={"current_version": roster.row_version},
        )
    built = await build_problem(session, month_date, roster.forbid_adjacent_shifts)
    return roster, built, await _load_stored(session, roster)


def _reject_locked(built: BuiltProblem, positions: Sequence[tuple[date, Shift]]) -> None:
    free_from = _pos(*built.problem.free_from)
    if any(_pos(d, s) < free_from for d, s in positions):
        raise LockedShiftError("that shift has already started and cannot be edited")


def _gate(built: BuiltProblem, before: list[Assignment], after: list[Assignment]) -> None:
    """P10: the edit must not introduce a new violation key or raise a magnitude."""
    problem = built.problem
    failures = worsened(validate_roster(problem, before), validate_roster(problem, after))
    if failures:
        no_contract = {str(w) for w in built.no_contract_worker_ids}
        raise HardViolationsError(
            "the edit would introduce new or worsened hard violations",
            details=[violation_to_out(v, no_contract).model_dump(mode="json") for v in failures],
        )


async def _commit_edit(
    session: AsyncSession, roster: Roster, user: User, acknowledge: bool
) -> bool:
    """Bumps the version, records the editor, and revokes an approval
    (needs the acknowledgement). Returns whether an approval was revoked."""
    revoked = False
    if roster.status == "APPROVED":
        if not acknowledge:
            raise ApprovedEditNotAcknowledgedError(
                "this roster is approved; editing returns it to draft and revokes the approval"
            )
        await revoke(session, roster, cause="EDIT", ref=None, revoked_by=user.id)
        revoked = True
    roster.row_version += 1
    roster.updated_by = user.id
    roster.updated_at = func.now()
    return revoked


async def _require_worker(session: AsyncSession, worker_id: str) -> None:
    if await session.get(Worker, int(worker_id)) is None:
        raise ValidationAppError(f"unknown worker {worker_id}")


async def _finish(session: AsyncSession, roster: Roster, revoked: bool, ra: RosterAssignment | None) -> EditResultOut:
    await session.commit()
    return EditResultOut(
        version=roster.row_version,
        status=roster.status,  # type: ignore[arg-type]
        approval_revoked=revoked,
        assignment=_out(ra) if ra is not None else None,
    )


@router.get(
    "/{month}/assignments",
    response_model=list[EditableAssignmentOut],
    responses=error_responses(401, 403, 404, 409, 422),
)
async def list_assignments(
    month: MonthPath,
    version: Annotated[int | None, Query(description="the roster version the caller shows; 409 if the roster moved on")] = None,
    _user: User = Depends(require_role("PLANNER", "MANAGER")),
    session: AsyncSession = Depends(get_session),
) -> list[EditableAssignmentOut]:
    """Stored assignments with their ids (the ids `DELETE`/`move` address).

    The UI joins these ids to `GET /rosters/{month}` by (worker, date, shift),
    so with `version` the ids are guaranteed to belong to that same roster
    version: otherwise a stale id could send an edit to a row that has moved
    since, and the edit's own version check would not notice."""
    month_date = parse_month(month)
    current_version = select(Roster.row_version).where(Roster.month == month_date)
    roster = (await session.execute(select(Roster).where(Roster.month == month_date))).scalar_one_or_none()
    if roster is None:
        raise NotFoundError(f"no roster for {month}")
    before = roster.row_version
    rows = [_out(ra) for ra in await _load_stored(session, roster)]
    # Read committed: an edit may commit between the two reads. Edits always bump the version,
    # so an unchanged version means the rows belong to it.
    after = (await session.execute(current_version)).scalar_one()
    if version is not None and (before != version or after != version):
        raise VersionConflictError(
            f"the roster is at version {after}, not {version}; reload it",
            details={"current_version": after},
        )
    return rows


@router.post(
    "/{month}/assignments",
    response_model=EditResultOut,
    responses=error_responses(400, 401, 403, 404, 409, 422),
)
async def add_assignment(
    month: MonthPath,
    body: AddAssignmentRequest,
    user: User = Depends(require_role("PLANNER", "MANAGER")),
    session: AsyncSession = Depends(get_session),
) -> EditResultOut:
    roster, built, stored = await _begin_edit(session, month, body.expected_version)
    _reject_locked(built, [(body.date, Shift(body.shift))])
    await _require_worker(session, body.worker_id)
    new = Assignment(body.worker_id, body.date, Shift(body.shift), Role(body.role))
    before = [_to_assignment(ra) for ra in stored]
    _gate(built, before, [*before, new])

    revoked = await _commit_edit(session, roster, user, body.acknowledge_approved_edit)
    ra = RosterAssignment(
        roster_id=roster.id, worker_id=int(body.worker_id), date=body.date, shift=body.shift, role=body.role
    )
    session.add(ra)
    await session.flush()
    return await _finish(session, roster, revoked, ra)


@router.delete(
    "/{month}/assignments/{assignment_id}",
    response_model=EditResultOut,
    responses=error_responses(400, 401, 403, 404, 409, 422),
)
async def remove_assignment(
    month: MonthPath,
    assignment_id: int,
    body: RemoveAssignmentRequest,
    user: User = Depends(require_role("PLANNER", "MANAGER")),
    session: AsyncSession = Depends(get_session),
) -> EditResultOut:
    roster, built, stored = await _begin_edit(session, month, body.expected_version)
    target = next((ra for ra in stored if ra.id == assignment_id), None)
    if target is None:
        raise NotFoundError(f"no assignment {assignment_id} in the roster of {month}")
    _reject_locked(built, [(target.date, Shift(target.shift))])
    # P10: removing from a free shift always passes (no gate).
    revoked = await _commit_edit(session, roster, user, body.acknowledge_approved_edit)
    await session.delete(target)
    await session.flush()
    return await _finish(session, roster, revoked, None)


@router.post(
    "/{month}/assignments/{assignment_id}/move",
    response_model=EditResultOut,
    responses=error_responses(400, 401, 403, 404, 409, 422),
)
async def move_assignment(
    month: MonthPath,
    assignment_id: int,
    body: MoveAssignmentRequest,
    user: User = Depends(require_role("PLANNER", "MANAGER")),
    session: AsyncSession = Depends(get_session),
) -> EditResultOut:
    """Remove + add, checked together; on failure nothing changes."""
    roster, built, stored = await _begin_edit(session, month, body.expected_version)
    target = next((ra for ra in stored if ra.id == assignment_id), None)
    if target is None:
        raise NotFoundError(f"no assignment {assignment_id} in the roster of {month}")
    old = _to_assignment(target)
    new = Assignment(
        body.worker_id or old.worker_id,
        body.date or old.date,
        Shift(body.shift) if body.shift else old.shift,
        Role(body.role) if body.role else old.role,
    )
    if new == old:
        raise BadRequestError("the move target equals the current assignment")
    _reject_locked(built, [(old.date, old.shift), (new.date, new.shift)])
    await _require_worker(session, new.worker_id)
    before = [_to_assignment(ra) for ra in stored]
    after = [a for a in before if a != old] + [new]
    _gate(built, before, after)

    revoked = await _commit_edit(session, roster, user, body.acknowledge_approved_edit)
    target.worker_id = int(new.worker_id)
    target.date = new.date
    target.shift = new.shift.value
    target.role = new.role.value
    await session.flush()
    return await _finish(session, roster, revoked, target)


@router.post(
    "/{month}/assignments/{assignment_id}/swap",
    response_model=EditResultOut,
    responses=error_responses(400, 401, 403, 404, 409, 422),
)
async def swap_assignments(
    month: MonthPath,
    assignment_id: int,
    body: SwapAssignmentRequest,
    user: User = Depends(require_role("PLANNER", "MANAGER")),
    session: AsyncSession = Depends(get_session),
) -> EditResultOut:
    """Exchange the workers of two assignments (same role, different slots;
    the shift letter and day may differ) in one transaction, checked
    together like a move."""
    roster, built, stored = await _begin_edit(session, month, body.expected_version)
    by_id = {ra.id: ra for ra in stored}
    first = by_id.get(assignment_id)
    second = by_id.get(body.other_assignment_id)
    if first is None or second is None:
        raise NotFoundError(f"no such assignment in the roster of {month}")
    if first.id == second.id or first.worker_id == second.worker_id:
        raise BadRequestError("a swap needs two assignments of different workers")
    if first.role != second.role:
        raise BadRequestError("only assignments of the same role can be swapped")
    if first.date == second.date and first.shift == second.shift:
        raise BadRequestError("the assignments are in the same slot, so swapping them changes nothing")
    a, b = _to_assignment(first), _to_assignment(second)
    _reject_locked(built, [(a.date, a.shift), (b.date, b.shift)])
    new_a = Assignment(b.worker_id, a.date, a.shift, a.role)
    new_b = Assignment(a.worker_id, b.date, b.shift, b.role)
    before = [_to_assignment(ra) for ra in stored]
    rest = [x for x in before if x not in (a, b)]
    # Checked before the gate: the double-booked rows would hit the unique slot constraint on flush.
    for moved in (new_a, new_b):
        taken = next((x for x in rest if (x.worker_id, x.date, x.shift) == (moved.worker_id, moved.date, moved.shift)), None)
        if taken is not None:
            dup = Violation(ViolationCode.DUPLICATE_ASSIGNMENT, (moved.worker_id, moved.date, moved.shift), 1, (taken, moved))
            raise HardViolationsError(
                f"worker {moved.worker_id} already works {moved.date} shift {moved.shift.value}",
                details=[violation_to_out(dup, set()).model_dump(mode="json")],
            )
    _gate(built, before, [*rest, new_a, new_b])

    revoked = await _commit_edit(session, roster, user, body.acknowledge_approved_edit)
    first.worker_id, second.worker_id = second.worker_id, first.worker_id
    await session.flush()
    return await _finish(session, roster, revoked, first)


@router.get(
    "/{month}/suggestions",
    response_model=SuggestionsOut,
    responses=error_responses(400, 401, 403, 404, 422),
)
async def get_suggestions(
    month: MonthPath,
    date_: Annotated[date, Query(alias="date")],
    shift: Annotated[Shift, Query()],
    role: Annotated[Role, Query()],
    _user: User = Depends(require_role("PLANNER", "MANAGER")),
    session: AsyncSession = Depends(get_session),
) -> SuggestionsOut:
    month_date = parse_month(month)
    roster = (await session.execute(select(Roster).where(Roster.month == month_date))).scalar_one_or_none()
    if roster is None:
        raise NotFoundError(f"no roster for {month}")
    if (date_.year, date_.month) != (month_date.year, month_date.month):
        raise ValidationAppError(f"{date_.isoformat()} is not in {month}")
    built = await build_problem(session, month_date, roster.forbid_adjacent_shifts)
    assignments = [_to_assignment(ra) for ra in await _load_stored(session, roster)]
    names = {w.worker_id: w.full_name for w in await load_worker_refs(session)}
    state, candidates = suggest(built.problem, assignments, date_, Shift(shift), Role(role), names)
    if is_history_month(month_date):
        state, candidates = "LOCKED", []
    return SuggestionsOut(
        date=date_,
        shift=shift,
        role=role,
        slot_state=state,  # type: ignore[arg-type]
        candidates=[
            SuggestionOut(
                worker_id=c.worker_id,
                full_name=c.full_name,
                assigned_hours=c.assigned_hours,
                min_hours=c.min_hours,
                hours_below_minimum=c.hours_below_minimum,
                shifts_that_day=c.shifts_that_day,
                reasons=list(c.reasons),
            )
            for c in candidates
        ],
    )


@router.get(
    "/{month}/assignments/{assignment_id}/replacements",
    response_model=SuggestionsOut,
    responses=error_responses(400, 401, 403, 404, 422),
)
async def get_replacements(
    month: MonthPath,
    assignment_id: int,
    _user: User = Depends(require_role("PLANNER", "MANAGER")),
    session: AsyncSession = Depends(get_session),
) -> SuggestionsOut:
    """Up to five workers who could take over an existing assignment (the
    "fix" options for a violation). Applying one is the move endpoint with
    a new `worker_id`, so it is revalidated there."""
    month_date = parse_month(month)
    roster = (await session.execute(select(Roster).where(Roster.month == month_date))).scalar_one_or_none()
    if roster is None:
        raise NotFoundError(f"no roster for {month}")
    stored = await _load_stored(session, roster)
    target = next((ra for ra in stored if ra.id == assignment_id), None)
    if target is None:
        raise NotFoundError(f"no assignment {assignment_id} in the roster of {month}")
    built = await build_problem(session, month_date, roster.forbid_adjacent_shifts)
    names = {w.worker_id: w.full_name for w in await load_worker_refs(session)}
    state, candidates = replacements(
        built.problem, [_to_assignment(ra) for ra in stored], _to_assignment(target), names
    )
    if is_history_month(month_date):
        state, candidates = "LOCKED", []
    return SuggestionsOut(
        date=target.date,
        shift=target.shift,
        role=target.role,
        slot_state=state,  # type: ignore[arg-type]
        candidates=[
            SuggestionOut(
                worker_id=c.worker_id,
                full_name=c.full_name,
                assigned_hours=c.assigned_hours,
                min_hours=c.min_hours,
                hours_below_minimum=c.hours_below_minimum,
                shifts_that_day=c.shifts_that_day,
                reasons=list(c.reasons),
            )
            for c in candidates
        ],
    )
