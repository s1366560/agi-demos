"""add channel config policy fields

Revision ID: g1a2b3c4d5e6
Revises: f7b8c9d0e1f2
Create Date: 2026-02-22 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "g1a2b3c4d5e6"
down_revision: Union[str, None] = "f7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "channel_configs",
        sa.Column(
            "dm_policy",
            sa.String(20),
            nullable=False,
            server_default="open",
        ),
    )
    op.add_column(
        "channel_configs",
        sa.Column(
            "group_policy",
            sa.String(20),
            nullable=False,
            server_default="open",
        ),
    )
    op.add_column(
        "channel_configs",
        sa.Column("allow_from", sa.JSON(), nullable=True),
    )
    op.add_column(
        "channel_configs",
        sa.Column("group_allow_from", sa.JSON(), nullable=True),
    )
    op.add_column(
        "channel_configs",
        sa.Column(
            "rate_limit_per_minute",
            sa.Integer(),
            nullable=False,
            server_default="60",
        ),
    )


def downgrade() -> None:
    op.drop_column("channel_configs", "rate_limit_per_minute")
    op.drop_column("channel_configs", "group_allow_from")
    op.drop_column("channel_configs", "allow_from")
    op.drop_column("channel_configs", "group_policy")
    op.drop_column("channel_configs", "dm_policy")
