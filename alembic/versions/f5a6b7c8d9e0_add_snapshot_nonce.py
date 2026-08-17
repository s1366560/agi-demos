"""add platform plugin snapshot nonce

Revision ID: f5a6b7c8d9e0
Revises: d8e9f0a1b2c3
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f5a6b7c8d9e0"
down_revision: str | Sequence[str] | None = "d8e9f0a1b2c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Persist the distribution nonce required by desktop reconciliation."""
    op.add_column(
        "platform_plugin_snapshots",
        sa.Column("nonce", sa.String(length=128), nullable=True),
    )
    op.execute("UPDATE platform_plugin_snapshots SET nonce = digest WHERE nonce IS NULL")
    op.alter_column(
        "platform_plugin_snapshots",
        "nonce",
        existing_type=sa.String(length=128),
        nullable=False,
    )


def downgrade() -> None:
    """Remove the distribution nonce."""
    op.alter_column(
        "platform_plugin_snapshots",
        "nonce",
        existing_type=sa.String(length=128),
        nullable=True,
    )
    op.drop_column("platform_plugin_snapshots", "nonce")
