"""`revoke(...)` (§3 `roster_approvals`, P7/P11): the piece of approval
T3's `save.py` needs when replacing an approved roster. The full
approval endpoint (grant, acknowledgement, audit trail) is T8.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.rosters.models import Roster, RosterApproval

REVOKE_CAUSES = ("EDIT", "REGENERATE", "CONTRACT_CHANGE", "WORKER_CHANGE")


async def revoke(
    session: AsyncSession,
    roster: Roster,
    cause: str,
    ref: str | None,
    revoked_by: int,
    now: datetime | None = None,
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
    roster.status = "DRAFT"
