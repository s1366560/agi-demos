"""add workspace plan events

Revision ID: j8c9d0e1f2a3
Revises: i7b8c9d0e1f2
Create Date: 2026-04-24 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "j8c9d0e1f2a3"
down_revision: str | Sequence[str] | None = "i7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_plan_events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("plan_id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("node_id", sa.String(), nullable=True),
        sa.Column("attempt_id", sa.String(), nullable=True),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=True),
        sa.Column(
            "payload_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["plan_id"], ["workspace_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_workspace_plan_events_plan_created",
        "workspace_plan_events",
        ["plan_id", "created_at"],
    )
    op.create_index(
        "ix_workspace_plan_events_workspace_created",
        "workspace_plan_events",
        ["workspace_id", "created_at"],
    )
    op.create_index(
        "ix_workspace_plan_events_node",
        "workspace_plan_events",
        ["plan_id", "node_id", "created_at"],
    )
    op.create_index(
        "ix_workspace_plan_events_attempt",
        "workspace_plan_events",
        ["attempt_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_workspace_plan_events_attempt", table_name="workspace_plan_events")
    op.drop_index("ix_workspace_plan_events_node", table_name="workspace_plan_events")
    op.drop_index("ix_workspace_plan_events_workspace_created", table_name="workspace_plan_events")
    op.drop_index("ix_workspace_plan_events_plan_created", table_name="workspace_plan_events")
    op.drop_table("workspace_plan_events")
