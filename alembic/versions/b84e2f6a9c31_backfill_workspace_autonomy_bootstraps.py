"""Backfill autonomous Workspace root bootstraps.

Revision ID: b84e2f6a9c31
Revises: a72d9c31e5bf
Create Date: 2026-08-14
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "b84e2f6a9c31"
down_revision: str | Sequence[str] | None = "a72d9c31e5bf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE_DDL = """
INSERT INTO avernet.workspace_autonomy_bootstrap_outbox (
    bootstrap_id,
    tenant_id,
    project_id,
    workspace_id,
    actor_id,
    objective_title,
    objective_description,
    created_at_ms
)
SELECT
    'autonomy-bootstrap-recovery:' || profile.workspace_id,
    profile.tenant_id,
    profile.project_id,
    profile.workspace_id,
    COALESCE(
        (
            SELECT member.user_id
            FROM avernet.workspace_members member
            WHERE member.tenant_id = profile.tenant_id
              AND member.project_id = profile.project_id
              AND member.workspace_id = profile.workspace_id
              AND member.role IN ('owner', 'admin', 'editor')
            ORDER BY CASE member.role
                WHEN 'owner' THEN 0
                WHEN 'admin' THEN 1
                ELSE 2
            END,
            member.created_at ASC,
            member.member_id ASC
            LIMIT 1
        ),
        profile.created_by
    ),
    CASE
        WHEN length(trim(profile.name)) > 0 THEN profile.name
        ELSE 'Autonomous workspace ' || profile.workspace_id
    END,
    profile.description,
    CAST(EXTRACT(EPOCH FROM CURRENT_TIMESTAMP) * 1000 AS BIGINT)
FROM avernet.workspace_profiles profile
WHERE profile.deleted_at IS NULL
  AND (
      profile.metadata_json ->> 'collaboration_mode' = 'autonomous'
      OR profile.metadata_json ->> 'agent_conversation_mode' = 'autonomous'
      OR profile.metadata_json -> 'legacy_desktop' ->> 'collaboration_mode' = 'autonomous'
  )
  AND NOT EXISTS (
      SELECT 1
      FROM avernet.workspace_tasks root
      WHERE root.tenant_id = profile.tenant_id
        AND root.project_id = profile.project_id
        AND root.workspace_id = profile.workspace_id
        AND root.metadata_json ->> 'task_role' = 'goal_root'
  )
ON CONFLICT (workspace_id) DO NOTHING
"""

_DOWNGRADE_GUARD = """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM avernet.workspace_autonomy_bootstrap_outbox
        WHERE bootstrap_id LIKE 'autonomy-bootstrap-recovery:%'
    ) THEN
        RAISE EXCEPTION
            'recovered Workspace Autonomy bootstrap rows contain durable data';
    END IF;
END
$$
"""


def upgrade() -> None:
    op.execute(_UPGRADE_DDL)


def downgrade() -> None:
    op.execute(_DOWNGRADE_GUARD)
