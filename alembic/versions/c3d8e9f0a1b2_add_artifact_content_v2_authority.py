"""add artifact content v2 authority

Revision ID: c3d8e9f0a1b2
Revises: b2c7d8e9f0a1
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c3d8e9f0a1b2"
down_revision: str | Sequence[str] | None = "b2c7d8e9f0a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add revisioned metadata pointer and durable idempotency receipts."""
    op.add_column(
        "artifacts",
        sa.Column(
            "content_revision",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
    )
    op.add_column(
        "artifacts",
        sa.Column("content_hash", sa.String(length=71), nullable=True),
    )
    op.create_check_constraint(
        "ck_artifacts_content_revision",
        "artifacts",
        "content_revision >= 0",
    )
    op.create_table(
        "artifact_content_receipts",
        sa.Column("artifact_id", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("request_hash", sa.String(length=71), nullable=False),
        sa.Column("expected_revision", sa.BigInteger(), nullable=False),
        sa.Column("resulting_revision", sa.BigInteger(), nullable=False),
        sa.Column("content_hash", sa.String(length=71), nullable=False),
        sa.Column("object_key", sa.String(length=500), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "expected_revision >= 0",
            name="ck_artifact_receipts_expected_revision",
        ),
        sa.CheckConstraint(
            "resulting_revision > 0",
            name="ck_artifact_receipts_resulting_revision",
        ),
        sa.CheckConstraint(
            "size_bytes >= 0",
            name="ck_artifact_receipts_size_bytes",
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["artifacts.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("artifact_id", "idempotency_key"),
    )
    op.create_index(
        "ix_artifact_content_receipts_scope",
        "artifact_content_receipts",
        ["tenant_id", "project_id", "artifact_id"],
    )


def downgrade() -> None:
    """Remove ArtifactContentContractV2 persistence."""
    op.drop_index(
        "ix_artifact_content_receipts_scope",
        table_name="artifact_content_receipts",
    )
    op.drop_table("artifact_content_receipts")
    op.drop_constraint(
        "ck_artifacts_content_revision",
        "artifacts",
        type_="check",
    )
    op.drop_column("artifacts", "content_hash")
    op.drop_column("artifacts", "content_revision")
