"""add workspace plan outbox

Revision ID: i7b8c9d0e1f2
Revises: h6a7b8c9d0e1
Create Date: 2026-04-24 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "i7b8c9d0e1f2"
down_revision: str | Sequence[str] | None = "h6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLE_NAME = "workspace_plan_outbox"


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
            sa.Column("event_type", sa.String(length=80), nullable=False),
            sa.Column(
                "payload_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'::json"),
            ),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("attempt_count", sa.Integer(), nullable=False),
            sa.Column("max_attempts", sa.Integer(), nullable=False),
            sa.Column("lease_owner", sa.String(length=255), nullable=True),
            sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "metadata_json",
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
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["plan_id"], ["workspace_plans.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    if not _has_index(TABLE_NAME, "ix_workspace_plan_outbox_plan"):
        op.create_index(
            "ix_workspace_plan_outbox_plan",
            TABLE_NAME,
            ["plan_id"],
        )
    if not _has_index(TABLE_NAME, "ix_workspace_plan_outbox_workspace_status"):
        op.create_index(
            "ix_workspace_plan_outbox_workspace_status",
            TABLE_NAME,
            ["workspace_id", "status"],
        )
    if not _has_index(TABLE_NAME, "ix_workspace_plan_outbox_status_next_attempt"):
        op.create_index(
            "ix_workspace_plan_outbox_status_next_attempt",
            TABLE_NAME,
            ["status", "next_attempt_at"],
        )
    if not _has_index(TABLE_NAME, "ix_workspace_plan_outbox_lease"):
        op.create_index(
            "ix_workspace_plan_outbox_lease",
            TABLE_NAME,
            ["lease_owner", "lease_expires_at"],
        )


def downgrade() -> None:
    if _has_index(TABLE_NAME, "ix_workspace_plan_outbox_lease"):
        op.drop_index("ix_workspace_plan_outbox_lease", table_name=TABLE_NAME)
    if _has_index(TABLE_NAME, "ix_workspace_plan_outbox_status_next_attempt"):
        op.drop_index(
            "ix_workspace_plan_outbox_status_next_attempt",
            table_name=TABLE_NAME,
        )
    if _has_index(TABLE_NAME, "ix_workspace_plan_outbox_workspace_status"):
        op.drop_index(
            "ix_workspace_plan_outbox_workspace_status",
            table_name=TABLE_NAME,
        )
    if _has_index(TABLE_NAME, "ix_workspace_plan_outbox_plan"):
        op.drop_index("ix_workspace_plan_outbox_plan", table_name=TABLE_NAME)
    if _has_table(TABLE_NAME):
        op.drop_table(TABLE_NAME)
