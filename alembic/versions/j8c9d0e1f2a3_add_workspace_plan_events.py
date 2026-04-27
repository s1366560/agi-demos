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


TABLE_NAME = "workspace_plan_events"


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _has_index(table_name: str, index_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return any(
        index["name"] == index_name for index in sa.inspect(op.get_bind()).get_indexes(table_name)
    )


def upgrade() -> None:
    if not _has_table(TABLE_NAME):
        op.create_table(
            TABLE_NAME,
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
    if not _has_index(TABLE_NAME, "ix_workspace_plan_events_plan_created"):
        op.create_index(
            "ix_workspace_plan_events_plan_created",
            TABLE_NAME,
            ["plan_id", "created_at"],
        )
    if not _has_index(TABLE_NAME, "ix_workspace_plan_events_workspace_created"):
        op.create_index(
            "ix_workspace_plan_events_workspace_created",
            TABLE_NAME,
            ["workspace_id", "created_at"],
        )
    if not _has_index(TABLE_NAME, "ix_workspace_plan_events_node"):
        op.create_index(
            "ix_workspace_plan_events_node",
            TABLE_NAME,
            ["plan_id", "node_id", "created_at"],
        )
    if not _has_index(TABLE_NAME, "ix_workspace_plan_events_attempt"):
        op.create_index(
            "ix_workspace_plan_events_attempt",
            TABLE_NAME,
            ["attempt_id"],
        )


def downgrade() -> None:
    if _has_index(TABLE_NAME, "ix_workspace_plan_events_attempt"):
        op.drop_index("ix_workspace_plan_events_attempt", table_name=TABLE_NAME)
    if _has_index(TABLE_NAME, "ix_workspace_plan_events_node"):
        op.drop_index("ix_workspace_plan_events_node", table_name=TABLE_NAME)
    if _has_index(TABLE_NAME, "ix_workspace_plan_events_workspace_created"):
        op.drop_index("ix_workspace_plan_events_workspace_created", table_name=TABLE_NAME)
    if _has_index(TABLE_NAME, "ix_workspace_plan_events_plan_created"):
        op.drop_index("ix_workspace_plan_events_plan_created", table_name=TABLE_NAME)
    if _has_table(TABLE_NAME):
        op.drop_table(TABLE_NAME)
