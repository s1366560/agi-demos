"""add agent_tasks table

Revision ID: b1c2d3e4f5a6
Revises: afa283626aea
Create Date: 2026-02-12 06:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, Sequence[str], None] = "afa283626aea"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_tasks",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("priority", sa.String(10), nullable=False, server_default="medium"),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_agent_tasks_conversation_id",
        "agent_tasks",
        ["conversation_id"],
    )
    op.create_index(
        "ix_agent_tasks_conv_status",
        "agent_tasks",
        ["conversation_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_tasks_conv_status", table_name="agent_tasks")
    op.drop_index("ix_agent_tasks_conversation_id", table_name="agent_tasks")
    op.drop_table("agent_tasks")
