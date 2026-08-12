"""Align the Avernet Workspace topology schema with the legacy contract.

Revision ID: 9f37c2a1b6d8
Revises: 8e26a5c9d0f4
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "9f37c2a1b6d8"
down_revision: str | Sequence[str] | None = "8e26a5c9d0f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPGRADE_DDL: tuple[str, ...] = (
    """
    ALTER TABLE avernet.workspace_topology_nodes
        ALTER COLUMN ref_id TYPE VARCHAR(255),
        ALTER COLUMN status TYPE VARCHAR(32)
    """,
    """
    ALTER TABLE avernet.workspace_topology_edges
        ALTER COLUMN direction DROP NOT NULL,
        ALTER COLUMN direction DROP DEFAULT
    """,
)

_DOWNGRADE_DDL: tuple[str, ...] = (
    """
    UPDATE avernet.workspace_topology_edges
    SET direction = 'directed'
    WHERE direction IS NULL
    """,
    """
    ALTER TABLE avernet.workspace_topology_edges
        ALTER COLUMN direction SET DEFAULT 'directed',
        ALTER COLUMN direction SET NOT NULL
    """,
    """
    ALTER TABLE avernet.workspace_topology_nodes
        ALTER COLUMN status TYPE VARCHAR(20),
        ALTER COLUMN ref_id TYPE VARCHAR(128)
    """,
)


def upgrade() -> None:
    for statement in _UPGRADE_DDL:
        op.execute(statement)


def downgrade() -> None:
    for statement in _DOWNGRADE_DDL:
        op.execute(statement)
