"""add mcp runtime metadata and lifecycle events

Revision ID: e1f2a3b4c5d6
Revises: c9e7a1b2d3f4
Create Date: 2026-02-20 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = "c9e7a1b2d3f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "mcp_servers",
        sa.Column("runtime_status", sa.String(length=30), nullable=False, server_default="unknown"),
    )
    op.add_column(
        "mcp_servers",
        sa.Column("runtime_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )

    op.add_column(
        "mcp_apps",
        sa.Column("lifecycle_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )

    op.create_table(
        "mcp_lifecycle_events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("server_id", sa.String(), nullable=True),
        sa.Column("app_id", sa.String(), nullable=True),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["app_id"], ["mcp_apps.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["server_id"], ["mcp_servers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_mcp_lifecycle_events_project_created",
        "mcp_lifecycle_events",
        ["project_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_mcp_lifecycle_events_server_created",
        "mcp_lifecycle_events",
        ["server_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_mcp_lifecycle_events_app_created",
        "mcp_lifecycle_events",
        ["app_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_mcp_lifecycle_events_tenant_id",
        "mcp_lifecycle_events",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_mcp_lifecycle_events_event_type",
        "mcp_lifecycle_events",
        ["event_type"],
        unique=False,
    )
    op.create_index(
        "ix_mcp_lifecycle_events_status",
        "mcp_lifecycle_events",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_mcp_lifecycle_events_created_at",
        "mcp_lifecycle_events",
        ["created_at"],
        unique=False,
    )

    op.execute(
        """
        UPDATE mcp_servers
        SET runtime_status = CASE
            WHEN enabled = false THEN 'disabled'
            WHEN sync_error IS NOT NULL AND sync_error != '' THEN 'error'
            WHEN last_sync_at IS NOT NULL THEN 'running'
            ELSE 'unknown'
        END
        """
    )
    op.execute(
        """
        UPDATE mcp_servers
        SET runtime_metadata = json_build_object(
            'backfilled_at', NOW()::text,
            'enabled', enabled,
            'last_sync_at', COALESCE(last_sync_at::text, ''),
            'sync_error', COALESCE(sync_error, '')
        )
        """
    )
    op.execute(
        """
        UPDATE mcp_apps
        SET lifecycle_metadata = json_build_object(
            'backfilled_at', NOW()::text,
            'status', status,
            'has_resource', CASE WHEN resource_html IS NOT NULL AND resource_html != '' THEN true ELSE false END
        )
        """
    )


def downgrade() -> None:
    op.drop_index("ix_mcp_lifecycle_events_created_at", table_name="mcp_lifecycle_events")
    op.drop_index("ix_mcp_lifecycle_events_status", table_name="mcp_lifecycle_events")
    op.drop_index("ix_mcp_lifecycle_events_event_type", table_name="mcp_lifecycle_events")
    op.drop_index("ix_mcp_lifecycle_events_tenant_id", table_name="mcp_lifecycle_events")
    op.drop_index("ix_mcp_lifecycle_events_app_created", table_name="mcp_lifecycle_events")
    op.drop_index("ix_mcp_lifecycle_events_server_created", table_name="mcp_lifecycle_events")
    op.drop_index("ix_mcp_lifecycle_events_project_created", table_name="mcp_lifecycle_events")
    op.drop_table("mcp_lifecycle_events")

    op.drop_column("mcp_apps", "lifecycle_metadata")
    op.drop_column("mcp_servers", "runtime_metadata")
    op.drop_column("mcp_servers", "runtime_status")
