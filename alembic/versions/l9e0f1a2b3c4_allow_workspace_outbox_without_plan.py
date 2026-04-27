"""allow workspace outbox worker launch without plan

Revision ID: l9e0f1a2b3c4
Revises: k8d9e0f1a2b3
Create Date: 2026-04-27 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "l9e0f1a2b3c4"
down_revision: str | Sequence[str] | None = "k8d9e0f1a2b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "workspace_plan_outbox",
        "plan_id",
        existing_type=sa.String(),
        nullable=True,
    )


def downgrade() -> None:
    op.execute("DELETE FROM workspace_plan_outbox WHERE plan_id IS NULL")
    op.alter_column(
        "workspace_plan_outbox",
        "plan_id",
        existing_type=sa.String(),
        nullable=False,
    )
