"""pin signed package releases to agent runs

Revision ID: 7ca467e31a9a
Revises: 5f998ffc4874
Create Date: 2026-11-23 10:07:58.092581

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7ca467e31a9a"
down_revision: str | Sequence[str] | None = "5f998ffc4874"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_run_package_selections",
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("releases", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["agent_run_authorities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.add_column(
        "project_plugin_installations",
        sa.Column("authorization_epoch", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("project_plugin_installations", "authorization_epoch")
    op.drop_table("agent_run_package_selections")
