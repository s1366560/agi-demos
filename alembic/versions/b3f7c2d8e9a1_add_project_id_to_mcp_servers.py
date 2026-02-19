"""add_project_id_to_mcp_servers

Revision ID: b3f7c2d8e9a1
Revises: 744edbe7a05b
Create Date: 2026-02-07

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3f7c2d8e9a1"
down_revision: Union[str, None] = "744edbe7a05b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_name = "mcp_servers"
    if table_name not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns(table_name)}
    if "project_id" not in columns:
        op.add_column(
            table_name,
            sa.Column("project_id", sa.String(), nullable=True),
        )
        inspector = sa.inspect(bind)

    index_name = op.f("ix_mcp_servers_project_id")
    indexes = {index["name"] for index in inspector.get_indexes(table_name)}
    if index_name not in indexes:
        op.create_index(index_name, table_name, ["project_id"], unique=False)

    foreign_keys = {fk["name"] for fk in inspector.get_foreign_keys(table_name)}
    if "fk_mcp_servers_project_id" not in foreign_keys:
        op.create_foreign_key(
            "fk_mcp_servers_project_id",
            table_name,
            "projects",
            ["project_id"],
            ["id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_name = "mcp_servers"
    if table_name not in inspector.get_table_names():
        return

    foreign_keys = {fk["name"] for fk in inspector.get_foreign_keys(table_name)}
    if "fk_mcp_servers_project_id" in foreign_keys:
        op.drop_constraint("fk_mcp_servers_project_id", table_name, type_="foreignkey")

    index_name = op.f("ix_mcp_servers_project_id")
    indexes = {index["name"] for index in inspector.get_indexes(table_name)}
    if index_name in indexes:
        op.drop_index(index_name, table_name=table_name)

    columns = {column["name"] for column in inspector.get_columns(table_name)}
    if "project_id" in columns:
        op.drop_column(table_name, "project_id")
