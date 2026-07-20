"""add workspace agent policy and plan task metadata

Revision ID: b2c7d8e9f0a1
Revises: a1f6e8c2d4b7
Create Date: 2026-07-20
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b2c7d8e9f0a1"
down_revision: str | None = "a1f6e8c2d4b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_agent_policies",
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("roles_json", sa.JSON(), nullable=False),
        sa.Column("fallbacks_json", sa.JSON(), nullable=False),
        sa.Column(
            "reasoning_effort", sa.String(length=16), server_default="medium", nullable=False
        ),
        sa.Column("permission_mode", sa.String(length=24), server_default="ask", nullable=False),
        sa.Column("updated_by", sa.String(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("workspace_id"),
    )
    op.create_index(
        "ix_workspace_agent_policies_scope",
        "workspace_agent_policies",
        ["tenant_id", "project_id"],
    )

    op.add_column("agent_tasks", sa.Column("title", sa.String(length=500), nullable=True))
    op.add_column("agent_tasks", sa.Column("description", sa.Text(), nullable=True))
    op.add_column(
        "agent_tasks", sa.Column("estimated_duration_seconds", sa.Integer(), nullable=True)
    )
    op.add_column("agent_tasks", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "agent_tasks", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("agent_tasks", sa.Column("result_summary", sa.Text(), nullable=True))
    op.add_column(
        "agent_tasks", sa.Column("evidence_refs", sa.JSON(), server_default="[]", nullable=False)
    )
    op.execute("UPDATE agent_tasks SET title = content WHERE title IS NULL")
    op.alter_column("agent_tasks", "title", nullable=False)
    op.alter_column("agent_tasks", "evidence_refs", server_default=None)

    op.create_table(
        "agent_plan_versions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="draft", nullable=False),
        sa.Column("tasks_json", sa.JSON(), nullable=False),
        sa.Column("policy_revision", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "conversation_id", "version", name="uq_agent_plan_versions_conv_version"
        ),
    )
    op.create_index(
        "ix_agent_plan_versions_conversation",
        "agent_plan_versions",
        ["conversation_id", "version"],
    )
    op.create_table(
        "agent_plan_runs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("plan_version_id", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("message_id", sa.String(length=255), nullable=False),
        sa.Column("request_message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=30), server_default="queued", nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("permission_profile", sa.String(length=30), nullable=False),
        sa.Column("authorization_snapshot", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["plan_version_id"], ["agent_plan_versions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index(
        "ix_agent_plan_runs_conversation",
        "agent_plan_runs",
        ["conversation_id", "created_at"],
    )

    op.add_column(
        "trust_policies",
        sa.Column("scope", sa.String(length=30), server_default="agent", nullable=False),
    )
    op.add_column(
        "trust_policies", sa.Column("canonical_tool_name", sa.String(length=160), nullable=True)
    )
    op.add_column(
        "trust_policies", sa.Column("source_hitl_request_id", sa.String(length=100), nullable=True)
    )
    op.add_column(
        "trust_policies", sa.Column("revision", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column("trust_policies", sa.Column("revoked_by", sa.String(length=36), nullable=True))
    op.add_column(
        "trust_policies", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_index("ix_agent_plan_runs_conversation", table_name="agent_plan_runs")
    op.drop_table("agent_plan_runs")
    op.drop_index("ix_agent_plan_versions_conversation", table_name="agent_plan_versions")
    op.drop_table("agent_plan_versions")
    for column in [
        "revoked_at",
        "revoked_by",
        "revision",
        "source_hitl_request_id",
        "canonical_tool_name",
        "scope",
    ]:
        op.drop_column("trust_policies", column)
    for column in [
        "evidence_refs",
        "result_summary",
        "completed_at",
        "started_at",
        "estimated_duration_seconds",
        "description",
        "title",
    ]:
        op.drop_column("agent_tasks", column)
    op.drop_index("ix_workspace_agent_policies_scope", table_name="workspace_agent_policies")
    op.drop_table("workspace_agent_policies")
