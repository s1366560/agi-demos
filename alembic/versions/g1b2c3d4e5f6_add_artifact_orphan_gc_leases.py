"""add artifact orphan gc leases

Revision ID: g1b2c3d4e5f6
Revises: e5f6a7b8c9d0
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "g1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add retry scheduling and complete lease ownership to the orphan queue."""
    op.add_column(
        "artifact_content_orphan_gc",
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.add_column(
        "artifact_content_orphan_gc",
        sa.Column("lease_owner", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "artifact_content_orphan_gc",
        sa.Column("lease_token", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "artifact_content_orphan_gc",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_artifact_orphan_gc_lease_complete",
        "artifact_content_orphan_gc",
        "(status = 'pending' AND "
        + "((lease_owner IS NULL AND lease_token IS NULL AND lease_expires_at IS NULL) "
        + "OR (lease_owner IS NOT NULL AND lease_token IS NOT NULL "
        + "AND lease_expires_at IS NOT NULL))) "
        + "OR (status <> 'pending' AND lease_owner IS NULL AND lease_token IS NULL "
        + "AND lease_expires_at IS NULL)",
    )
    op.drop_index(
        "ix_artifact_content_orphan_gc_status_updated",
        table_name="artifact_content_orphan_gc",
    )
    op.create_index(
        "ix_artifact_content_orphan_gc_dispatch",
        "artifact_content_orphan_gc",
        ["status", "next_attempt_at", "lease_expires_at"],
    )


def downgrade() -> None:
    """Remove retry scheduling and lease ownership from the orphan queue."""
    op.drop_index(
        "ix_artifact_content_orphan_gc_dispatch",
        table_name="artifact_content_orphan_gc",
    )
    op.create_index(
        "ix_artifact_content_orphan_gc_status_updated",
        "artifact_content_orphan_gc",
        ["status", "updated_at"],
    )
    op.drop_constraint(
        "ck_artifact_orphan_gc_lease_complete",
        "artifact_content_orphan_gc",
        type_="check",
    )
    op.drop_column("artifact_content_orphan_gc", "lease_expires_at")
    op.drop_column("artifact_content_orphan_gc", "lease_token")
    op.drop_column("artifact_content_orphan_gc", "lease_owner")
    op.drop_column("artifact_content_orphan_gc", "next_attempt_at")
