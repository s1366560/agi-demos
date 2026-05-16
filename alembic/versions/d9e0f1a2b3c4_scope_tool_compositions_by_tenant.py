"""scope tool compositions by tenant

Revision ID: d9e0f1a2b3c4
Revises: c5680baba419
Create Date: 2026-05-15 05:40:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d9e0f1a2b3c4"
down_revision: str | Sequence[str] | None = "c5680baba419"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists() -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return bool(inspector.has_table("tool_compositions"))


def _column_names() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns("tool_compositions")}


def _index_names() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {index["name"] for index in inspector.get_indexes("tool_compositions")}


def _unique_constraint_names() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("tool_compositions")
        if constraint["name"]
    }


def upgrade() -> None:
    """Add tenant/project scope to tool compositions."""
    if not _table_exists():
        return

    columns = _column_names()
    if "tenant_id" not in columns:
        op.add_column(
            "tool_compositions",
            sa.Column("tenant_id", sa.String(), nullable=False, server_default="global"),
        )
    if "project_id" not in columns:
        op.add_column(
            "tool_compositions",
            sa.Column("project_id", sa.String(), nullable=True),
        )

    indexes = _index_names()
    if "ix_tool_compositions_tenant_id" not in indexes:
        op.create_index(
            op.f("ix_tool_compositions_tenant_id"),
            "tool_compositions",
            ["tenant_id"],
            unique=False,
        )
    if "ix_tool_compositions_project_id" not in indexes:
        op.create_index(
            op.f("ix_tool_compositions_project_id"),
            "tool_compositions",
            ["project_id"],
            unique=False,
        )

    if "ix_tool_compositions_name" in indexes:
        op.drop_index(op.f("ix_tool_compositions_name"), table_name="tool_compositions")
        op.create_index(
            op.f("ix_tool_compositions_name"),
            "tool_compositions",
            ["name"],
            unique=False,
        )

    unique_constraints = _unique_constraint_names()
    for constraint_name in ("tool_compositions_name_key", "uq_tool_compositions_name"):
        if constraint_name in unique_constraints:
            op.drop_constraint(constraint_name, "tool_compositions", type_="unique")

    if "uq_tool_compositions_tenant_name_project" not in unique_constraints:
        op.create_unique_constraint(
            "uq_tool_compositions_tenant_name_project",
            "tool_compositions",
            ["tenant_id", "name", "project_id"],
        )


def downgrade() -> None:
    """Remove tenant/project scope from tool compositions."""
    if not _table_exists():
        return

    unique_constraints = _unique_constraint_names()
    if "uq_tool_compositions_tenant_name_project" in unique_constraints:
        op.drop_constraint(
            "uq_tool_compositions_tenant_name_project",
            "tool_compositions",
            type_="unique",
        )

    indexes = _index_names()
    if "ix_tool_compositions_project_id" in indexes:
        op.drop_index(op.f("ix_tool_compositions_project_id"), table_name="tool_compositions")
    if "ix_tool_compositions_tenant_id" in indexes:
        op.drop_index(op.f("ix_tool_compositions_tenant_id"), table_name="tool_compositions")
    if "ix_tool_compositions_name" in indexes:
        op.drop_index(op.f("ix_tool_compositions_name"), table_name="tool_compositions")
        op.create_index(
            op.f("ix_tool_compositions_name"),
            "tool_compositions",
            ["name"],
            unique=True,
        )

    columns = _column_names()
    if "project_id" in columns:
        op.drop_column("tool_compositions", "project_id")
    if "tenant_id" in columns:
        op.drop_column("tool_compositions", "tenant_id")
