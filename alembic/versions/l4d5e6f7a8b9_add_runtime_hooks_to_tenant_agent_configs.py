"""add runtime_hooks to tenant_agent_configs

Revision ID: l4d5e6f7a8b9
Revises: 0f7a8f48758d
Create Date: 2026-04-08 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "l4d5e6f7a8b9"
down_revision: Union[str, Sequence[str], None] = "0f7a8f48758d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "tenant_agent_configs",
        sa.Column(
            "runtime_hooks",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )
    op.alter_column("tenant_agent_configs", "runtime_hooks", server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("tenant_agent_configs", "runtime_hooks")
