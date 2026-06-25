"""add acp external agent configs

Revision ID: p5e6f7a8b9c0
Revises: o4d5e6f7a8b9
Create Date: 2026-06-24 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "p5e6f7a8b9c0"
down_revision: str | Sequence[str] | None = "o4d5e6f7a8b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "acp_external_agent_configs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("agent_key", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("transport", sa.String(length=32), nullable=False),
        sa.Column("command", sa.String(length=500), nullable=True),
        sa.Column("args", sa.JSON(), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("env", sa.JSON(), nullable=False),
        sa.Column("headers", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "agent_key", name="uq_acp_external_agents_tenant_key"),
    )
    op.create_index("ix_acp_external_agent_configs_tenant_id", "acp_external_agent_configs", ["tenant_id"])
    op.create_index("ix_acp_external_agent_configs_agent_key", "acp_external_agent_configs", ["agent_key"])
    op.create_index(
        "ix_acp_external_agents_tenant_key",
        "acp_external_agent_configs",
        ["tenant_id", "agent_key"],
    )
    op.create_index(
        "ix_acp_external_agents_tenant_enabled",
        "acp_external_agent_configs",
        ["tenant_id", "enabled"],
    )


def downgrade() -> None:
    op.drop_index("ix_acp_external_agents_tenant_enabled", table_name="acp_external_agent_configs")
    op.drop_index("ix_acp_external_agents_tenant_key", table_name="acp_external_agent_configs")
    op.drop_index("ix_acp_external_agent_configs_agent_key", table_name="acp_external_agent_configs")
    op.drop_index("ix_acp_external_agent_configs_tenant_id", table_name="acp_external_agent_configs")
    op.drop_table("acp_external_agent_configs")
