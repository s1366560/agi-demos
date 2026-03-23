"""add session_policy delegate_config model_override group_id agent_to_agent_allowlist

Revision ID: 43b727f54251
Revises: ff587f7ed717
Create Date: 2026-03-23 17:03:58.376255

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "43b727f54251"
down_revision: Union[str, Sequence[str], None] = "ff587f7ed717"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # agent_bindings: broadcast group support (Gap 5)
    op.add_column("agent_bindings", sa.Column("group_id", sa.String(length=100), nullable=True))
    op.create_index(
        op.f("ix_agent_bindings_group_id"), "agent_bindings", ["group_id"], unique=False
    )

    # agent_definitions: session policy (Gap 2+3), delegate config (Gap 1), allowlist (Gap 12)
    op.add_column("agent_definitions", sa.Column("session_policy", sa.JSON(), nullable=True))
    op.add_column("agent_definitions", sa.Column("delegate_config", sa.JSON(), nullable=True))
    op.add_column(
        "agent_definitions", sa.Column("agent_to_agent_allowlist", sa.JSON(), nullable=True)
    )

    # channel_configs: per-channel model override (Gap 8)
    op.add_column(
        "channel_configs",
        sa.Column(
            "model_override",
            sa.String(length=255),
            nullable=True,
            comment="LLM model override for this channel config",
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("channel_configs", "model_override")
    op.drop_column("agent_definitions", "agent_to_agent_allowlist")
    op.drop_column("agent_definitions", "delegate_config")
    op.drop_column("agent_definitions", "session_policy")
    op.drop_index(op.f("ix_agent_bindings_group_id"), table_name="agent_bindings")
    op.drop_column("agent_bindings", "group_id")
