"""Backfill missing Workspace revision authorities.

Revision ID: 727ce1982b0f
Revises: c39e5a7b1d2f
Create Date: 2026-08-11
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "727ce1982b0f"
down_revision: str | Sequence[str] | None = "c39e5a7b1d2f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_BACKFILL_SQL = """
INSERT INTO avernet.workspace_authorities (
    workspace_id,
    tenant_id,
    project_id,
    revision,
    created_at,
    updated_at
)
SELECT
    profile.workspace_id,
    profile.tenant_id,
    profile.project_id,
    0,
    profile.created_at,
    profile.updated_at
FROM avernet.workspace_profiles profile
LEFT JOIN avernet.workspace_authorities authority
    ON authority.tenant_id = profile.tenant_id
    AND authority.project_id = profile.project_id
    AND authority.workspace_id = profile.workspace_id
WHERE authority.workspace_id IS NULL
ON CONFLICT (workspace_id) DO NOTHING
"""


def upgrade() -> None:
    """Give every migrated Workspace an explicit revision-zero authority."""
    op.execute(_BACKFILL_SQL)


def downgrade() -> None:
    """Retain authority rows because later writes make their origin indistinguishable."""
