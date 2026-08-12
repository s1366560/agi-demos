"""Relax conversation links for Avernet-owned workspaces.

Revision ID: e9f0a1b2c3d5
Revises: 727ce1982b0f
Create Date: 2026-08-12
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "e9f0a1b2c3d5"
down_revision: str | Sequence[str] | None = "727ce1982b0f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Turn legacy Workspace FKs into external authority correlations."""
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.drop_constraint("conversations_workspace_id_fkey", "conversations", type_="foreignkey")
    op.drop_constraint(
        "conversations_linked_workspace_task_id_fkey",
        "conversations",
        type_="foreignkey",
    )


def downgrade() -> None:
    """Restore legacy FKs after rejecting correlations absent from legacy tables."""
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM conversations conversation
                LEFT JOIN workspaces workspace ON workspace.id = conversation.workspace_id
                WHERE conversation.workspace_id IS NOT NULL AND workspace.id IS NULL
            ) OR EXISTS (
                SELECT 1
                FROM conversations conversation
                LEFT JOIN workspace_tasks task
                    ON task.id = conversation.linked_workspace_task_id
                WHERE conversation.linked_workspace_task_id IS NOT NULL AND task.id IS NULL
            ) THEN
                RAISE EXCEPTION
                    'cannot restore legacy conversation Workspace FKs while Avernet correlations exist';
            END IF;
        END
        $$
        """
    )
    op.create_foreign_key(
        "conversations_workspace_id_fkey",
        "conversations",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "conversations_linked_workspace_task_id_fkey",
        "conversations",
        "workspace_tasks",
        ["linked_workspace_task_id"],
        ["id"],
        ondelete="SET NULL",
    )
