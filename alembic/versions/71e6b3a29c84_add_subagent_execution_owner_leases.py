"""add subagent execution owner leases

Revision ID: 71e6b3a29c84
Revises: 2d6a9c18e4b7
Create Date: 2026-09-14 13:41:02.179674

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "71e6b3a29c84"
down_revision: str | Sequence[str] | None = "2d6a9c18e4b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "subagent_owner_leases_v2",
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("owner_token", sa.String(), nullable=True),
        sa.Column("instance_id", sa.String(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("conversation_id", "run_id"),
    )
    op.create_index(
        op.f("ix_subagent_owner_leases_v2_expires_at"),
        "subagent_owner_leases_v2",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_subagent_owner_leases_v2_expires_at", table_name="subagent_owner_leases_v2")
    op.drop_table("subagent_owner_leases_v2")
