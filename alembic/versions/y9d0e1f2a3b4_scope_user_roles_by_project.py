"""scope user roles by project

Revision ID: y9d0e1f2a3b4
Revises: d9e0f1a2b3c4
Create Date: 2026-05-15 06:15:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "y9d0e1f2a3b4"
down_revision: str | Sequence[str] | None = "d9e0f1a2b3c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLE_NAME = "user_roles"
PROJECT_ID_FK = "fk_user_roles_project_id"


def _table_exists() -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return bool(inspector.has_table(TABLE_NAME))


def _column_names() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns(TABLE_NAME)}


def _index_names() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {index["name"] for index in inspector.get_indexes(TABLE_NAME)}


def _foreign_key_names() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {
        constraint["name"]
        for constraint in inspector.get_foreign_keys(TABLE_NAME)
        if constraint["name"]
    }


def upgrade() -> None:
    """Add optional project scope to RBAC user role assignments."""
    if not _table_exists():
        return

    if "project_id" not in _column_names():
        op.add_column(TABLE_NAME, sa.Column("project_id", sa.String(), nullable=True))

    if "ix_user_roles_project_id" not in _index_names():
        op.create_index(op.f("ix_user_roles_project_id"), TABLE_NAME, ["project_id"], unique=False)

    if PROJECT_ID_FK not in _foreign_key_names():
        op.create_foreign_key(PROJECT_ID_FK, TABLE_NAME, "projects", ["project_id"], ["id"])


def downgrade() -> None:
    """Remove project scope from RBAC user role assignments."""
    if not _table_exists():
        return

    if PROJECT_ID_FK in _foreign_key_names():
        op.drop_constraint(PROJECT_ID_FK, TABLE_NAME, type_="foreignkey")

    if "ix_user_roles_project_id" in _index_names():
        op.drop_index(op.f("ix_user_roles_project_id"), table_name=TABLE_NAME)

    if "project_id" in _column_names():
        op.drop_column(TABLE_NAME, "project_id")
