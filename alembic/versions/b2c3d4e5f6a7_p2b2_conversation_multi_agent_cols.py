"""p2b2 conversation + message multi-agent columns.

Revision ID: b2c3d4e5f6a7
Revises: b1a2c3d4e5f6
Create Date: 2026-04-25

Phase-2.1 (Track B · Agent First) follow-on to the participant_agents
dark-launch. Surfaces the remaining multi-agent columns so the domain
roster + goal contract + message sender / mention fields are
persistable.

Column-add only; no backfill, no constraint changes. Existing single-
agent conversations keep working unchanged (all new columns nullable
or default to safe empty values).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | Sequence[str] | None = "b1a2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add 4 conversation columns + 2 message columns."""
    # conversations.conversation_mode  — nullable override of project default.
    op.add_column(
        "conversations",
        sa.Column("conversation_mode", sa.String(length=32), nullable=True),
    )
    # conversations.coordinator_agent_id  — required in AUTONOMOUS mode only.
    op.add_column(
        "conversations",
        sa.Column("coordinator_agent_id", sa.String(), nullable=True),
    )
    # conversations.focused_agent_id  — active agent for ISOLATED mode.
    op.add_column(
        "conversations",
        sa.Column("focused_agent_id", sa.String(), nullable=True),
    )
    # conversations.goal_contract  — serialized GoalContract (JSON).
    op.add_column(
        "conversations",
        sa.Column("goal_contract", sa.JSON(), nullable=True),
    )

    # messages.sender_agent_id  — which agent produced the message (NULL = user).
    op.add_column(
        "messages",
        sa.Column("sender_agent_id", sa.String(), nullable=True),
    )
    # messages.mentions  — structured @mention list produced by the frontend.
    op.add_column(
        "messages",
        sa.Column(
            "mentions",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )


def downgrade() -> None:
    """Drop the 6 new columns.

    Fail fast (10s lock_timeout) rather than hanging behind stale
    idle-in-transaction backends — matches Track A pattern established
    in b1a2c3d4e5f6.
    """
    bind = op.get_bind()
    bind.exec_driver_sql("SET LOCAL lock_timeout = '10s'")
    op.drop_column("messages", "mentions")
    op.drop_column("messages", "sender_agent_id")
    op.drop_column("conversations", "goal_contract")
    op.drop_column("conversations", "focused_agent_id")
    op.drop_column("conversations", "coordinator_agent_id")
    op.drop_column("conversations", "conversation_mode")
