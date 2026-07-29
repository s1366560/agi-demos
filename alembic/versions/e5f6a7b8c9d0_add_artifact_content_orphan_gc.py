"""add artifact content orphan gc

Revision ID: e5f6a7b8c9d0
Revises: c3d8e9f0a1b2
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: str | Sequence[str] | None = "c3d8e9f0a1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the durable provisional-object reconciliation queue."""
    op.create_table(
        "artifact_content_orphan_gc",
        sa.Column("object_key", sa.String(length=500), nullable=False),
        sa.Column("artifact_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("conversation_id", sa.String(length=64), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=71), nullable=False),
        sa.Column("content_revision", sa.BigInteger(), nullable=False),
        sa.Column("content_hash", sa.String(length=71), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "content_revision > 0",
            name="ck_artifact_orphan_gc_content_revision",
        ),
        sa.CheckConstraint(
            "attempts >= 0",
            name="ck_artifact_orphan_gc_attempts",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'deleted', 'missing', 'retained')",
            name="ck_artifact_orphan_gc_status",
        ),
        sa.PrimaryKeyConstraint("object_key"),
    )
    op.create_index(
        "ix_artifact_content_orphan_gc_status_updated",
        "artifact_content_orphan_gc",
        ["status", "updated_at"],
    )
    op.create_index(
        "ix_artifact_content_orphan_gc_scope",
        "artifact_content_orphan_gc",
        ["tenant_id", "project_id", "artifact_id"],
    )


def downgrade() -> None:
    """Remove the Artifact content orphan reconciliation queue."""
    op.drop_index(
        "ix_artifact_content_orphan_gc_scope",
        table_name="artifact_content_orphan_gc",
    )
    op.drop_index(
        "ix_artifact_content_orphan_gc_status_updated",
        table_name="artifact_content_orphan_gc",
    )
    op.drop_table("artifact_content_orphan_gc")
