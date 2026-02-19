"""merge_heads

Revision ID: b333c8709d75
Revises: d4e5f6a7b8c9, d8f2a1c3e5b7
Create Date: 2026-02-19 12:54:11.974428

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b333c8709d75'
down_revision: Union[str, Sequence[str], None] = ('d4e5f6a7b8c9', 'd8f2a1c3e5b7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
