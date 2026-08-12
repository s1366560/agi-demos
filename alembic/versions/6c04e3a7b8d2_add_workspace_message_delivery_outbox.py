"""Add durable Workspace message delivery snapshots.

Revision ID: 6c04e3a7b8d2
Revises: 5b93d2f8eac1
Create Date: 2026-08-11
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "6c04e3a7b8d2"
down_revision: str | Sequence[str] | None = "5b93d2f8eac1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE_DDL: tuple[str, ...] = (
    """
    CREATE TABLE avernet.workspace_message_delivery_outbox (
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        workspace_id VARCHAR(128) NOT NULL,
        bcs_message_id VARCHAR(128) NOT NULL,
        group_id VARCHAR(128) NOT NULL,
        target_order BIGINT NOT NULL,
        agent_id VARCHAR(128) NOT NULL,
        bot_uuid VARCHAR(256) NOT NULL,
        display_name VARCHAR(255),
        status VARCHAR(24) NOT NULL DEFAULT 'pending',
        attempt_count INTEGER NOT NULL DEFAULT 0,
        max_attempts INTEGER NOT NULL DEFAULT 8,
        next_attempt_at_ms BIGINT NOT NULL,
        lease_owner VARCHAR(128),
        lease_expires_at_ms BIGINT,
        last_error TEXT,
        delivered_at_ms BIGINT,
        created_at_ms BIGINT NOT NULL,
        CONSTRAINT pk_workspace_message_delivery_outbox
            PRIMARY KEY (workspace_id, bcs_message_id, agent_id),
        CONSTRAINT uq_workspace_message_delivery_outbox_order
            UNIQUE (workspace_id, bcs_message_id, target_order),
        CONSTRAINT fk_workspace_message_delivery_outbox_profile
            FOREIGN KEY (tenant_id, project_id, workspace_id)
            REFERENCES avernet.workspace_profiles (tenant_id, project_id, workspace_id)
            ON DELETE CASCADE,
        CONSTRAINT fk_workspace_message_delivery_outbox_message
            FOREIGN KEY (bcs_message_id)
            REFERENCES avernet.bcs_messages (message_id)
            ON DELETE CASCADE,
        CONSTRAINT ck_workspace_message_delivery_outbox_status
            CHECK (status IN ('pending', 'delivering', 'delivered', 'dead_letter')),
        CONSTRAINT ck_workspace_message_delivery_outbox_attempts
            CHECK (
                attempt_count >= 0
                AND max_attempts > 0
                AND attempt_count <= max_attempts
            ),
        CONSTRAINT ck_workspace_message_delivery_outbox_timestamps
            CHECK (
                next_attempt_at_ms >= 0
                AND created_at_ms >= 0
                AND (lease_expires_at_ms IS NULL OR lease_expires_at_ms >= 0)
                AND (delivered_at_ms IS NULL OR delivered_at_ms >= 0)
            ),
        CONSTRAINT ck_workspace_message_delivery_outbox_lease
            CHECK (
                (status = 'delivering'
                    AND lease_owner IS NOT NULL
                    AND lease_expires_at_ms IS NOT NULL)
                OR
                (status <> 'delivering'
                    AND lease_owner IS NULL
                    AND lease_expires_at_ms IS NULL)
            ),
        CONSTRAINT ck_workspace_message_delivery_outbox_delivered
            CHECK (
                (status = 'delivered' AND delivered_at_ms IS NOT NULL)
                OR
                (status <> 'delivered' AND delivered_at_ms IS NULL)
            )
    )
    """,
    """
    CREATE INDEX ix_avn_workspace_message_delivery_ready
        ON avernet.workspace_message_delivery_outbox
            (status, next_attempt_at_ms, target_order)
    """,
    """
    CREATE INDEX ix_avn_workspace_message_delivery_lease
        ON avernet.workspace_message_delivery_outbox (lease_expires_at_ms)
        WHERE status = 'delivering'
    """,
    """
    CREATE FUNCTION avernet.reject_workspace_message_delivery_snapshot_update()
    RETURNS trigger AS $$
    BEGIN
        IF ROW(
            NEW.tenant_id,
            NEW.project_id,
            NEW.workspace_id,
            NEW.bcs_message_id,
            NEW.group_id,
            NEW.target_order,
            NEW.agent_id,
            NEW.bot_uuid,
            NEW.display_name,
            NEW.created_at_ms
        ) IS DISTINCT FROM ROW(
            OLD.tenant_id,
            OLD.project_id,
            OLD.workspace_id,
            OLD.bcs_message_id,
            OLD.group_id,
            OLD.target_order,
            OLD.agent_id,
            OLD.bot_uuid,
            OLD.display_name,
            OLD.created_at_ms
        ) THEN
            RAISE EXCEPTION
                'workspace_message_delivery_outbox snapshot columns are immutable';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE TRIGGER trg_workspace_message_delivery_snapshot_immutable
    BEFORE UPDATE OF
        tenant_id,
        project_id,
        workspace_id,
        bcs_message_id,
        group_id,
        target_order,
        agent_id,
        bot_uuid,
        display_name,
        created_at_ms
    ON avernet.workspace_message_delivery_outbox
    FOR EACH ROW
    EXECUTE FUNCTION avernet.reject_workspace_message_delivery_snapshot_update()
    """,
)

_DOWNGRADE_DDL: tuple[str, ...] = (
    """
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1
            FROM avernet.workspace_message_delivery_outbox
        ) THEN
            RAISE EXCEPTION
                'workspace_message_delivery_outbox contains durable delivery data';
        END IF;
    END
    $$
    """,
    "DROP TABLE avernet.workspace_message_delivery_outbox",
    "DROP FUNCTION avernet.reject_workspace_message_delivery_snapshot_update()",
)


def _execute_all(statements: Sequence[str]) -> None:
    for statement in statements:
        op.execute(sa.text(statement))


def upgrade() -> None:
    _execute_all(_UPGRADE_DDL)


def downgrade() -> None:
    _execute_all(_DOWNGRADE_DDL)
