"""add tenant plugin configs

Revision ID: e2f3a4b5c6d7
Revises: c1d2e3f4a5b6
Create Date: 2026-05-26

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e2f3a4b5c6d7"
down_revision: str | Sequence[str] | None = "c1d2e3f4a5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create tenant-scoped runtime plugin config table."""
    op.create_table(
        "plugin_configs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("plugin_name", sa.String(length=255), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "plugin_name", name="uq_plugin_configs_tenant_plugin"),
    )
    op.create_index("ix_plugin_configs_tenant_id", "plugin_configs", ["tenant_id"])
    op.create_index("ix_plugin_configs_plugin_name", "plugin_configs", ["plugin_name"])
    op.create_index(
        "ix_plugin_configs_tenant_plugin",
        "plugin_configs",
        ["tenant_id", "plugin_name"],
    )


def downgrade() -> None:
    """Drop tenant-scoped runtime plugin config table."""
    op.drop_index("ix_plugin_configs_tenant_plugin", table_name="plugin_configs")
    op.drop_index("ix_plugin_configs_plugin_name", table_name="plugin_configs")
    op.drop_index("ix_plugin_configs_tenant_id", table_name="plugin_configs")
    op.drop_table("plugin_configs")
