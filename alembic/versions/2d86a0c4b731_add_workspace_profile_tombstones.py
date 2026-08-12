"""Add durable Workspace profile tombstones.

Revision ID: 2d86a0c4b731
Revises: 1c75e9f4a286
Create Date: 2026-08-10

Workspace mutation receipts and outbox records reference the profile and must
survive a public delete. A tombstone closes the BCS Group and hides the
Workspace from active reads without cascading away its replay authority.
"""

from collections.abc import Iterable

import sqlalchemy as sa

from alembic import op

revision = "2d86a0c4b731"
down_revision = "1c75e9f4a286"
branch_labels = None
depends_on = None

_UPGRADE_DDL: tuple[str, ...] = (
    """
    ALTER TABLE avernet.workspace_profiles
        ADD COLUMN deleted_at TIMESTAMPTZ,
        ADD COLUMN deleted_by VARCHAR(128)
    """,
    """
    ALTER TABLE avernet.workspace_profiles
        ADD CONSTRAINT ck_workspace_profiles_tombstone_actor
        CHECK (deleted_at IS NULL OR deleted_by IS NOT NULL)
    """,
    """
    ALTER TABLE avernet.workspace_profiles
        DROP CONSTRAINT uq_workspace_profiles_project_name
    """,
    """
    CREATE UNIQUE INDEX uq_workspace_profiles_project_name_active
        ON avernet.workspace_profiles (tenant_id, project_id, name)
        WHERE deleted_at IS NULL
    """,
    """
    CREATE INDEX ix_avn_ws_profiles_active_scope
        ON avernet.workspace_profiles (tenant_id, project_id, created_at DESC)
        WHERE deleted_at IS NULL
    """,
)

_DOWNGRADE_DDL: tuple[str, ...] = (
    "DROP INDEX IF EXISTS avernet.ix_avn_ws_profiles_active_scope",
    "DROP INDEX IF EXISTS avernet.uq_workspace_profiles_project_name_active",
    """
    ALTER TABLE avernet.workspace_profiles
        DROP CONSTRAINT ck_workspace_profiles_tombstone_actor
    """,
    """
    ALTER TABLE avernet.workspace_profiles
        DROP COLUMN deleted_by,
        DROP COLUMN deleted_at
    """,
    """
    ALTER TABLE avernet.workspace_profiles
        ADD CONSTRAINT uq_workspace_profiles_project_name
        UNIQUE (tenant_id, project_id, name)
    """,
)


def _execute_all(statements: Iterable[str]) -> None:
    for statement in statements:
        op.execute(sa.text(statement))


def upgrade() -> None:
    _execute_all(_UPGRADE_DDL)


def downgrade() -> None:
    _execute_all(_DOWNGRADE_DDL)
