"""add_correlation_id_to_agent_events

Revision ID: 276db25ba465
Revises: 841c6ae07ebf
Create Date: 2026-02-04 08:13:50.204104

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '276db25ba465'
down_revision: Union[str, Sequence[str], None] = '841c6ae07ebf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add correlation_id column to agent_execution_events for request tracking."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_name = "agent_execution_events"
    if table_name not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns(table_name)}
    if "correlation_id" not in columns:
        op.add_column(table_name, sa.Column("correlation_id", sa.String(length=32), nullable=True))

    indexes = {index["name"] for index in inspector.get_indexes(table_name)}
    if "ix_agent_events_corr_id" not in indexes:
        op.create_index("ix_agent_events_corr_id", table_name, ["correlation_id"], unique=False)


def downgrade() -> None:
    """Remove correlation_id column from agent_execution_events."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_name = "agent_execution_events"
    if table_name not in inspector.get_table_names():
        return

    indexes = {index["name"] for index in inspector.get_indexes(table_name)}
    if "ix_agent_events_corr_id" in indexes:
        op.drop_index("ix_agent_events_corr_id", table_name=table_name)

    columns = {column["name"] for column in inspector.get_columns(table_name)}
    if "correlation_id" in columns:
        op.drop_column(table_name, "correlation_id")
