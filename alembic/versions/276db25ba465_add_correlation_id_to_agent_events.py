"""add_correlation_id_to_agent_events

Revision ID: 276db25ba465
Revises: 841c6ae07ebf
Create Date: 2026-02-04 08:13:50.204104

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '276db25ba465'
down_revision: Union[str, Sequence[str], None] = '841c6ae07ebf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add correlation_id column to agent_execution_events for request tracking."""
    op.add_column('agent_execution_events', sa.Column('correlation_id', sa.String(length=32), nullable=True))
    op.create_index('ix_agent_events_corr_id', 'agent_execution_events', ['correlation_id'], unique=False)


def downgrade() -> None:
    """Remove correlation_id column from agent_execution_events."""
    op.drop_index('ix_agent_events_corr_id', table_name='agent_execution_events')
    op.drop_column('agent_execution_events', 'correlation_id')
