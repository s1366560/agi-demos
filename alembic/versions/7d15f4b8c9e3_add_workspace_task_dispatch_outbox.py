"""Add durable fenced Workspace Task dispatch snapshots.

Revision ID: 7d15f4b8c9e3
Revises: 6c04e3a7b8d2
Create Date: 2026-08-11
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "7d15f4b8c9e3"
down_revision: str | Sequence[str] | None = "6c04e3a7b8d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE_DDL: tuple[str, ...] = (
    """
    CREATE TABLE avernet.workspace_task_dispatch_outbox (
        dispatch_id VARCHAR(191) PRIMARY KEY,
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        workspace_id VARCHAR(128) NOT NULL,
        task_id VARCHAR(128) NOT NULL,
        attempt_id VARCHAR(128),
        plan_id VARCHAR(128),
        plan_node_id VARCHAR(128),
        user_id VARCHAR(128) NOT NULL,
        agent_id VARCHAR(128) NOT NULL,
        workspace_agent_binding_id VARCHAR(128) NOT NULL,
        bot_uuid VARCHAR(256) NOT NULL,
        group_id VARCHAR(128) NOT NULL,
        conversation_id VARCHAR(128) NOT NULL,
        delivery_request_id VARCHAR(191) NOT NULL,
        task_title VARCHAR(255) NOT NULL,
        task_description TEXT,
        status VARCHAR(24) NOT NULL DEFAULT 'pending',
        attempt_count INTEGER NOT NULL DEFAULT 0,
        max_attempts INTEGER NOT NULL DEFAULT 8,
        next_attempt_at_ms BIGINT NOT NULL DEFAULT 0,
        lease_owner VARCHAR(191),
        lease_expires_at_ms BIGINT,
        lease_generation BIGINT NOT NULL DEFAULT 0,
        last_error VARCHAR(128),
        delivered_at_ms BIGINT,
        created_at_ms BIGINT NOT NULL,
        CONSTRAINT uq_workspace_task_dispatch_delivery UNIQUE (delivery_request_id),
        CONSTRAINT fk_workspace_task_dispatch_profile
            FOREIGN KEY (tenant_id, project_id, workspace_id)
            REFERENCES avernet.workspace_profiles (tenant_id, project_id, workspace_id)
            ON DELETE CASCADE,
        CONSTRAINT fk_workspace_task_dispatch_task
            FOREIGN KEY (tenant_id, project_id, workspace_id, task_id)
            REFERENCES avernet.workspace_tasks (tenant_id, project_id, workspace_id, task_id)
            ON DELETE CASCADE,
        CONSTRAINT ck_workspace_task_dispatch_status
            CHECK (status IN ('pending', 'delivering', 'delivered', 'dead_letter')),
        CONSTRAINT ck_workspace_task_dispatch_attempts
            CHECK (
                attempt_count >= 0
                AND max_attempts > 0
                AND attempt_count <= max_attempts
            ),
        CONSTRAINT ck_workspace_task_dispatch_timestamps
            CHECK (
                next_attempt_at_ms >= 0
                AND created_at_ms >= 0
                AND lease_generation >= 0
                AND (lease_expires_at_ms IS NULL OR lease_expires_at_ms >= 0)
                AND (delivered_at_ms IS NULL OR delivered_at_ms >= 0)
            ),
        CONSTRAINT ck_workspace_task_dispatch_lease
            CHECK (
                (status = 'delivering'
                    AND lease_owner IS NOT NULL
                    AND lease_expires_at_ms IS NOT NULL)
                OR
                (status <> 'delivering'
                    AND lease_owner IS NULL
                    AND lease_expires_at_ms IS NULL)
            ),
        CONSTRAINT ck_workspace_task_dispatch_delivered
            CHECK (
                (status = 'delivered' AND delivered_at_ms IS NOT NULL)
                OR
                (status <> 'delivered' AND delivered_at_ms IS NULL)
            )
    )
    """,
    """
    CREATE INDEX ix_avn_workspace_task_dispatch_ready
        ON avernet.workspace_task_dispatch_outbox
            (status, next_attempt_at_ms, created_at_ms, dispatch_id)
    """,
    """
    CREATE INDEX ix_avn_workspace_task_dispatch_lease
        ON avernet.workspace_task_dispatch_outbox (lease_expires_at_ms)
        WHERE status = 'delivering'
    """,
    """
    CREATE FUNCTION avernet.reject_workspace_task_dispatch_snapshot_update()
    RETURNS trigger AS $$
    BEGIN
        IF ROW(
            NEW.tenant_id,
            NEW.project_id,
            NEW.workspace_id,
            NEW.task_id,
            NEW.attempt_id,
            NEW.plan_id,
            NEW.plan_node_id,
            NEW.user_id,
            NEW.agent_id,
            NEW.workspace_agent_binding_id,
            NEW.bot_uuid,
            NEW.group_id,
            NEW.conversation_id,
            NEW.delivery_request_id,
            NEW.task_title,
            NEW.task_description,
            NEW.created_at_ms
        ) IS DISTINCT FROM ROW(
            OLD.tenant_id,
            OLD.project_id,
            OLD.workspace_id,
            OLD.task_id,
            OLD.attempt_id,
            OLD.plan_id,
            OLD.plan_node_id,
            OLD.user_id,
            OLD.agent_id,
            OLD.workspace_agent_binding_id,
            OLD.bot_uuid,
            OLD.group_id,
            OLD.conversation_id,
            OLD.delivery_request_id,
            OLD.task_title,
            OLD.task_description,
            OLD.created_at_ms
        ) THEN
            RAISE EXCEPTION
                'workspace_task_dispatch_outbox snapshot columns are immutable';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE TRIGGER trg_workspace_task_dispatch_snapshot_immutable
    BEFORE UPDATE OF
        tenant_id,
        project_id,
        workspace_id,
        task_id,
        attempt_id,
        plan_id,
        plan_node_id,
        user_id,
        agent_id,
        workspace_agent_binding_id,
        bot_uuid,
        group_id,
        conversation_id,
        delivery_request_id,
        task_title,
        task_description,
        created_at_ms
    ON avernet.workspace_task_dispatch_outbox
    FOR EACH ROW
    EXECUTE FUNCTION avernet.reject_workspace_task_dispatch_snapshot_update()
    """,
)

_DOWNGRADE_DDL: tuple[str, ...] = (
    """
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM avernet.workspace_task_dispatch_outbox) THEN
            RAISE EXCEPTION
                'workspace_task_dispatch_outbox contains durable dispatch data';
        END IF;
    END
    $$
    """,
    "DROP TABLE avernet.workspace_task_dispatch_outbox",
    "DROP FUNCTION avernet.reject_workspace_task_dispatch_snapshot_update()",
)


def _execute_all(statements: Sequence[str]) -> None:
    for statement in statements:
        op.execute(sa.text(statement))


def upgrade() -> None:
    _execute_all(_UPGRADE_DDL)


def downgrade() -> None:
    _execute_all(_DOWNGRADE_DDL)
