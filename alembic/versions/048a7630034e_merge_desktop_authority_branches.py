"""merge desktop authority branches

Revision ID: 048a7630034e
Revises: d4e9f0a1b2c3, g1b2c3d4e5f6
Create Date: 2026-07-29 11:23:24.360643

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '048a7630034e'
down_revision: Union[str, Sequence[str], None] = ('d4e9f0a1b2c3', 'g1b2c3d4e5f6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
