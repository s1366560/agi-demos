"""add workspace plan handoff fields

Revision ID: k8d9e0f1a2b3
Revises: j8c9d0e1f2a3
Create Date: 2026-04-27 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "k8d9e0f1a2b3"
down_revision: str | Sequence[str] | None = "j8c9d0e1f2a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLE_NAME = "workspace_plan_nodes"


def _has_column(table_name: str, column_name: str) -> bool:
    return any(
        column["name"] == column_name
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    )


def upgrade() -> None:
    if not _has_column(TABLE_NAME, "feature_checkpoint"):
        op.add_column(
            TABLE_NAME,
            sa.Column("feature_checkpoint", sa.JSON(), nullable=True),
        )
    if not _has_column(TABLE_NAME, "handoff_package"):
        op.add_column(
            TABLE_NAME,
            sa.Column("handoff_package", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    if _has_column(TABLE_NAME, "handoff_package"):
        op.drop_column(TABLE_NAME, "handoff_package")
    if _has_column(TABLE_NAME, "feature_checkpoint"):
        op.drop_column(TABLE_NAME, "feature_checkpoint")
