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


def upgrade() -> None:
    op.add_column(
        "workspace_plan_nodes",
        sa.Column("feature_checkpoint", sa.JSON(), nullable=True),
    )
    op.add_column(
        "workspace_plan_nodes",
        sa.Column("handoff_package", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workspace_plan_nodes", "handoff_package")
    op.drop_column("workspace_plan_nodes", "feature_checkpoint")
