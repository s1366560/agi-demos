"""add channel session bindings

Revision ID: f6a7b8c9d0e1
Revises: e1f2a3b4c5d6
Create Date: 2026-02-21 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "channel_session_bindings",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("channel_config_id", sa.String(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("channel_type", sa.String(), nullable=False),
        sa.Column("chat_id", sa.String(), nullable=False),
        sa.Column("chat_type", sa.String(), nullable=False),
        sa.Column("thread_id", sa.String(), nullable=True),
        sa.Column("topic_id", sa.String(), nullable=True),
        sa.Column("session_key", sa.String(length=512), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["channel_config_id"], ["channel_configs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "session_key",
            name="uq_channel_session_bindings_project_session_key",
        ),
        sa.UniqueConstraint(
            "conversation_id",
            name="uq_channel_session_bindings_conversation_id",
        ),
    )
    op.create_index(
        "ix_channel_session_bindings_project_id",
        "channel_session_bindings",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_channel_session_bindings_channel_config_id",
        "channel_session_bindings",
        ["channel_config_id"],
        unique=False,
    )
    op.create_index(
        "ix_channel_session_bindings_project_chat",
        "channel_session_bindings",
        ["project_id", "chat_id"],
        unique=False,
    )
    op.create_index(
        "ix_channel_session_bindings_config_chat",
        "channel_session_bindings",
        ["channel_config_id", "chat_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_channel_session_bindings_config_chat", table_name="channel_session_bindings")
    op.drop_index("ix_channel_session_bindings_project_chat", table_name="channel_session_bindings")
    op.drop_index(
        "ix_channel_session_bindings_channel_config_id",
        table_name="channel_session_bindings",
    )
    op.drop_index("ix_channel_session_bindings_project_id", table_name="channel_session_bindings")
    op.drop_table("channel_session_bindings")
