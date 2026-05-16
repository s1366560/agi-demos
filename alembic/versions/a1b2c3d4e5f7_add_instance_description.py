"""Add instance description.

Revision ID: a1b2c3d4e5f7
Revises: z1a2b3c4d5e6
Create Date: 2026-05-16 17:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1b2c3d4e5f7"
down_revision: str | Sequence[str] | None = "z1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("instances", sa.Column("description", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("instances", "description")
