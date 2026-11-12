"""Widen workspace plan outbox status for runtime admission values.

Revision ID: a1b2c3d4e5f6
Revises: f2a3b4c5d6e8
Create Date: 2026-11-10 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "f2a3b4c5d6e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Allow runtime admission statuses that do not fit varchar(20)."""
    if not sa.inspect(op.get_bind()).has_table("workspace_plan_outbox"):
        return
    op.alter_column(
        "workspace_plan_outbox",
        "status",
        existing_type=sa.String(length=20),
        type_=sa.String(length=32),
        existing_nullable=False,
    )


def downgrade() -> None:
    """Restore the original status width."""
    if not sa.inspect(op.get_bind()).has_table("workspace_plan_outbox"):
        return
    op.alter_column(
        "workspace_plan_outbox",
        "status",
        existing_type=sa.String(length=32),
        type_=sa.String(length=20),
        existing_nullable=False,
    )
