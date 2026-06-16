"""add agent definition policy columns

Revision ID: j7e8f9a0b1c2
Revises: i6d7e8f9a0b1
Create Date: 2026-06-16

"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "j7e8f9a0b1c2"
down_revision: str | Sequence[str] | None = "i6d7e8f9a0b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_NAME = "agent_definitions"
SPAWN_POLICY_COLUMN = "spawn_policy"
TOOL_POLICY_COLUMN = "tool_policy"


def _column_names() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns(TABLE_NAME)}


def _is_offline_mode() -> bool:
    return bool(getattr(op.get_context(), "as_sql", False))


def upgrade() -> None:
    """Persist structured delegation and tool-access policy on agent definitions."""
    columns = set() if _is_offline_mode() else _column_names()

    if _is_offline_mode() or SPAWN_POLICY_COLUMN not in columns:
        op.add_column(TABLE_NAME, sa.Column(SPAWN_POLICY_COLUMN, sa.JSON(), nullable=True))
    if _is_offline_mode() or TOOL_POLICY_COLUMN not in columns:
        op.add_column(TABLE_NAME, sa.Column(TOOL_POLICY_COLUMN, sa.JSON(), nullable=True))


def downgrade() -> None:
    """Remove structured agent definition policy columns."""
    columns = set() if _is_offline_mode() else _column_names()

    if _is_offline_mode() or TOOL_POLICY_COLUMN in columns:
        op.drop_column(TABLE_NAME, TOOL_POLICY_COLUMN)
    if _is_offline_mode() or SPAWN_POLICY_COLUMN in columns:
        op.drop_column(TABLE_NAME, SPAWN_POLICY_COLUMN)
