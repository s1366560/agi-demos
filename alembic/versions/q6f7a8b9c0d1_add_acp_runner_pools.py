"""add acp runner pools

Revision ID: q6f7a8b9c0d1
Revises: p5e6f7a8b9c0
Create Date: 2026-06-25 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "q6f7a8b9c0d1"
down_revision: str | Sequence[str] | None = "p5e6f7a8b9c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "acp_external_agent_configs",
        sa.Column("runner_pool_key", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "acp_external_agent_configs",
        sa.Column("required_labels", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column(
        "acp_external_agent_configs",
        sa.Column("cwd_policy", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.alter_column("acp_external_agent_configs", "required_labels", server_default=None)
    op.alter_column("acp_external_agent_configs", "cwd_policy", server_default=None)

    op.create_table(
        "acp_runner_pools",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("cluster_id", sa.String(), nullable=False),
        sa.Column("pool_key", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("labels", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("capacity_policy", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("scheduling_policy", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["cluster_id"], ["clusters.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "pool_key", name="uq_acp_runner_pools_tenant_key"),
    )
    op.create_index("ix_acp_runner_pools_tenant_id", "acp_runner_pools", ["tenant_id"])
    op.create_index("ix_acp_runner_pools_cluster", "acp_runner_pools", ["cluster_id"])
    op.create_index(
        "ix_acp_runner_pools_tenant_enabled",
        "acp_runner_pools",
        ["tenant_id", "enabled"],
    )

    op.create_table(
        "acp_runner_instances",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("pool_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("runner_id", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="offline"),
        sa.Column("version", sa.String(length=80), nullable=True),
        sa.Column("capabilities", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("current_sessions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_sessions", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("connection_id", sa.String(length=120), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["pool_id"], ["acp_runner_pools.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("pool_id", "runner_id", name="uq_acp_runner_instances_pool_runner"),
    )
    op.create_index("ix_acp_runner_instances_pool_id", "acp_runner_instances", ["pool_id"])
    op.create_index("ix_acp_runner_instances_tenant_id", "acp_runner_instances", ["tenant_id"])
    op.create_index(
        "ix_acp_runner_instances_pool_status",
        "acp_runner_instances",
        ["pool_id", "status"],
    )

    op.create_table(
        "acp_runner_tokens",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("pool_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["pool_id"], ["acp_runner_pools.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_acp_runner_tokens_pool_id", "acp_runner_tokens", ["pool_id"])
    op.create_index("ix_acp_runner_tokens_tenant_id", "acp_runner_tokens", ["tenant_id"])

    op.create_table(
        "acp_runner_sessions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("session_id", sa.String(), nullable=False, unique=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("pool_id", sa.String(), nullable=False),
        sa.Column("runner_id", sa.String(length=160), nullable=False),
        sa.Column("agent_key", sa.String(length=120), nullable=False),
        sa.Column("owner_user_id", sa.String(), nullable=False),
        sa.Column("remote_session_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pool_id"], ["acp_runner_pools.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_acp_runner_sessions_session_id", "acp_runner_sessions", ["session_id"])
    op.create_index("ix_acp_runner_sessions_tenant_id", "acp_runner_sessions", ["tenant_id"])
    op.create_index("ix_acp_runner_sessions_pool_id", "acp_runner_sessions", ["pool_id"])
    op.create_index(
        "ix_acp_runner_sessions_runner",
        "acp_runner_sessions",
        ["tenant_id", "runner_id", "status"],
    )
    op.create_index(
        "ix_acp_runner_sessions_pool",
        "acp_runner_sessions",
        ["pool_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_acp_runner_sessions_pool", table_name="acp_runner_sessions")
    op.drop_index("ix_acp_runner_sessions_runner", table_name="acp_runner_sessions")
    op.drop_index("ix_acp_runner_sessions_pool_id", table_name="acp_runner_sessions")
    op.drop_index("ix_acp_runner_sessions_tenant_id", table_name="acp_runner_sessions")
    op.drop_index("ix_acp_runner_sessions_session_id", table_name="acp_runner_sessions")
    op.drop_table("acp_runner_sessions")

    op.drop_index("ix_acp_runner_tokens_tenant_id", table_name="acp_runner_tokens")
    op.drop_index("ix_acp_runner_tokens_pool_id", table_name="acp_runner_tokens")
    op.drop_table("acp_runner_tokens")

    op.drop_index("ix_acp_runner_instances_pool_status", table_name="acp_runner_instances")
    op.drop_index("ix_acp_runner_instances_tenant_id", table_name="acp_runner_instances")
    op.drop_index("ix_acp_runner_instances_pool_id", table_name="acp_runner_instances")
    op.drop_table("acp_runner_instances")

    op.drop_index("ix_acp_runner_pools_tenant_enabled", table_name="acp_runner_pools")
    op.drop_index("ix_acp_runner_pools_cluster", table_name="acp_runner_pools")
    op.drop_index("ix_acp_runner_pools_tenant_id", table_name="acp_runner_pools")
    op.drop_table("acp_runner_pools")

    op.drop_column("acp_external_agent_configs", "cwd_policy")
    op.drop_column("acp_external_agent_configs", "required_labels")
    op.drop_column("acp_external_agent_configs", "runner_pool_key")
