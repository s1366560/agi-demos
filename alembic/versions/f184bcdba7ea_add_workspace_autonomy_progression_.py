"""Add durable fenced Workspace Autonomy progression snapshots.

Revision ID: f184bcdba7ea
Revises: f0a1b2c3d4e6
Create Date: 2026-08-14
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "f184bcdba7ea"
down_revision: str | Sequence[str] | None = "f0a1b2c3d4e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE_DDL: tuple[str, ...] = (
    """
    ALTER TABLE avernet.workspace_autonomy_ticks
        ADD CONSTRAINT uq_workspace_autonomy_ticks_scope_id
        UNIQUE (tenant_id, project_id, workspace_id, tick_id)
    """,
    """
    ALTER TABLE avernet.workspace_agent_bindings
        ADD CONSTRAINT uq_workspace_agent_bindings_scope_id
        UNIQUE (tenant_id, project_id, workspace_id, binding_id)
    """,
    """
    CREATE TABLE avernet.workspace_autonomy_progression_outbox (
        progression_id VARCHAR(191) PRIMARY KEY,
        tick_id VARCHAR(128) NOT NULL UNIQUE,
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        workspace_id VARCHAR(128) NOT NULL,
        root_task_id VARCHAR(128) NOT NULL,
        actor_id VARCHAR(256) NOT NULL,
        judge_agent_id VARCHAR(256) NOT NULL,
        workspace_agent_binding_id VARCHAR(128) NOT NULL,
        task_title VARCHAR(255) NOT NULL,
        task_description TEXT NOT NULL,
        status VARCHAR(24) NOT NULL DEFAULT 'pending',
        attempt_count INTEGER NOT NULL DEFAULT 0,
        max_attempts INTEGER NOT NULL DEFAULT 8,
        next_attempt_at_ms BIGINT NOT NULL DEFAULT 0,
        lease_owner VARCHAR(191),
        lease_expires_at_ms BIGINT,
        lease_generation BIGINT NOT NULL DEFAULT 0,
        execution_task_id VARCHAR(128),
        last_error VARCHAR(128),
        created_at_ms BIGINT NOT NULL,
        completed_at_ms BIGINT,
        CONSTRAINT fk_workspace_autonomy_progression_tick
            FOREIGN KEY (tenant_id, project_id, workspace_id, tick_id)
            REFERENCES avernet.workspace_autonomy_ticks
                (tenant_id, project_id, workspace_id, tick_id)
            ON DELETE CASCADE,
        CONSTRAINT fk_workspace_autonomy_progression_profile
            FOREIGN KEY (tenant_id, project_id, workspace_id)
            REFERENCES avernet.workspace_profiles (tenant_id, project_id, workspace_id)
            ON DELETE CASCADE,
        CONSTRAINT fk_workspace_autonomy_progression_root_task
            FOREIGN KEY (tenant_id, project_id, workspace_id, root_task_id)
            REFERENCES avernet.workspace_tasks (tenant_id, project_id, workspace_id, task_id)
            ON DELETE RESTRICT,
        CONSTRAINT fk_workspace_autonomy_progression_binding
            FOREIGN KEY (tenant_id, project_id, workspace_id, workspace_agent_binding_id)
            REFERENCES avernet.workspace_agent_bindings
                (tenant_id, project_id, workspace_id, binding_id)
            ON DELETE RESTRICT,
        CONSTRAINT fk_workspace_autonomy_progression_execution_task
            FOREIGN KEY (tenant_id, project_id, workspace_id, execution_task_id)
            REFERENCES avernet.workspace_tasks (tenant_id, project_id, workspace_id, task_id)
            ON DELETE RESTRICT,
        CONSTRAINT ck_workspace_autonomy_progression_status
            CHECK (status IN ('pending', 'processing', 'completed', 'dead_letter')),
        CONSTRAINT ck_workspace_autonomy_progression_attempts
            CHECK (
                attempt_count >= 0
                AND max_attempts > 0
                AND attempt_count <= max_attempts
            ),
        CONSTRAINT ck_workspace_autonomy_progression_timestamps
            CHECK (
                next_attempt_at_ms >= 0
                AND created_at_ms >= 0
                AND lease_generation >= 0
                AND (lease_expires_at_ms IS NULL OR lease_expires_at_ms >= 0)
                AND (completed_at_ms IS NULL OR completed_at_ms >= 0)
            ),
        CONSTRAINT ck_workspace_autonomy_progression_lease
            CHECK (
                (status = 'processing'
                    AND lease_owner IS NOT NULL
                    AND lease_expires_at_ms IS NOT NULL)
                OR
                (status <> 'processing'
                    AND lease_owner IS NULL
                    AND lease_expires_at_ms IS NULL)
            ),
        CONSTRAINT ck_workspace_autonomy_progression_completion
            CHECK (
                (status = 'completed'
                    AND execution_task_id IS NOT NULL
                    AND completed_at_ms IS NOT NULL)
                OR
                (status <> 'completed' AND completed_at_ms IS NULL)
            )
    )
    """,
    """
    CREATE INDEX ix_avn_workspace_autonomy_progression_due
        ON avernet.workspace_autonomy_progression_outbox
            (status, next_attempt_at_ms, lease_expires_at_ms, created_at_ms, progression_id)
    """,
    """
    CREATE INDEX ix_avn_workspace_autonomy_progression_workspace
        ON avernet.workspace_autonomy_progression_outbox
            (workspace_id, created_at_ms, progression_id)
    """,
    """
    CREATE FUNCTION avernet.reject_workspace_autonomy_progression_snapshot_update()
    RETURNS trigger AS $$
    BEGIN
        IF ROW(
            NEW.tick_id,
            NEW.tenant_id,
            NEW.project_id,
            NEW.workspace_id,
            NEW.root_task_id,
            NEW.actor_id,
            NEW.judge_agent_id,
            NEW.workspace_agent_binding_id,
            NEW.task_title,
            NEW.task_description,
            NEW.created_at_ms
        ) IS DISTINCT FROM ROW(
            OLD.tick_id,
            OLD.tenant_id,
            OLD.project_id,
            OLD.workspace_id,
            OLD.root_task_id,
            OLD.actor_id,
            OLD.judge_agent_id,
            OLD.workspace_agent_binding_id,
            OLD.task_title,
            OLD.task_description,
            OLD.created_at_ms
        ) THEN
            RAISE EXCEPTION
                'workspace_autonomy_progression_outbox snapshot columns are immutable';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE TRIGGER trg_workspace_autonomy_progression_snapshot_immutable
    BEFORE UPDATE OF
        tick_id,
        tenant_id,
        project_id,
        workspace_id,
        root_task_id,
        actor_id,
        judge_agent_id,
        workspace_agent_binding_id,
        task_title,
        task_description,
        created_at_ms
    ON avernet.workspace_autonomy_progression_outbox
    FOR EACH ROW
    EXECUTE FUNCTION avernet.reject_workspace_autonomy_progression_snapshot_update()
    """,
    """
    REVOKE ALL ON TABLE avernet.workspace_autonomy_progression_outbox FROM PUBLIC
    """,
)

_DOWNGRADE_DDL: tuple[str, ...] = (
    """
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM avernet.workspace_autonomy_progression_outbox) THEN
            RAISE EXCEPTION
                'workspace_autonomy_progression_outbox contains durable progression data';
        END IF;
    END
    $$
    """,
    "DROP INDEX IF EXISTS avernet.ix_avn_workspace_autonomy_progression_workspace",
    "DROP INDEX IF EXISTS avernet.ix_avn_workspace_autonomy_progression_due",
    "DROP TABLE avernet.workspace_autonomy_progression_outbox",
    "DROP FUNCTION avernet.reject_workspace_autonomy_progression_snapshot_update()",
    """
    ALTER TABLE avernet.workspace_agent_bindings
        DROP CONSTRAINT uq_workspace_agent_bindings_scope_id
    """,
    """
    ALTER TABLE avernet.workspace_autonomy_ticks
        DROP CONSTRAINT uq_workspace_autonomy_ticks_scope_id
    """,
)


def _execute_all(statements: Sequence[str]) -> None:
    for statement in statements:
        op.execute(sa.text(statement))


def upgrade() -> None:
    _execute_all(_UPGRADE_DDL)


def downgrade() -> None:
    _execute_all(_DOWNGRADE_DDL)
