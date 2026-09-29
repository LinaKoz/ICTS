"""free-text reason for a manual revocation of an approval

Revision ID: b9d2e4f6a7c8
Revises: a8c1d2e3f4b5
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b9d2e4f6a7c8"
down_revision: Union[str, None] = "a8c1d2e3f4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("roster_approvals", sa.Column("revoke_reason", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("roster_approvals", "revoke_reason")
