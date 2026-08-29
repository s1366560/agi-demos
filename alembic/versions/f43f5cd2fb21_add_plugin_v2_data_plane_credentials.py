"""add plugin v2 data plane credentials

Revision ID: f43f5cd2fb21
Revises: b5e9f3d8c012
Create Date: 2026-08-30 05:00:13.276382
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f43f5cd2fb21"
down_revision: str | Sequence[str] | None = "b5e9f3d8c012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create hashed, auditable workload credentials bound to V2 data planes."""
    op.create_table(
        "platform_plugin_v2_data_plane_credentials",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("data_plane_id", sa.String(length=255), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("key_prefix", sa.String(length=18), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_user_id", sa.String(length=255), nullable=True),
        sa.Column("rotated_from_id", sa.String(length=36), nullable=True),
        sa.CheckConstraint(
            "length(data_plane_id) > 0",
            name="ck_platform_plugin_v2_data_plane_credential_plane",
        ),
        sa.CheckConstraint(
            "length(key_hash) = 64",
            name="ck_platform_plugin_v2_data_plane_credential_hash",
        ),
        sa.CheckConstraint(
            "length(key_prefix) = 18 AND substr(key_prefix, 1, 6) = 'ms_dp_'",
            name="ck_platform_plugin_v2_data_plane_credential_prefix",
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > created_at",
            name="ck_platform_plugin_v2_data_plane_credential_expiry",
        ),
        sa.CheckConstraint(
            "(revoked_at IS NULL AND revoked_by_user_id IS NULL) OR "
            "(revoked_at IS NOT NULL AND revoked_by_user_id IS NOT NULL)",
            name="ck_platform_plugin_v2_data_plane_credential_revocation",
        ),
        sa.ForeignKeyConstraint(
            ["rotated_from_id"],
            ["platform_plugin_v2_data_plane_credentials.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "key_hash",
            name="uq_platform_plugin_v2_data_plane_credential_hash",
        ),
    )
    op.create_index(
        "ix_platform_plugin_v2_data_plane_credential_plane_active",
        "platform_plugin_v2_data_plane_credentials",
        ["data_plane_id", "revoked_at", "expires_at"],
    )
    op.create_index(
        "ix_platform_plugin_v2_data_plane_credential_rotated_from",
        "platform_plugin_v2_data_plane_credentials",
        ["rotated_from_id"],
    )


def downgrade() -> None:
    """Remove only protocol-v2 data-plane workload credentials."""
    op.drop_index(
        "ix_platform_plugin_v2_data_plane_credential_rotated_from",
        table_name="platform_plugin_v2_data_plane_credentials",
    )
    op.drop_index(
        "ix_platform_plugin_v2_data_plane_credential_plane_active",
        table_name="platform_plugin_v2_data_plane_credentials",
    )
    op.drop_table("platform_plugin_v2_data_plane_credentials")
