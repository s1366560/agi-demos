"""add_agent_session_snapshots

Revision ID: 9a1c1a6b2d3e
Revises: 276db25ba465
Create Date: 2026-02-05 09:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "9a1c1a6b2d3e"
down_revision: Union[str, Sequence[str], None] = "276db25ba465"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_session_snapshots",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("agent_mode", sa.String(), nullable=False),
        sa.Column("request_id", sa.String(), nullable=False),
        sa.Column("snapshot_type", sa.String(length=50), nullable=False),
        sa.Column("snapshot_data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_agent_session_snapshots_tenant_id",
        "agent_session_snapshots",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_session_snapshots_project_id",
        "agent_session_snapshots",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_session_snapshots_agent_mode",
        "agent_session_snapshots",
        ["agent_mode"],
        unique=False,
    )
    op.create_index(
        "ix_agent_session_snapshots_request_id",
        "agent_session_snapshots",
        ["request_id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_session_snapshots_snapshot_type",
        "agent_session_snapshots",
        ["snapshot_type"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_agent_session_snapshots_snapshot_type", table_name="agent_session_snapshots")
    op.drop_index("ix_agent_session_snapshots_request_id", table_name="agent_session_snapshots")
    op.drop_index("ix_agent_session_snapshots_agent_mode", table_name="agent_session_snapshots")
    op.drop_index("ix_agent_session_snapshots_project_id", table_name="agent_session_snapshots")
    op.drop_index("ix_agent_session_snapshots_tenant_id", table_name="agent_session_snapshots")
    op.drop_table("agent_session_snapshots")
