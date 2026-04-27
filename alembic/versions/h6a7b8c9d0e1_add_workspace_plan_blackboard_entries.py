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


TABLE_NAME = "workspace_plan_blackboard_entries"


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
    if not _has_index(TABLE_NAME, "ix_workspace_plan_blackboard_plan"):
        op.create_index(
            "ix_workspace_plan_blackboard_plan",
            TABLE_NAME,
            ["plan_id"],
        )
    if not _has_index(TABLE_NAME, "ix_workspace_plan_blackboard_plan_key"):
        op.create_index(
            "ix_workspace_plan_blackboard_plan_key",
            TABLE_NAME,
            ["plan_id", "key"],
        )


def downgrade() -> None:
    if _has_index(TABLE_NAME, "ix_workspace_plan_blackboard_plan_key"):
        op.drop_index(
            "ix_workspace_plan_blackboard_plan_key",
            table_name=TABLE_NAME,
        )
    if _has_index(TABLE_NAME, "ix_workspace_plan_blackboard_plan"):
        op.drop_index(
            "ix_workspace_plan_blackboard_plan",
            table_name=TABLE_NAME,
        )
    if _has_table(TABLE_NAME):
        op.drop_table(TABLE_NAME)
