"""add marketplace OCI artifact references

Revision ID: a7b8c9d0e1f2
Revises: f5a6b7c8d9e0
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: str | Sequence[str] | None = "f5a6b7c8d9e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Persist immutable OCI provenance needed to reinstall or audit packages."""
    op.add_column(
        "platform_plugin_packages",
        sa.Column("artifact_registry", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "platform_plugin_packages",
        sa.Column("artifact_repository", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "platform_plugin_packages",
        sa.Column("oci_manifest_digest", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "platform_plugin_packages",
        sa.Column(
            "install_status",
            sa.String(length=32),
            nullable=False,
            server_default="verified",
        ),
    )
    op.execute(
        "UPDATE platform_plugin_packages "
        "SET artifact_registry = 'inline://marketplace', "
        "artifact_repository = plugin_id, "
        "oci_manifest_digest = artifact_digest "
        "WHERE artifact_registry IS NULL"
    )
    op.alter_column(
        "platform_plugin_packages",
        "artifact_registry",
        existing_type=sa.String(length=512),
        nullable=False,
    )
    op.alter_column(
        "platform_plugin_packages",
        "artifact_repository",
        existing_type=sa.String(length=255),
        nullable=False,
    )
    op.alter_column(
        "platform_plugin_packages",
        "oci_manifest_digest",
        existing_type=sa.String(length=64),
        nullable=False,
    )


def downgrade() -> None:
    """Remove marketplace OCI artifact references."""
    op.drop_column("platform_plugin_packages", "install_status")
    op.drop_column("platform_plugin_packages", "oci_manifest_digest")
    op.drop_column("platform_plugin_packages", "artifact_repository")
    op.drop_column("platform_plugin_packages", "artifact_registry")
