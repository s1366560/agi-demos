"""add marketplace package manifest

Revision ID: d8e9f0a1b2c3
Revises: c7df09004ba2
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d8e9f0a1b2c3"
down_revision: str | Sequence[str] | None = "c7df09004ba2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Persist the verified manifest needed for later permission approvals."""
    op.add_column(
        "platform_plugin_packages",
        sa.Column(
            "manifest",
            postgresql.JSONB(astext_type=sa.Text()).not_null(),
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    """Remove package manifest persistence."""
    op.drop_column("platform_plugin_packages", "manifest")
