"""Add spawn_policy, tool_policy, identity JSON columns to subagents table.

Revision ID: h1a2b3c4d5e6
Revises: f18043355e3b
Create Date: 2026-03-19
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "h1a2b3c4d5e6"
down_revision: Union[str, None] = "f18043355e3b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("subagents", sa.Column("spawn_policy_json", sa.JSON(), nullable=True))
    op.add_column("subagents", sa.Column("tool_policy_json", sa.JSON(), nullable=True))
    op.add_column("subagents", sa.Column("identity_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("subagents", "identity_json")
    op.drop_column("subagents", "tool_policy_json")
    op.drop_column("subagents", "spawn_policy_json")
