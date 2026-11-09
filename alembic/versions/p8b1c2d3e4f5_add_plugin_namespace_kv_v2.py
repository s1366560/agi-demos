"""add plugin namespace kv v2

Revision ID: p8b1c2d3e4f5
Revises: d10a27f4c901
Create Date: 2026-11-09 02:50:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "p8b1c2d3e4f5"
down_revision: str | Sequence[str] | None = "d10a27f4c901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "platform_plugin_namespace_kv_v2",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("plugin_id", sa.String(length=128), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("item_key", sa.String(length=128), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("document", sa.JSON(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "plugin_id",
            "tenant_id",
            "project_id",
            "item_key",
            name="uq_plugin_namespace_kv_v2_scope",
        ),
    )


def downgrade() -> None:
    op.drop_table("platform_plugin_namespace_kv_v2")
