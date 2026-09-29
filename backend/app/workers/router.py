"""Workers API (§6 "Workers"): `GET|POST /workers`,
`GET|PATCH|DELETE /workers/{id}`. Aggregates the contracts router under
one include in `main.py`. Both PLANNER and MANAGER may use it (P12).

Writes take the scheduling lock, then check `expected_version` (409
`VERSION_CONFLICT`). Status/role changes go through the change-set
service: `worker_field_history` row, revalidation of affected rosters,
approval revoke `WORKER_CHANGE` (P7).
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_schemas.common import Role, error_responses
from app.api_schemas.workers import (
    WorkerCreate,
    WorkerDetailOut,
    WorkerOut,
    WorkerPatch,
    WorkerStatus,
    WorkerUpdateOut,
)
from app.auth.models import User
from app.auth.session import require_role
from app.changes.service import ChangeSet, WorkerUpdate, apply_change_set, month_start
from app.contracts.models import ContractVersion
from app.contracts.resolve import resolve_contracts_for_workers
from app.contracts.router import router as contracts_router
from app.db import get_session, take_scheduling_lock
from app.errors import NotFoundError, ValidationAppError, VersionConflictError, WorkerInUseError
from app.rosters.models import RosterAssignment
from app.timeutil import now_israel
from app.workers.models import Worker, WorkerFieldHistory
from app.workers.national_id import national_id_error
from app.workers.serialize import history_to_out, impact_fields, user_names, worker_names, worker_to_out

router = APIRouter(prefix="/api/workers", tags=["workers"])
router.include_router(contracts_router)

_ANY_PLANNER = Depends(require_role("PLANNER", "MANAGER"))


def field_error(field: str, message: str, type_: str) -> ValidationAppError:
    """A 422 in the same `details` shape as request validation, so the UI
    shows it inline next to the field."""
    return ValidationAppError(
        "the request is invalid", details=[{"loc": ["body", field], "message": message, "type": type_}]
    )


async def _check_national_id(session: AsyncSession, national_id: str, except_id: int | None = None) -> None:
    problem = national_id_error(national_id)
    if problem:
        raise field_error("national_id", problem, "national_id")
    stmt = select(Worker.id).where(Worker.national_id == national_id)
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing is not None and existing != except_id:
        raise field_error("national_id", "a worker with this national ID already exists", "duplicate")


async def _get_worker(session: AsyncSession, worker_id: int) -> Worker:
    worker = await session.get(Worker, worker_id)
    if worker is None:
        raise NotFoundError(f"worker {worker_id} not found")
    return worker


async def _current_contract(session: AsyncSession, worker_id: int) -> ContractVersion | None:
    resolved = await resolve_contracts_for_workers(session, [worker_id], month_start(now_israel()))
    return resolved.get(worker_id)


@router.get("", response_model=list[WorkerOut], responses=error_responses(401, 403, 422))
async def list_workers(
    status: WorkerStatus | None = None,
    role: Role | None = None,
    q: Annotated[str | None, Query(description="substring of name or national ID")] = None,
    _user: User = _ANY_PLANNER,
    session: AsyncSession = Depends(get_session),
) -> list[WorkerOut]:
    stmt = select(Worker).order_by(Worker.full_name, Worker.id)
    if status:
        stmt = stmt.where(Worker.status == status)
    if role:
        stmt = stmt.where(Worker.role == role)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(Worker.full_name.ilike(like) | Worker.national_id.like(like))
    workers = (await session.execute(stmt)).scalars().all()
    contracts = await resolve_contracts_for_workers(session, [w.id for w in workers], month_start(now_israel()))
    users = await user_names(session)
    return [worker_to_out(w, contracts.get(w.id), users) for w in workers]


@router.post("", response_model=WorkerOut, status_code=201, responses=error_responses(401, 403, 422))
async def create_worker(
    body: WorkerCreate,
    _user: User = _ANY_PLANNER,
    session: AsyncSession = Depends(get_session),
) -> WorkerOut:
    await take_scheduling_lock(session)
    await _check_national_id(session, body.national_id)
    worker = Worker(national_id=body.national_id, full_name=body.full_name, role=body.role, status=body.status)
    session.add(worker)
    await session.commit()
    await session.refresh(worker)
    return worker_to_out(worker, None, await user_names(session))


@router.get("/{worker_id}", response_model=WorkerDetailOut, responses=error_responses(401, 403, 404, 422))
async def get_worker(
    worker_id: int,
    _user: User = _ANY_PLANNER,
    session: AsyncSession = Depends(get_session),
) -> WorkerDetailOut:
    worker = await _get_worker(session, worker_id)
    users = await user_names(session)
    history = (
        (
            await session.execute(
                select(WorkerFieldHistory)
                .where(WorkerFieldHistory.worker_id == worker_id)
                .order_by(WorkerFieldHistory.effective_at.desc(), WorkerFieldHistory.id.desc())
            )
        )
        .scalars()
        .all()
    )
    base = worker_to_out(worker, await _current_contract(session, worker_id), users)
    return WorkerDetailOut(**base.model_dump(), field_history=[history_to_out(h, users) for h in history])


@router.patch("/{worker_id}", response_model=WorkerUpdateOut, responses=error_responses(401, 403, 404, 409, 422))
async def update_worker(
    worker_id: int,
    body: WorkerPatch,
    user: User = _ANY_PLANNER,
    session: AsyncSession = Depends(get_session),
) -> WorkerUpdateOut:
    await take_scheduling_lock(session)
    worker = await _get_worker(session, worker_id)
    if body.expected_version != worker.row_version:
        raise VersionConflictError(
            "the worker was changed by someone else; reload and try again",
            details={"current_version": worker.row_version},
        )
    if body.national_id is not None and body.national_id != worker.national_id:
        await _check_national_id(session, body.national_id, except_id=worker_id)

    cs = ChangeSet(
        actor_id=user.id,
        worker_updates=(
            WorkerUpdate(
                worker_id=worker_id,
                national_id=body.national_id,
                full_name=body.full_name,
                role=body.role,
                status=body.status,
            ),
        ),
        worker_change_ref=f"worker:{worker_id}",
    )
    result = await apply_change_set(session, cs)
    await session.commit()

    fresh = await _get_worker(session, worker_id)
    users = await user_names(session)
    return WorkerUpdateOut(
        worker=worker_to_out(fresh, await _current_contract(session, worker_id), users),
        changed=bool(result.changed_workers),
        **impact_fields(result.impact, await worker_names(session)),
    )


@router.delete("/{worker_id}", status_code=204, responses=error_responses(401, 403, 404, 409, 422))
async def delete_worker(
    worker_id: int,
    _user: User = _ANY_PLANNER,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """P6: hard delete only if the worker has no contract versions, no
    assignments and no status/role history; otherwise 409 `WORKER_IN_USE`
    and the UI offers "deactivate"."""
    await take_scheduling_lock(session)
    worker = await _get_worker(session, worker_id)
    in_use = {
        "contract_versions": select(func.count()).select_from(ContractVersion).where(ContractVersion.worker_id == worker_id),
        "assignments": select(func.count()).select_from(RosterAssignment).where(RosterAssignment.worker_id == worker_id),
        "history_entries": select(func.count()).select_from(WorkerFieldHistory).where(WorkerFieldHistory.worker_id == worker_id),
    }
    counts = {name: (await session.execute(stmt)).scalar_one() for name, stmt in in_use.items()}
    if any(counts.values()):
        raise WorkerInUseError(
            "the worker has contracts, assignments or history and cannot be deleted; deactivate them instead",
            details=counts,
        )
    await session.delete(worker)
    await session.commit()
    return Response(status_code=204)
