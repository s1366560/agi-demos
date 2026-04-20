"""add workspace plan and plan node tables

Revision ID: n1a2b3c4d5e6
Revises: m5e6f7a8b9c0
Create Date: 2026-05-01 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "n1a2b3c4d5e6"
down_revision: str | Sequence[str] | None = "m5e6f7a8b9c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_plans",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("goal_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workspace_plans_workspace", "workspace_plans", ["workspace_id"])

    op.create_table(
        "workspace_plan_nodes",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("plan_id", sa.String(), nullable=False),
        sa.Column("parent_id", sa.String(), nullable=True),
        sa.Column("kind", sa.String(length=20), nullable=False, server_default="task"),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("depends_on", sa.JSON(), nullable=False),
        sa.Column("inputs_schema", sa.JSON(), nullable=False),
        sa.Column("outputs_schema", sa.JSON(), nullable=False),
        sa.Column("acceptance_criteria", sa.JSON(), nullable=False),
        sa.Column("recommended_capabilities", sa.JSON(), nullable=False),
        sa.Column("preferred_agent_id", sa.String(), nullable=True),
        sa.Column("estimated_effort", sa.JSON(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("intent", sa.String(length=20), nullable=False, server_default="todo"),
        sa.Column("execution", sa.String(length=20), nullable=False, server_default="idle"),
        sa.Column("progress", sa.JSON(), nullable=False),
        sa.Column("assignee_agent_id", sa.String(), nullable=True),
        sa.Column("current_attempt_id", sa.String(), nullable=True),
        sa.Column("workspace_task_id", sa.String(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["plan_id"], ["workspace_plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workspace_plan_nodes_plan", "workspace_plan_nodes", ["plan_id"])
    op.create_index("ix_workspace_plan_nodes_parent", "workspace_plan_nodes", ["parent_id"])
    op.create_index(
        "ix_workspace_plan_nodes_workspace_task",
        "workspace_plan_nodes",
        ["workspace_task_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_workspace_plan_nodes_workspace_task", table_name="workspace_plan_nodes")
    op.drop_index("ix_workspace_plan_nodes_parent", table_name="workspace_plan_nodes")
    op.drop_index("ix_workspace_plan_nodes_plan", table_name="workspace_plan_nodes")
    op.drop_table("workspace_plan_nodes")
    op.drop_index("ix_workspace_plans_workspace", table_name="workspace_plans")
    op.drop_table("workspace_plans")
