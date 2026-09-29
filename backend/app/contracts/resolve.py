"""Contract resolution (§3 "Contract resolution"), read path only.

`rosters/problem_builder` (T3) owns turning this into engine input;
this module is the minimal, pure query T3 depends on.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.models import ContractVersion


async def resolve_contracts_for_workers(
    session: AsyncSession, worker_ids: list[int], month: date
) -> dict[int, ContractVersion]:
    """`resolve_contract` for a whole worker set at once (T3's
    `problem_builder` needs one query per roster build, not one per
    worker). Same rule: `effective_month <= month`, highest
    `effective_month` then `version_no` wins; a worker with no
    applicable version is simply absent from the result."""
    if not worker_ids:
        return {}
    stmt = (
        select(ContractVersion)
        .where(ContractVersion.worker_id.in_(worker_ids), ContractVersion.effective_month <= month)
        .order_by(
            ContractVersion.worker_id,
            ContractVersion.effective_month.desc(),
            ContractVersion.version_no.desc(),
        )
    )
    resolved: dict[int, ContractVersion] = {}
    for cv in (await session.execute(stmt)).scalars():
        resolved.setdefault(cv.worker_id, cv)  # first row per worker_id wins (best match)
    return resolved


async def resolve_contract(
    session: AsyncSession, worker_id: int, month: date
) -> ContractVersion | None:
    """The contract version effective for `worker_id` in `month`:
    `effective_month <= month`, ordered by
    `effective_month DESC, version_no DESC`, first row. A future
    version never resolves for an earlier month."""
    stmt = (
        select(ContractVersion)
        .where(ContractVersion.worker_id == worker_id, ContractVersion.effective_month <= month)
        .order_by(ContractVersion.effective_month.desc(), ContractVersion.version_no.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()
