"""allow the MANUAL revoke cause (T8: a manager revoking an approval by hand)

Revision ID: a8c1d2e3f4b5
Revises: f64a67d5168f
"""
from typing import Sequence, Union

from alembic import op

revision: str = "a8c1d2e3f4b5"
down_revision: Union[str, None] = "f64a67d5168f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NAME = "ck_roster_approvals_revoke_cause"
_OLD = "revoke_cause IN ('EDIT', 'REGENERATE', 'CONTRACT_CHANGE', 'WORKER_CHANGE') OR revoke_cause IS NULL"
_NEW = "revoke_cause IN ('EDIT', 'REGENERATE', 'CONTRACT_CHANGE', 'WORKER_CHANGE', 'MANUAL') OR revoke_cause IS NULL"


def upgrade() -> None:
    op.drop_constraint(_NAME, "roster_approvals", type_="check")
    op.create_check_constraint(_NAME, "roster_approvals", _NEW)


def downgrade() -> None:
    op.execute("UPDATE roster_approvals SET revoke_cause = 'EDIT' WHERE revoke_cause = 'MANUAL'")
    op.drop_constraint(_NAME, "roster_approvals", type_="check")
    op.create_check_constraint(_NAME, "roster_approvals", _OLD)
