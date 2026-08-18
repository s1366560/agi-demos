"""add plugin cutover approval expiry

Revision ID: 23dc191c451d
Revises: 8120f25cc8c5
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "23dc191c451d"
down_revision: str | Sequence[str] | None = "8120f25cc8c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Bound durable cutover approval authority in time."""
    op.add_column(
        "platform_plugin_cutover_approvals",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE platform_plugin_cutover_approvals "
        "SET expires_at = approved_at + INTERVAL '7 days' "
        "WHERE expires_at IS NULL"
    )
    op.alter_column(
        "platform_plugin_cutover_approvals",
        "expires_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )


def downgrade() -> None:
    """Restore unbounded cutover approvals."""
    op.drop_column("platform_plugin_cutover_approvals", "expires_at")
