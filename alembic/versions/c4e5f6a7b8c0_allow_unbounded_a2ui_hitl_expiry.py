"""Allow A2UI interactions to wait without a user-response deadline.

Revision ID: c4e5f6a7b8c0
Revises: a1b2c3d4e5f6
Create Date: 2026-11-19 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c4e5f6a7b8c0"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_hitl_requests() -> bool:
    """Workspace-only upgrade paths stamp past the table that owns this column."""
    return sa.inspect(op.get_bind()).has_table("hitl_requests")


def upgrade() -> None:
    if not _has_hitl_requests():
        return
    op.alter_column(
        "hitl_requests",
        "expires_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
    )


def downgrade() -> None:
    if not _has_hitl_requests():
        return
    op.execute("UPDATE hitl_requests SET expires_at = created_at WHERE expires_at IS NULL")
    op.alter_column(
        "hitl_requests",
        "expires_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )
