"""add preferred_language to users

Revision ID: c5680baba419
Revises: x8c9d0e1f2a3
Create Date: 2026-05-13 13:07:56.094969

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c5680baba419"
down_revision: Union[str, Sequence[str], None] = "x8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add nullable preferred_language column to users."""
    op.add_column(
        "users",
        sa.Column("preferred_language", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    """Drop preferred_language column from users."""
    op.drop_column("users", "preferred_language")
