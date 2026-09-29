"""Contracts API (§6 "Contracts"), mounted under `/api/workers/{id}/contracts`
by `workers/router.py`.

`GET` lists every version plus the one resolved for `resolved_for`.
`POST /preview` and `POST /` share the change-set service with CSV: the
preview reports affected rosters and `locked_violations` (P2) and returns a
fingerprint; the apply must send it back (409 `STALE_PREVIEW` otherwise).
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_schemas.common import error_responses
from app.api_schemas.workers import ContractApply, ContractApplyOut, ContractInput, ContractPreviewOut, ContractsOut
from app.auth.models import User
from app.auth.session import require_role
from app.changes.service import (
    ChangeSet,
    ContractDraft,
    StaleChangeSetError,
    apply_change_set,
    is_retroactive,
    month_start,
    preview_change_set,
)
from app.contracts.models import ContractVersion
from app.contracts.resolve import resolve_contract
from app.db import get_session
from app.errors import NotFoundError, StalePreviewError
from app.rosters.problem_builder import MONTH_PATTERN, parse_month
from app.timeutil import now_israel
from app.workers.models import Worker
from app.workers.serialize import contract_to_out, impact_fields, month_str, user_names, worker_names

router = APIRouter(prefix="/{worker_id}/contracts", tags=["contracts"])

_ANY_PLANNER = Depends(require_role("PLANNER", "MANAGER"))


async def _require_worker(session: AsyncSession, worker_id: int) -> None:
    if await session.get(Worker, worker_id) is None:
        raise NotFoundError(f"worker {worker_id} not found")


def _draft(worker_id: int, body: ContractInput) -> ContractDraft:
    return ContractDraft(
        worker_id=worker_id,
        effective_month=parse_month(body.effective_month),
        hourly_rate_ils=body.hourly_rate_ils,
        min_hours=body.min_hours,
        max_hours=body.max_hours,
        availability=tuple(body.availability),
    )


@router.get("", response_model=ContractsOut, responses=error_responses(401, 403, 404, 422))
async def list_contracts(
    worker_id: int,
    resolved_for: Annotated[str | None, Query(pattern=MONTH_PATTERN, description="YYYY-MM; default: the current Israel month")] = None,
    _user: User = _ANY_PLANNER,
    session: AsyncSession = Depends(get_session),
) -> ContractsOut:
    await _require_worker(session, worker_id)
    month = parse_month(resolved_for) if resolved_for else month_start(now_israel())
    versions = (
        (
            await session.execute(
                select(ContractVersion)
                .where(ContractVersion.worker_id == worker_id)
                .order_by(ContractVersion.effective_month.desc(), ContractVersion.version_no.desc())
            )
        )
        .scalars()
        .all()
    )
    resolved = await resolve_contract(session, worker_id, month)
    users = await user_names(session)
    return ContractsOut(
        worker_id=worker_id,
        resolved_for=month_str(month),
        resolved=contract_to_out(resolved, users) if resolved else None,
        versions=[contract_to_out(v, users) for v in versions],
    )


@router.post("/preview", response_model=ContractPreviewOut, responses=error_responses(401, 403, 404, 422))
async def preview_contract(
    worker_id: int,
    body: ContractInput,
    user: User = _ANY_PLANNER,
    session: AsyncSession = Depends(get_session),
) -> ContractPreviewOut:
    await _require_worker(session, worker_id)
    draft = _draft(worker_id, body)
    impact = await preview_change_set(session, ChangeSet(actor_id=user.id, contracts=(draft,)))
    plan = impact.contracts[0]
    users = await user_names(session)
    out = ContractPreviewOut(
        worker_id=worker_id,
        effective_month=body.effective_month,
        retroactive=is_retroactive(draft.effective_month),
        unchanged=plan.unchanged,
        previous=contract_to_out(plan.previous, users) if plan.previous else None,
        fingerprint=impact.fingerprint,
        **impact_fields(impact, await worker_names(session)),
    )
    await session.rollback()  # nothing was written; releases the scheduling lock
    return out


@router.post("", response_model=ContractApplyOut, responses=error_responses(401, 403, 404, 409, 422))
async def apply_contract(
    worker_id: int,
    body: ContractApply,
    user: User = _ANY_PLANNER,
    session: AsyncSession = Depends(get_session),
) -> ContractApplyOut:
    """Creates a new immutable version. An unchanged contract (P5) creates
    nothing (`created=false`). Assignments are kept; approved rosters that
    gain hard violations return to DRAFT with revoke cause `CONTRACT_CHANGE`."""
    await _require_worker(session, worker_id)
    cs = ChangeSet(actor_id=user.id, contracts=(_draft(worker_id, body),))
    try:
        result = await apply_change_set(session, cs, expected_fingerprint=body.fingerprint)
    except StaleChangeSetError as stale:
        names = await worker_names(session)
        plan = stale.fresh.contracts[0]
        users = await user_names(session)
        fresh = ContractPreviewOut(
            worker_id=worker_id,
            effective_month=body.effective_month,
            retroactive=is_retroactive(cs.contracts[0].effective_month),
            unchanged=plan.unchanged,
            previous=contract_to_out(plan.previous, users) if plan.previous else None,
            fingerprint=stale.fresh.fingerprint,
            **impact_fields(stale.fresh, names),
        )
        await session.rollback()
        raise StalePreviewError(stale.message, details=fresh.model_dump(mode="json")) from None
    await session.commit()

    created = result.new_versions[0] if result.new_versions else None
    users = await user_names(session)
    impact = result.impact
    return ContractApplyOut(
        created=created is not None,
        contract=contract_to_out(created, users) if created else None,
        revoked_rosters=[month_str(r.month) for r in impact.rosters if r.revokes_approval],
        **impact_fields(impact, await worker_names(session)),
    )
