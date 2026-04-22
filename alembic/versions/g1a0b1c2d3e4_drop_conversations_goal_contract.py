"""g1 drop conversations.goal_contract column.

Revision ID: g1a0b1c2d3e4
Revises: p2b3a0c4e5f6
Create Date: 2026-05-10

Track G1 (Workspace-first pivot). ``GoalContract`` is removed from the
domain — terminal goals and budget caps now live on the owning
``Workspace`` / ``WorkspaceTask``. Drop the ``conversations.goal_contract``
JSON column; any existing rows' goal data is orphaned (migration path:
operators should re-create as WorkspaceTasks before running this upgrade
if the data matters; none is production-critical at time of ship).

``downgrade()`` recreates the column as nullable JSON for reversibility
but obviously cannot restore prior payloads.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "g1a0b1c2d3e4"
down_revision: str | Sequence[str] | None = "p2b3a0c4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop conversations.goal_contract."""
    bind = op.get_bind()
    bind.exec_driver_sql("SET LOCAL lock_timeout = '10s'")
    op.drop_column("conversations", "goal_contract")


def downgrade() -> None:
    """Re-add conversations.goal_contract (no data restore)."""
    op.add_column(
        "conversations",
        sa.Column("goal_contract", sa.JSON(), nullable=True),
    )
