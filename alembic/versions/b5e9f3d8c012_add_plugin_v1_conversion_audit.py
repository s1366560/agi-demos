"""add plugin v1 conversion audit

Revision ID: b5e9f3d8c012
Revises: a4d8e2c7b901
Create Date: 2026-08-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b5e9f3d8c012"
down_revision: str | Sequence[str] | None = "a4d8e2c7b901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create immutable evidence for completed offline V1 conversions."""
    op.create_table(
        "platform_plugin_v1_conversion_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("migration_id", sa.String(length=128), nullable=False),
        sa.Column("source_digest", sa.String(length=71), nullable=False),
        sa.Column("mapping_digest", sa.String(length=71), nullable=False),
        sa.Column("output_digest", sa.String(length=71), nullable=False),
        sa.Column("actor_id", sa.String(length=255), nullable=False),
        sa.Column("report", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(source_digest) = 71 AND substr(source_digest, 1, 7) = 'sha256:'",
            name="ck_platform_plugin_v1_conversion_source_digest",
        ),
        sa.CheckConstraint(
            "length(mapping_digest) = 71 AND substr(mapping_digest, 1, 7) = 'sha256:'",
            name="ck_platform_plugin_v1_conversion_mapping_digest",
        ),
        sa.CheckConstraint(
            "length(output_digest) = 71 AND substr(output_digest, 1, 7) = 'sha256:'",
            name="ck_platform_plugin_v1_conversion_output_digest",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "migration_id",
            name="uq_platform_plugin_v1_conversion_migration_id",
        ),
    )
    op.create_index(
        "ix_platform_plugin_v1_conversion_created",
        "platform_plugin_v1_conversion_runs",
        ["created_at", "migration_id"],
    )


def downgrade() -> None:
    """Remove only the offline conversion audit ledger."""
    op.drop_index(
        "ix_platform_plugin_v1_conversion_created",
        table_name="platform_plugin_v1_conversion_runs",
    )
    op.drop_table("platform_plugin_v1_conversion_runs")
