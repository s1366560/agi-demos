"""add provider model filtering fields

Revision ID: 6716678957ce
Revises: b9c8d7e6f5a4
Create Date: 2026-03-04 19:44:28.891468

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "6716678957ce"
down_revision: Union[str, Sequence[str], None] = "b9c8d7e6f5a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add model filtering fields to llm_providers."""
    op.add_column(
        "llm_providers",
        sa.Column(
            "is_enabled",
            sa.Boolean(),
            server_default="true",
            nullable=False,
        ),
    )
    op.add_column(
        "llm_providers",
        sa.Column(
            "allowed_models",
            sa.Text(),
            nullable=True,
            comment="JSON array of allowed model prefixes",
        ),
    )
    op.add_column(
        "llm_providers",
        sa.Column(
            "blocked_models",
            sa.Text(),
            nullable=True,
            comment="JSON array of blocked model prefixes",
        ),
    )


def downgrade() -> None:
    """Remove model filtering fields from llm_providers."""
    op.drop_column("llm_providers", "blocked_models")
    op.drop_column("llm_providers", "allowed_models")
    op.drop_column("llm_providers", "is_enabled")
