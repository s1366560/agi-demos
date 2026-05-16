"""add user profile json

Revision ID: z1a2b3c4d5e6
Revises: y9d0e1f2a3b4
Create Date: 2026-05-16 11:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "z1a2b3c4d5e6"
down_revision: str | Sequence[str] | None = "y9d0e1f2a3b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLE_NAME = "users"
COLUMN_NAME = "profile"


def _column_names() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns(TABLE_NAME)}


def _is_offline_mode() -> bool:
    return bool(getattr(op.get_context(), "as_sql", False))


def upgrade() -> None:
    """Persist user profile metadata edited from account settings."""
    if not _is_offline_mode() and COLUMN_NAME in _column_names():
        return

    op.add_column(
        TABLE_NAME,
        sa.Column(COLUMN_NAME, sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.alter_column(TABLE_NAME, COLUMN_NAME, server_default=None)


def downgrade() -> None:
    """Remove persisted user profile metadata."""
    if not _is_offline_mode() and COLUMN_NAME not in _column_names():
        return

    op.drop_column(TABLE_NAME, COLUMN_NAME)
