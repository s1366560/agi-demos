"""add_sync_error_to_mcp_servers

Revision ID: 0c10a5d7e203
Revises: b3f7c2d8e9a1
Create Date: 2026-02-07 17:15:55.680845

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0c10a5d7e203'
down_revision: Union[str, Sequence[str], None] = 'b3f7c2d8e9a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('mcp_servers', sa.Column('sync_error', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('mcp_servers', 'sync_error')
