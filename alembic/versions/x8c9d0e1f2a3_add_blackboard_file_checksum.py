"""add blackboard file checksum

Revision ID: x8c9d0e1f2a3
Revises: w7b8c9d0e1f2
Create Date: 2026-05-13

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "x8c9d0e1f2a3"
down_revision = "w7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "blackboard_files",
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "blackboard_files",
        sa.Column("mime_type_detected", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("blackboard_files", "mime_type_detected")
    op.drop_column("blackboard_files", "checksum_sha256")
