"""make mcp_apps server_id nullable

Agent-developed MCP Apps don't have a corresponding mcp_servers record.
Make server_id nullable and update unique constraint to use
(project_id, server_name, tool_name) instead.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-02-12 15:35:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop FK constraint so we can alter the column
    op.drop_constraint("mcp_apps_server_id_fkey", "mcp_apps", type_="foreignkey")
    # Make server_id nullable
    op.alter_column("mcp_apps", "server_id", existing_type=sa.String(), nullable=True)
    # Re-add FK as nullable
    op.create_foreign_key(
        "mcp_apps_server_id_fkey",
        "mcp_apps",
        "mcp_servers",
        ["server_id"],
        ["id"],
        ondelete="CASCADE",
    )
    # A failed DDL statement aborts PostgreSQL's migration transaction even if
    # Python catches it. Both known historical names are safe to drop explicitly.
    op.execute(sa.text("ALTER TABLE mcp_apps DROP CONSTRAINT IF EXISTS uq_mcp_app_server_tool"))
    op.execute(sa.text("ALTER TABLE mcp_apps DROP CONSTRAINT IF EXISTS uq_mcp_apps_server_tool"))
    # Add new unique constraint
    op.create_unique_constraint(
        "uq_mcp_app_project_server_tool",
        "mcp_apps",
        ["project_id", "server_name", "tool_name"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_mcp_app_project_server_tool", "mcp_apps", type_="unique")
    op.drop_constraint("mcp_apps_server_id_fkey", "mcp_apps", type_="foreignkey")
    op.alter_column("mcp_apps", "server_id", existing_type=sa.String(), nullable=False)
    op.create_foreign_key(
        "mcp_apps_server_id_fkey",
        "mcp_apps",
        "mcp_servers",
        ["server_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_mcp_app_server_tool",
        "mcp_apps",
        ["server_id", "tool_name"],
    )
