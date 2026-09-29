"""`resolve_worker_state` (§3 D9(b)): the worker's status/role as of a
past instant, undoing any `worker_field_history` change that happened
after it. Used only for locked (already-started) assignments; free
shifts always use the worker's current row (§3).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.workers.models import Worker, WorkerFieldHistory


def state_at(current: dict[str, str], history: list[WorkerFieldHistory], at: datetime) -> dict[str, str]:
    """Pure core of `resolve_worker_state`: `current` is `{status, role}`
    now; `history` is one worker's `worker_field_history` rows. Each field
    is replaced by the `old_value` of its oldest row with `effective_at > at`."""
    state = dict(current)
    for field, key in (("STATUS", "status"), ("ROLE", "role")):
        later = [h for h in history if h.field == field and h.effective_at > at]
        if later:
            state[key] = min(later, key=lambda h: h.effective_at).old_value
    return state


async def load_worker_states(
    session: AsyncSession, worker_ids: set[int]
) -> tuple[dict[int, dict[str, str]], dict[int, list[WorkerFieldHistory]]]:
    """Bulk loader for `state_at`: current `{status, role}` and history
    rows per worker, in two queries regardless of how many assignments
    are being evaluated."""
    if not worker_ids:
        return {}, {}
    workers = (await session.execute(select(Worker).where(Worker.id.in_(worker_ids)))).scalars().all()
    current = {w.id: {"status": w.status, "role": w.role} for w in workers}
    rows = (
        await session.execute(select(WorkerFieldHistory).where(WorkerFieldHistory.worker_id.in_(worker_ids)))
    ).scalars().all()
    history: dict[int, list[WorkerFieldHistory]] = {}
    for h in rows:
        history.setdefault(h.worker_id, []).append(h)
    return current, history


async def resolve_worker_state(session: AsyncSession, worker_id: int, at: datetime) -> dict[str, str] | None:
    """The worker's `{status, role}` as of `at`: the current row, with
    each field replaced by the `old_value` of the oldest history row
    for that field with `effective_at > at`, if one exists. Returns
    `None` if the worker does not exist."""
    worker = await session.get(Worker, worker_id)
    if worker is None:
        return None
    state = {"status": worker.status, "role": worker.role}
    for field, key in (("STATUS", "status"), ("ROLE", "role")):
        stmt = (
            select(WorkerFieldHistory.old_value)
            .where(
                WorkerFieldHistory.worker_id == worker_id,
                WorkerFieldHistory.field == field,
                WorkerFieldHistory.effective_at > at,
            )
            .order_by(WorkerFieldHistory.effective_at.asc())
            .limit(1)
        )
        old_value = (await session.execute(stmt)).scalar_one_or_none()
        if old_value is not None:
            state[key] = old_value
    return state
