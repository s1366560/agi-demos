"""add workspace_blackboard_outbox table

Adds a transactional outbox table for blackboard SSE events so that
post/reply/file mutations and their corresponding event dispatch share a
single DB transaction. A background dispatcher drains pending rows and
publishes them to the Redis workspace event bus.

Revision ID: w7b8c9d0e1f2
Revises: v6a7b8c9d0e1
Create Date: 2026-05-13
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "w7b8c9d0e1f2"
down_revision: str | Sequence[str] | None = "v6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_blackboard_outbox",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("correlation_id", sa.String(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default=sa.text("10")),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_blackboard_outbox_workspace_status",
        "workspace_blackboard_outbox",
        ["workspace_id", "status"],
    )
    op.create_index(
        "ix_blackboard_outbox_status_next_attempt",
        "workspace_blackboard_outbox",
        ["status", "next_attempt_at"],
    )
    op.create_index(
        "ix_blackboard_outbox_created_at",
        "workspace_blackboard_outbox",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_blackboard_outbox_created_at", table_name="workspace_blackboard_outbox")
    op.drop_index(
        "ix_blackboard_outbox_status_next_attempt", table_name="workspace_blackboard_outbox"
    )
    op.drop_index(
        "ix_blackboard_outbox_workspace_status", table_name="workspace_blackboard_outbox"
    )
    op.drop_table("workspace_blackboard_outbox")
