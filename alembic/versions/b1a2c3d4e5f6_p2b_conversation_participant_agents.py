"""p2b dark-launch: conversation.participant_agents

Revision ID: b1a2c3d4e5f6
Revises: p2c3c4d5e6f7
Create Date: 2026-04-22

Dark-launch for Track B (P2-3 phase-2 multi-agent conversations).
Adds the ``participant_agents`` JSON column to ``conversations`` so that
phase-2.1 can ship domain/routing changes without a fresh migration.

Column only — no ORM mapping, no backfill, no routing change. Existing
code paths keep working unchanged (single-agent semantics retained via
the existing ``project.agent_conversation_mode`` flag).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b1a2c3d4e5f6"
down_revision: str | Sequence[str] | None = "p2c3c4d5e6f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add participant_agents JSON column (default []) to conversations."""
    op.add_column(
        "conversations",
        sa.Column(
            "participant_agents",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )


def downgrade() -> None:
    """Drop participant_agents column.

    Fail fast (10s lock_timeout) rather than hanging behind stale
    idle-in-transaction backends — matches Track A pattern.
    """
    bind = op.get_bind()
    bind.exec_driver_sql("SET LOCAL lock_timeout = '10s'")
    op.drop_column("conversations", "participant_agents")
