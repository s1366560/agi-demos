"""add workspace_messages table

Revision ID: 13210a8c06aa
Revises: ebb74c4411bc
Create Date: 2026-03-26 12:22:35.913724

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "13210a8c06aa"
down_revision: Union[str, Sequence[str], None] = "ebb74c4411bc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "workspace_messages",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("sender_id", sa.String(), nullable=False),
        sa.Column("sender_type", sa.String(length=10), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("mentions_json", sa.JSON(), nullable=False),
        sa.Column("parent_message_id", sa.String(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_workspace_messages_parent", "workspace_messages", ["parent_message_id"], unique=False
    )
    op.create_index(
        "ix_workspace_messages_workspace_created",
        "workspace_messages",
        ["workspace_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_workspace_messages_workspace_created", table_name="workspace_messages")
    op.drop_index("ix_workspace_messages_parent", table_name="workspace_messages")
    op.drop_table("workspace_messages")
