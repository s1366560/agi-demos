"""add_project_id_to_mcp_servers

Revision ID: b3f7c2d8e9a1
Revises: 744edbe7a05b
Create Date: 2026-02-07

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b3f7c2d8e9a1"
down_revision: Union[str, None] = "744edbe7a05b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add project_id column as nullable first (for existing data)
    op.add_column(
        "mcp_servers",
        sa.Column("project_id", sa.String(), nullable=True),
    )

    # Add index for project_id
    op.create_index(
        op.f("ix_mcp_servers_project_id"),
        "mcp_servers",
        ["project_id"],
        unique=False,
    )

    # Add foreign key constraint
    op.create_foreign_key(
        "fk_mcp_servers_project_id",
        "mcp_servers",
        "projects",
        ["project_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_mcp_servers_project_id", "mcp_servers", type_="foreignkey")
    op.drop_index(op.f("ix_mcp_servers_project_id"), table_name="mcp_servers")
    op.drop_column("mcp_servers", "project_id")
