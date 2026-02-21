"""add channel outbox table

Revision ID: f7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-02-21 00:10:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "channel_outbox",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("channel_config_id", sa.String(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("chat_id", sa.String(), nullable=False),
        sa.Column("reply_to_channel_message_id", sa.String(), nullable=True),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("sent_channel_message_id", sa.String(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
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
    )
    op.create_index("ix_channel_outbox_project_id", "channel_outbox", ["project_id"], unique=False)
    op.create_index(
        "ix_channel_outbox_channel_config_id",
        "channel_outbox",
        ["channel_config_id"],
        unique=False,
    )
    op.create_index(
        "ix_channel_outbox_conversation_id",
        "channel_outbox",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        "ix_channel_outbox_status_retry",
        "channel_outbox",
        ["status", "next_retry_at"],
        unique=False,
    )
    op.create_index(
        "ix_channel_outbox_project_created",
        "channel_outbox",
        ["project_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_channel_outbox_project_created", table_name="channel_outbox")
    op.drop_index("ix_channel_outbox_status_retry", table_name="channel_outbox")
    op.drop_index("ix_channel_outbox_conversation_id", table_name="channel_outbox")
    op.drop_index("ix_channel_outbox_channel_config_id", table_name="channel_outbox")
    op.drop_index("ix_channel_outbox_project_id", table_name="channel_outbox")
    op.drop_table("channel_outbox")
