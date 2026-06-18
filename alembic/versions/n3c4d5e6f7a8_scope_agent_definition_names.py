"""Scope agent definition names by tenant and project.

Revision ID: n3c4d5e6f7a8
Revises: m2b3c4d5e6f7
Create Date: 2026-06-18
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "n3c4d5e6f7a8"
down_revision: str | Sequence[str] | None = "m2b3c4d5e6f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


AGENT_DEFINITIONS_TABLE = "agent_definitions"
OLD_AGENT_DEFINITION_NAME_CONSTRAINT = "agent_definitions_name_key"
TENANT_AGENT_NAME_INDEX = "uq_agent_definitions_tenant_name"
PROJECT_AGENT_NAME_INDEX = "uq_agent_definitions_tenant_project_name"


def upgrade() -> None:
    _drop_existing_name_unique()

    op.create_index(
        TENANT_AGENT_NAME_INDEX,
        AGENT_DEFINITIONS_TABLE,
        ["tenant_id", "name"],
        unique=True,
        postgresql_where=sa.text("project_id IS NULL"),
        sqlite_where=sa.text("project_id IS NULL"),
    )
    op.create_index(
        PROJECT_AGENT_NAME_INDEX,
        AGENT_DEFINITIONS_TABLE,
        ["tenant_id", "project_id", "name"],
        unique=True,
        postgresql_where=sa.text("project_id IS NOT NULL"),
        sqlite_where=sa.text("project_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(PROJECT_AGENT_NAME_INDEX, table_name=AGENT_DEFINITIONS_TABLE)
    op.drop_index(TENANT_AGENT_NAME_INDEX, table_name=AGENT_DEFINITIONS_TABLE)

    op.create_unique_constraint(
        OLD_AGENT_DEFINITION_NAME_CONSTRAINT,
        AGENT_DEFINITIONS_TABLE,
        ["name"],
    )


def _drop_existing_name_unique() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for constraint in inspector.get_unique_constraints(AGENT_DEFINITIONS_TABLE):
        if constraint.get("column_names") == ["name"]:
            op.drop_constraint(str(constraint["name"]), AGENT_DEFINITIONS_TABLE, type_="unique")
            return

    for index in inspector.get_indexes(AGENT_DEFINITIONS_TABLE):
        if index.get("unique") and index.get("column_names") == ["name"]:
            op.drop_index(str(index["name"]), table_name=AGENT_DEFINITIONS_TABLE)
            return

    raise RuntimeError("No single-column agent definition name uniqueness found")
