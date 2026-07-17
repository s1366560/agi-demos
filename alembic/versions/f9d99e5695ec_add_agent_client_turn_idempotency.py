"""add agent client turn idempotency

Revision ID: f9d99e5695ec
Revises: 8d3e1c9b2a71
Create Date: 2026-07-17 09:25:58.839701

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f9d99e5695ec"
down_revision: str | Sequence[str] | None = "8d3e1c9b2a71"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the durable client-turn idempotency ledger."""
    op.create_table(
        "agent_client_turns",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("client_message_id", sa.String(length=255), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("execution_message_id", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="accepted",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "conversation_id",
            "client_message_id",
            name="uq_agent_client_turns_conversation_message",
        ),
    )
    op.create_index(
        "ix_agent_client_turns_conversation_status",
        "agent_client_turns",
        ["conversation_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    """Drop the durable client-turn idempotency ledger."""
    op.drop_index(
        "ix_agent_client_turns_conversation_status",
        table_name="agent_client_turns",
    )
    op.drop_table("agent_client_turns")
