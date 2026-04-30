"""add workspace deployment services

Revision ID: r2c3d4e5f6a7
Revises: q1b2c3d4e5f6
Create Date: 2026-04-30
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "r2c3d4e5f6a7"
down_revision: str | Sequence[str] | None = "q1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _has_column(table_name: str, column_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return any(
        column["name"] == column_name
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    )


def _has_index(table_name: str, index_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return any(
        index["name"] == index_name for index in sa.inspect(op.get_bind()).get_indexes(table_name)
    )


def upgrade() -> None:
    table_name = "workspace_deployments"
    if not _has_table(table_name):
        return
    for column_name, column in (
        ("service_id", sa.Column("service_id", sa.String(length=128), nullable=True)),
        ("service_name", sa.Column("service_name", sa.String(length=255), nullable=True)),
        ("service_url", sa.Column("service_url", sa.String(), nullable=True)),
        ("ws_preview_url", sa.Column("ws_preview_url", sa.String(), nullable=True)),
        (
            "required",
            sa.Column("required", sa.Boolean(), nullable=False, server_default="true"),
        ),
    ):
        if not _has_column(table_name, column_name):
            op.add_column(table_name, column)
    if not _has_index(table_name, "ix_workspace_deployments_plan_node_service"):
        op.create_index(
            "ix_workspace_deployments_plan_node_service",
            table_name,
            ["plan_id", "node_id", "service_id"],
        )


def downgrade() -> None:
    table_name = "workspace_deployments"
    if not _has_table(table_name):
        return
    if _has_index(table_name, "ix_workspace_deployments_plan_node_service"):
        op.drop_index("ix_workspace_deployments_plan_node_service", table_name=table_name)
    for column_name in ("required", "ws_preview_url", "service_url", "service_name", "service_id"):
        if _has_column(table_name, column_name):
            op.drop_column(table_name, column_name)
