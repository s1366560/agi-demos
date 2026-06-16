"""add project scope to skill evolution jobs

Revision ID: k9f0a1b2c3d4
Revises: j7e8f9a0b1c2
Create Date: 2026-06-16

"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "k9f0a1b2c3d4"
down_revision: str | Sequence[str] | None = "j7e8f9a0b1c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_NAME = "skill_evolution_jobs"
PROJECT_ID_COLUMN = "project_id"
PROJECT_INDEX = "ix_skill_evolution_jobs_project_id"
SKILL_TENANT_PROJECT_INDEX = "ix_skill_evolution_jobs_skill_tenant_project"


def _is_offline_mode() -> bool:
    return bool(getattr(op.get_context(), "as_sql", False))


def _column_names() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns(TABLE_NAME)}


def _index_names() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {index["name"] for index in inspector.get_indexes(TABLE_NAME)}


def upgrade() -> None:
    """Track which project produced and owns a skill evolution job."""
    offline = _is_offline_mode()
    columns = set() if offline else _column_names()
    indexes = set() if offline else _index_names()

    if offline or PROJECT_ID_COLUMN not in columns:
        op.add_column(TABLE_NAME, sa.Column(PROJECT_ID_COLUMN, sa.String(), nullable=True))
    if offline or PROJECT_INDEX not in indexes:
        op.create_index(PROJECT_INDEX, TABLE_NAME, [PROJECT_ID_COLUMN])
    if offline or SKILL_TENANT_PROJECT_INDEX not in indexes:
        op.create_index(
            SKILL_TENANT_PROJECT_INDEX,
            TABLE_NAME,
            ["skill_name", "tenant_id", PROJECT_ID_COLUMN],
        )


def downgrade() -> None:
    """Remove project scope from skill evolution jobs."""
    offline = _is_offline_mode()
    columns = set() if offline else _column_names()
    indexes = set() if offline else _index_names()

    if offline or SKILL_TENANT_PROJECT_INDEX in indexes:
        op.drop_index(SKILL_TENANT_PROJECT_INDEX, table_name=TABLE_NAME)
    if offline or PROJECT_INDEX in indexes:
        op.drop_index(PROJECT_INDEX, table_name=TABLE_NAME)
    if offline or PROJECT_ID_COLUMN in columns:
        op.drop_column(TABLE_NAME, PROJECT_ID_COLUMN)
