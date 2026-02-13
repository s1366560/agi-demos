"""add mcp_apps table

Revision ID: c3d4e5f6a7b8
Revises: b1c2d3e4f5a6
Create Date: 2026-02-12 12:12:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mcp_apps",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "server_id",
            sa.String(36),
            sa.ForeignKey("mcp_servers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("server_name", sa.String(255), nullable=False),
        sa.Column("tool_name", sa.String(255), nullable=False),
        sa.Column("resource_uri", sa.String(1024), nullable=False),
        sa.Column("resource_html", sa.Text(), nullable=True),
        sa.Column("resource_size_bytes", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(50), nullable=False, server_default="user_added"),
        sa.Column("status", sa.String(50), nullable=False, server_default="discovered"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("ui_permissions", sa.JSON(), nullable=True),
        sa.Column("ui_csp", sa.JSON(), nullable=True),
        sa.Column("ui_title", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=True, onupdate=sa.func.now()),
        sa.UniqueConstraint("server_id", "tool_name", name="uq_mcp_apps_server_tool"),
    )
    op.create_index("ix_mcp_apps_project_status", "mcp_apps", ["project_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_mcp_apps_project_status", table_name="mcp_apps")
    op.drop_table("mcp_apps")
