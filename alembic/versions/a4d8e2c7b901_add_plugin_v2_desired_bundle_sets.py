"""add plugin v2 desired bundle sets

Revision ID: a4d8e2c7b901
Revises: e91f4c7b2d60
Create Date: 2026-08-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a4d8e2c7b901"
down_revision: str | Sequence[str] | None = "e91f4c7b2d60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create append-only, scope-private protocol-v2 desired state."""
    op.create_table(
        "platform_plugin_v2_desired_bundle_sets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("scope_key", sa.String(length=64), nullable=False),
        sa.Column("scope_kind", sa.String(length=16), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=True),
        sa.Column("project_id", sa.String(length=255), nullable=True),
        sa.Column("session_id", sa.String(length=255), nullable=True),
        sa.Column("desired_set_id", sa.String(length=128), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("digest", sa.String(length=71), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("actor_id", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "scope_kind IN ('root', 'tenant', 'project', 'session')",
            name="ck_platform_plugin_v2_desired_scope_kind",
        ),
        sa.CheckConstraint("revision > 0", name="ck_platform_plugin_v2_desired_revision"),
        sa.CheckConstraint(
            "length(digest) = 71 AND substr(digest, 1, 7) = 'sha256:'",
            name="ck_platform_plugin_v2_desired_digest",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scope_key",
            "revision",
            name="uq_platform_plugin_v2_desired_scope_revision",
        ),
        sa.UniqueConstraint(
            "scope_key",
            "digest",
            name="uq_platform_plugin_v2_desired_scope_digest",
        ),
    )
    op.create_index(
        "ix_platform_plugin_v2_desired_scope_revision",
        "platform_plugin_v2_desired_bundle_sets",
        ["scope_key", "revision"],
    )
    op.create_index(
        "ix_platform_plugin_v2_desired_scope_path",
        "platform_plugin_v2_desired_bundle_sets",
        ["scope_kind", "tenant_id", "project_id", "session_id"],
    )


def downgrade() -> None:
    """Remove only protocol-v2 desired state."""
    op.drop_index(
        "ix_platform_plugin_v2_desired_scope_path",
        table_name="platform_plugin_v2_desired_bundle_sets",
    )
    op.drop_index(
        "ix_platform_plugin_v2_desired_scope_revision",
        table_name="platform_plugin_v2_desired_bundle_sets",
    )
    op.drop_table("platform_plugin_v2_desired_bundle_sets")
