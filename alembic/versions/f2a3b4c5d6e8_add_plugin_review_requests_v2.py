"""add plugin review requests v2

Revision ID: f2a3b4c5d6e8
Revises: p8b1c2d3e4f5
Create Date: 2026-11-09 03:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f2a3b4c5d6e8"
down_revision: str | Sequence[str] | None = "p8b1c2d3e4f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "platform_plugin_review_requests_v2",
        sa.Column("review_id", sa.String(length=36), nullable=False),
        sa.Column("plugin_id", sa.String(length=128), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("digest", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("review_id"),
    )


def downgrade() -> None:
    op.drop_table("platform_plugin_review_requests_v2")
