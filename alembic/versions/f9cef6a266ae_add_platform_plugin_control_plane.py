"""add platform plugin control plane

Revision ID: f9cef6a266ae
Revises: b84e2f6a9c31
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f9cef6a266ae"
down_revision: str | Sequence[str] | None = "b84e2f6a9c31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the platform plugin control-plane tables."""
    op.create_table(
        "platform_plugin_catalog",
        sa.Column("plugin_id", sa.String(length=255), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("runtime", sa.String(length=32), nullable=False),
        sa.Column("trust", sa.String(length=32), nullable=False),
        sa.Column("manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("plugin_id"),
    )
    op.create_table(
        "platform_plugin_desired_states",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("scope_type", sa.String(length=16), nullable=False),
        sa.Column("scope_id", sa.String(length=255), nullable=False),
        sa.Column("plugin_id", sa.String(length=255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("revision > 0", name="ck_platform_plugin_desired_revision"),
        sa.UniqueConstraint(
            "scope_type", "scope_id", "plugin_id", name="uq_platform_plugin_desired_scope_plugin"
        ),
    )
    op.create_index(
        "ix_platform_plugin_desired_scope",
        "platform_plugin_desired_states",
        ["scope_type", "scope_id"],
    )
    op.create_table(
        "platform_plugin_snapshots",
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("profile_id", sa.String(length=255), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("digest"),
        sa.UniqueConstraint("version"),
    )
    op.create_table(
        "platform_plugin_capability_audits",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("snapshot_digest", sa.String(length=64), nullable=False),
        sa.Column("plugin_id", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("capability_kind", sa.String(length=64), nullable=False),
        sa.Column("capability_id", sa.String(length=255), nullable=False),
        sa.Column("actor_id", sa.String(length=255), nullable=True),
        sa.Column("before_state", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("after_state", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_platform_plugin_capability_audits_plugin_id",
        "platform_plugin_capability_audits",
        ["plugin_id"],
    )
    op.create_index(
        "ix_platform_plugin_capability_audits_snapshot_digest",
        "platform_plugin_capability_audits",
        ["snapshot_digest"],
    )
    op.create_index(
        "ix_platform_plugin_capability_audit_snapshot_created",
        "platform_plugin_capability_audits",
        ["snapshot_digest", "created_at"],
    )
    op.create_table(
        "platform_plugin_apply_states",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("data_plane_id", sa.String(length=255), nullable=False),
        sa.Column("snapshot_digest", sa.String(length=64), nullable=False),
        sa.Column("requested_version", sa.BigInteger(), nullable=False),
        sa.Column("applied_version", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "last_ack_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "requested_version > 0 AND applied_version > 0",
            name="ck_platform_plugin_apply_versions",
        ),
        sa.CheckConstraint("status IN ('ack', 'nack')", name="ck_platform_plugin_apply_status"),
        sa.UniqueConstraint("data_plane_id"),
    )


def downgrade() -> None:
    """Remove the platform plugin control-plane tables."""
    op.drop_table("platform_plugin_apply_states")
    op.drop_index(
        "ix_platform_plugin_capability_audit_snapshot_created",
        table_name="platform_plugin_capability_audits",
    )
    op.drop_index(
        "ix_platform_plugin_capability_audits_snapshot_digest",
        table_name="platform_plugin_capability_audits",
    )
    op.drop_index(
        "ix_platform_plugin_capability_audits_plugin_id",
        table_name="platform_plugin_capability_audits",
    )
    op.drop_table("platform_plugin_capability_audits")
    op.drop_table("platform_plugin_snapshots")
    op.drop_index(
        "ix_platform_plugin_desired_scope",
        table_name="platform_plugin_desired_states",
    )
    op.drop_table("platform_plugin_desired_states")
    op.drop_table("platform_plugin_catalog")
