"""add plugin cutover approvals

Revision ID: 8120f25cc8c5
Revises: 3ef7c1424290
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "8120f25cc8c5"
down_revision: str | Sequence[str] | None = "3ef7c1424290"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Persist auditable approvals of platform-plugin agent cutover."""
    op.create_table(
        "platform_plugin_cutover_approvals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("capability", sa.String(length=64), nullable=False),
        sa.Column("approved_by", sa.String(length=255), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "approved_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_platform_plugin_cutover_approvals_capability",
        "platform_plugin_cutover_approvals",
        ["capability"],
    )
    op.create_index(
        "ix_platform_plugin_cutover_approval_capability_active",
        "platform_plugin_cutover_approvals",
        ["capability", "revoked_at", "approved_at"],
    )


def downgrade() -> None:
    """Remove cutover approval history."""
    op.drop_index(
        "ix_platform_plugin_cutover_approval_capability_active",
        table_name="platform_plugin_cutover_approvals",
    )
    op.drop_index(
        "ix_platform_plugin_cutover_approvals_capability",
        table_name="platform_plugin_cutover_approvals",
    )
    op.drop_table("platform_plugin_cutover_approvals")
