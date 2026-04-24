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


def upgrade() -> None:
    op.create_table(
        "workspace_plan_outbox",
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
    op.create_index(
        "ix_workspace_plan_outbox_plan",
        "workspace_plan_outbox",
        ["plan_id"],
    )
    op.create_index(
        "ix_workspace_plan_outbox_workspace_status",
        "workspace_plan_outbox",
        ["workspace_id", "status"],
    )
    op.create_index(
        "ix_workspace_plan_outbox_status_next_attempt",
        "workspace_plan_outbox",
        ["status", "next_attempt_at"],
    )
    op.create_index(
        "ix_workspace_plan_outbox_lease",
        "workspace_plan_outbox",
        ["lease_owner", "lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_workspace_plan_outbox_lease", table_name="workspace_plan_outbox")
    op.drop_index(
        "ix_workspace_plan_outbox_status_next_attempt",
        table_name="workspace_plan_outbox",
    )
    op.drop_index(
        "ix_workspace_plan_outbox_workspace_status",
        table_name="workspace_plan_outbox",
    )
    op.drop_index("ix_workspace_plan_outbox_plan", table_name="workspace_plan_outbox")
    op.drop_table("workspace_plan_outbox")
