"""add_agent_session_snapshots

Revision ID: 9a1c1a6b2d3e
Revises: 276db25ba465
Create Date: 2026-02-05 09:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9a1c1a6b2d3e"
down_revision: Union[str, Sequence[str], None] = "276db25ba465"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_name = "agent_session_snapshots"

    if table_name not in inspector.get_table_names():
        op.create_table(
            table_name,
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
        inspector = sa.inspect(bind)

    existing_indexes = {idx["name"] for idx in inspector.get_indexes(table_name)}
    wanted_indexes = (
        ("ix_agent_session_snapshots_tenant_id", ["tenant_id"]),
        ("ix_agent_session_snapshots_project_id", ["project_id"]),
        ("ix_agent_session_snapshots_agent_mode", ["agent_mode"]),
        ("ix_agent_session_snapshots_request_id", ["request_id"]),
        ("ix_agent_session_snapshots_snapshot_type", ["snapshot_type"]),
    )
    for index_name, columns in wanted_indexes:
        if index_name not in existing_indexes:
            op.create_index(index_name, table_name, columns, unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_name = "agent_session_snapshots"
    if table_name not in inspector.get_table_names():
        return

    existing_indexes = {idx["name"] for idx in inspector.get_indexes(table_name)}
    for index_name in (
        "ix_agent_session_snapshots_snapshot_type",
        "ix_agent_session_snapshots_request_id",
        "ix_agent_session_snapshots_agent_mode",
        "ix_agent_session_snapshots_project_id",
        "ix_agent_session_snapshots_tenant_id",
    ):
        if index_name in existing_indexes:
            op.drop_index(index_name, table_name=table_name)
    op.drop_table(table_name)
