"""add workspace plan blackboard entries

Revision ID: h6a7b8c9d0e1
Revises: g5f2a3b4c5d6
Create Date: 2026-04-24 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "h6a7b8c9d0e1"
down_revision: str | Sequence[str] | None = "g5f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_plan_blackboard_entries",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("plan_id", sa.String(), nullable=False),
        sa.Column("key", sa.String(length=500), nullable=False),
        sa.Column("value_json", sa.JSON(), nullable=True),
        sa.Column("published_by", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("schema_ref", sa.String(), nullable=True),
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
        sa.ForeignKeyConstraint(["plan_id"], ["workspace_plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "plan_id",
            "key",
            "version",
            name="uq_workspace_plan_blackboard_plan_key_version",
        ),
    )
    op.create_index(
        "ix_workspace_plan_blackboard_plan",
        "workspace_plan_blackboard_entries",
        ["plan_id"],
    )
    op.create_index(
        "ix_workspace_plan_blackboard_plan_key",
        "workspace_plan_blackboard_entries",
        ["plan_id", "key"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workspace_plan_blackboard_plan_key",
        table_name="workspace_plan_blackboard_entries",
    )
    op.drop_index(
        "ix_workspace_plan_blackboard_plan",
        table_name="workspace_plan_blackboard_entries",
    )
    op.drop_table("workspace_plan_blackboard_entries")
