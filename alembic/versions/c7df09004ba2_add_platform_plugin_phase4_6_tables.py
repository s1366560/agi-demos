"""add platform plugin phase 4-6 tables

Revision ID: c7df09004ba2
Revises: f9cef6a266ae
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c7df09004ba2"
down_revision: str | Sequence[str] | None = "f9cef6a266ae"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create permission, backend, route, quota, and package governance tables."""
    op.create_table(
        "platform_plugin_permissions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("scope_type", sa.String(length=16), nullable=False),
        sa.Column("scope_id", sa.String(length=255), nullable=False),
        sa.Column("plugin_id", sa.String(length=255), nullable=False),
        sa.Column("permission", sa.String(length=64), nullable=False),
        sa.Column("granted_by", sa.String(length=255), nullable=True),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scope_type",
            "scope_id",
            "plugin_id",
            "permission",
            name="uq_platform_plugin_permission_scope",
        ),
    )
    op.create_index(
        "ix_platform_plugin_permissions_plugin_id",
        "platform_plugin_permissions",
        ["plugin_id"],
    )
    op.create_index(
        "ix_platform_plugin_permission_scope",
        "platform_plugin_permissions",
        ["scope_type", "scope_id", "plugin_id"],
    )

    op.create_table(
        "platform_plugin_credential_grants",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("plugin_id", sa.String(length=255), nullable=False),
        sa.Column("credential_ref", sa.String(length=512), nullable=False),
        sa.Column("permission", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("granted_by", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_platform_plugin_credential_grants_plugin_id",
        "platform_plugin_credential_grants",
        ["plugin_id"],
    )
    op.create_index(
        "ix_platform_plugin_credential_grant_lookup",
        "platform_plugin_credential_grants",
        ["plugin_id", "credential_ref", "expires_at"],
    )

    op.create_table(
        "platform_plugin_backend_selections",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("scope_type", sa.String(length=16), nullable=False),
        sa.Column("scope_id", sa.String(length=255), nullable=False),
        sa.Column("capability_kind", sa.String(length=64), nullable=False),
        sa.Column("plugin_id", sa.String(length=255), nullable=False),
        sa.Column("capability_id", sa.String(length=255), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("revision > 0", name="ck_platform_plugin_backend_selection_revision"),
        sa.UniqueConstraint(
            "scope_type",
            "scope_id",
            "capability_kind",
            name="uq_platform_plugin_backend_selection_scope",
        ),
    )

    op.create_table(
        "platform_plugin_http_routes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("plugin_id", sa.String(length=255), nullable=False),
        sa.Column("method", sa.String(length=8), nullable=False),
        sa.Column("path", sa.String(length=512), nullable=False),
        sa.Column("permission", sa.String(length=191), nullable=False),
        sa.Column("authorization_mode", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("method", "path", name="uq_platform_plugin_http_route"),
        sa.CheckConstraint(
            "method IN ('GET', 'POST', 'PUT', 'PATCH', 'DELETE')",
            name="ck_platform_plugin_http_route_method",
        ),
        sa.CheckConstraint(
            "authorization_mode IN ('tenant_member', 'project_member', 'tenant_admin')",
            name="ck_platform_plugin_http_route_authorization",
        ),
        sa.CheckConstraint("revision > 0", name="ck_platform_plugin_http_route_revision"),
    )
    op.create_index(
        "ix_platform_plugin_http_routes_plugin_id",
        "platform_plugin_http_routes",
        ["plugin_id"],
    )

    op.create_table(
        "platform_plugin_quota_usage",
        sa.Column("plugin_id", sa.String(length=255), nullable=False),
        sa.Column("concurrent_calls", sa.Integer(), nullable=False),
        sa.Column(
            "window_started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("requests_in_window", sa.Integer(), nullable=False),
        sa.Column("output_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_bytes", sa.BigInteger(), nullable=False),
        sa.Column("usd_micros", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("plugin_id"),
        sa.CheckConstraint(
            "concurrent_calls >= 0 AND requests_in_window >= 0",
            name="ck_platform_plugin_quota_counts",
        ),
        sa.CheckConstraint(
            "output_bytes >= 0 AND storage_bytes >= 0 AND usd_micros >= 0",
            name="ck_platform_plugin_quota_bytes",
        ),
    )

    op.create_table(
        "platform_plugin_packages",
        sa.Column("plugin_id", sa.String(length=255), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("publisher", sa.String(length=255), nullable=False),
        sa.Column("artifact_digest", sa.String(length=64), nullable=False),
        sa.Column("signature", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("security_scan_status", sa.String(length=32), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.Column("revocation_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("plugin_id", "version"),
    )


def downgrade() -> None:
    """Remove Phase 4-6 plugin governance tables."""
    op.drop_table("platform_plugin_packages")
    op.drop_table("platform_plugin_quota_usage")
    op.drop_index(
        "ix_platform_plugin_http_routes_plugin_id",
        table_name="platform_plugin_http_routes",
    )
    op.drop_table("platform_plugin_http_routes")
    op.drop_table("platform_plugin_backend_selections")
    op.drop_index(
        "ix_platform_plugin_credential_grant_lookup",
        table_name="platform_plugin_credential_grants",
    )
    op.drop_index(
        "ix_platform_plugin_credential_grants_plugin_id",
        table_name="platform_plugin_credential_grants",
    )
    op.drop_table("platform_plugin_credential_grants")
    op.drop_index(
        "ix_platform_plugin_permission_scope",
        table_name="platform_plugin_permissions",
    )
    op.drop_index(
        "ix_platform_plugin_permissions_plugin_id",
        table_name="platform_plugin_permissions",
    )
    op.drop_table("platform_plugin_permissions")
