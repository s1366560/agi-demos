"""Align the Avernet Workspace Gene schema with the legacy contract.

Revision ID: a17c3e5f7b9d
Revises: 9f37c2a1b6d8
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "a17c3e5f7b9d"
down_revision: str | Sequence[str] | None = "9f37c2a1b6d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPGRADE_DDL: tuple[str, ...] = (
    """
    ALTER TABLE avernet.workspace_genes
        ALTER COLUMN updated_at DROP NOT NULL
    """,
)

_DOWNGRADE_DDL: tuple[str, ...] = (
    """
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM avernet.workspace_genes WHERE updated_at IS NULL
        ) THEN
            RAISE EXCEPTION
                'workspace_genes contains legacy-compatible NULL updated_at values';
        END IF;
    END
    $$
    """,
    """
    ALTER TABLE avernet.workspace_genes
        ALTER COLUMN updated_at SET NOT NULL
    """,
)


def upgrade() -> None:
    for statement in _UPGRADE_DDL:
        op.execute(statement)


def downgrade() -> None:
    for statement in _DOWNGRADE_DDL:
        op.execute(statement)
