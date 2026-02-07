"""merge_heads

Revision ID: 744edbe7a05b
Revises: 776383e6003d, 9a1c1a6b2d3e
Create Date: 2026-02-07 15:04:05.361307

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '744edbe7a05b'
down_revision: Union[str, Sequence[str], None] = ('776383e6003d', '9a1c1a6b2d3e')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
