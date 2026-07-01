"""add pluggable graph and retrieval stores

Revision ID: b1039849ef6d
Revises: q6f7a8b9c0d1
Create Date: 2026-06-26 15:23:54.115155

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

from alembic import op

revision: str = "b1039849ef6d"
down_revision: str | Sequence[str] | None = "q6f7a8b9c0d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _inspector() -> Inspector:
    return sa.inspect(op.get_bind())


def _has_table(table_name: str) -> bool:
    return _inspector().has_table(table_name)


def _has_column(table_name: str, column_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return any(column["name"] == column_name for column in _inspector().get_columns(table_name))


def _has_index(table_name: str, index_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return any(index["name"] == index_name for index in _inspector().get_indexes(table_name))


def upgrade() -> None:
    """Upgrade schema."""
    if not _has_table("graph_stores"):
        op.create_table(
            "graph_stores",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("engine_type", sa.String(length=50), nullable=False),
            sa.Column("connection_config_encrypted", sa.Text(), nullable=True),
            sa.Column("index_config", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(length=50), nullable=False),
            sa.Column("health_status", sa.String(length=50), nullable=True),
            sa.Column("last_health_check", sa.DateTime(timezone=True), nullable=True),
            sa.Column("detected_version", sa.String(length=100), nullable=True),
            sa.Column("created_by", sa.String(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tenant_id", "name", name="uq_graph_stores_tenant_name"),
        )
    if not _has_index("graph_stores", "ix_graph_stores_tenant_engine"):
        op.create_index(
            "ix_graph_stores_tenant_engine",
            "graph_stores",
            ["tenant_id", "engine_type"],
            unique=False,
        )
    if not _has_index("graph_stores", "ix_graph_stores_tenant_status"):
        op.create_index("ix_graph_stores_tenant_status", "graph_stores", ["tenant_id", "status"])
    if not _has_index("graph_stores", op.f("ix_graph_stores_tenant_id")):
        op.create_index(op.f("ix_graph_stores_tenant_id"), "graph_stores", ["tenant_id"])

    if not _has_table("retrieval_stores"):
        op.create_table(
            "retrieval_stores",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("engine_type", sa.String(length=50), nullable=False),
            sa.Column("connection_config_encrypted", sa.Text(), nullable=True),
            sa.Column("index_config", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(length=50), nullable=False),
            sa.Column("health_status", sa.String(length=50), nullable=True),
            sa.Column("last_health_check", sa.DateTime(timezone=True), nullable=True),
            sa.Column("detected_version", sa.String(length=100), nullable=True),
            sa.Column("created_by", sa.String(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tenant_id", "name", name="uq_retrieval_stores_tenant_name"),
        )
    if not _has_index("retrieval_stores", "ix_retrieval_stores_tenant_engine"):
        op.create_index(
            "ix_retrieval_stores_tenant_engine",
            "retrieval_stores",
            ["tenant_id", "engine_type"],
            unique=False,
        )
    if not _has_index("retrieval_stores", "ix_retrieval_stores_tenant_status"):
        op.create_index(
            "ix_retrieval_stores_tenant_status",
            "retrieval_stores",
            ["tenant_id", "status"],
        )
    if not _has_index("retrieval_stores", op.f("ix_retrieval_stores_tenant_id")):
        op.create_index(op.f("ix_retrieval_stores_tenant_id"), "retrieval_stores", ["tenant_id"])

    if not _has_column("projects", "graph_store_id"):
        op.add_column("projects", sa.Column("graph_store_id", sa.String(), nullable=True))
    if not _has_column("projects", "retrieval_store_id"):
        op.add_column("projects", sa.Column("retrieval_store_id", sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    if _has_column("projects", "retrieval_store_id"):
        op.drop_column("projects", "retrieval_store_id")
    if _has_column("projects", "graph_store_id"):
        op.drop_column("projects", "graph_store_id")

    if _has_table("retrieval_stores"):
        if _has_index("retrieval_stores", op.f("ix_retrieval_stores_tenant_id")):
            op.drop_index(op.f("ix_retrieval_stores_tenant_id"), table_name="retrieval_stores")
        if _has_index("retrieval_stores", "ix_retrieval_stores_tenant_status"):
            op.drop_index("ix_retrieval_stores_tenant_status", table_name="retrieval_stores")
        if _has_index("retrieval_stores", "ix_retrieval_stores_tenant_engine"):
            op.drop_index("ix_retrieval_stores_tenant_engine", table_name="retrieval_stores")
        op.drop_table("retrieval_stores")

    if _has_table("graph_stores"):
        if _has_index("graph_stores", op.f("ix_graph_stores_tenant_id")):
            op.drop_index(op.f("ix_graph_stores_tenant_id"), table_name="graph_stores")
        if _has_index("graph_stores", "ix_graph_stores_tenant_status"):
            op.drop_index("ix_graph_stores_tenant_status", table_name="graph_stores")
        if _has_index("graph_stores", "ix_graph_stores_tenant_engine"):
            op.drop_index("ix_graph_stores_tenant_engine", table_name="graph_stores")
        op.drop_table("graph_stores")
