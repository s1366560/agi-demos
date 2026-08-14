"""Add durable Workspace Autonomy judgment claims and attentions.

Revision ID: a72d9c31e5bf
Revises: f184bcdba7ea
Create Date: 2026-08-14
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "a72d9c31e5bf"
down_revision: str | Sequence[str] | None = "f184bcdba7ea"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE_DDL: tuple[str, ...] = (
    """
    ALTER TABLE avernet.workspace_autonomy_ticks
        DROP CONSTRAINT ck_workspace_autonomy_ticks_reason
    """,
    """
    ALTER TABLE avernet.workspace_autonomy_ticks
        ADD CONSTRAINT ck_workspace_autonomy_ticks_reason
        CHECK (reason IN (
            'triggered', 'blocked_by_judge', 'escalated_by_judge',
            'no_open_root', 'no_active_agent', 'cooling_down'
        ))
    """,
    """
    ALTER TABLE avernet.workspace_judge_audits
        ADD CONSTRAINT uq_workspace_judge_audits_scope_id
        UNIQUE (tenant_id, project_id, workspace_id, audit_id)
    """,
    """
    CREATE TABLE avernet.workspace_autonomy_judgment_claims (
        claim_id VARCHAR(191) PRIMARY KEY,
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        workspace_id VARCHAR(128) NOT NULL,
        actor_id VARCHAR(256) NOT NULL,
        idempotency_key VARCHAR(256) NOT NULL,
        request_hash VARCHAR(64) NOT NULL,
        expected_revision BIGINT NOT NULL,
        status VARCHAR(24) NOT NULL DEFAULT 'processing',
        lease_owner VARCHAR(191),
        lease_expires_at_ms BIGINT,
        lease_generation BIGINT NOT NULL DEFAULT 1,
        audit_id VARCHAR(128),
        judgment_json JSONB,
        error_detail VARCHAR(256),
        created_at_ms BIGINT NOT NULL,
        updated_at_ms BIGINT NOT NULL,
        judged_at_ms BIGINT,
        applied_at_ms BIGINT,
        CONSTRAINT fk_workspace_autonomy_judgment_claim_profile
            FOREIGN KEY (tenant_id, project_id, workspace_id)
            REFERENCES avernet.workspace_profiles (tenant_id, project_id, workspace_id)
            ON DELETE CASCADE,
        CONSTRAINT fk_workspace_autonomy_judgment_claim_audit
            FOREIGN KEY (tenant_id, project_id, workspace_id, audit_id)
            REFERENCES avernet.workspace_judge_audits
                (tenant_id, project_id, workspace_id, audit_id)
            ON DELETE RESTRICT,
        CONSTRAINT uq_workspace_autonomy_judgment_claim_idempotency
            UNIQUE (workspace_id, actor_id, idempotency_key),
        CONSTRAINT ck_workspace_autonomy_judgment_claim_status
            CHECK (status IN ('processing', 'judged', 'applied', 'failed', 'superseded')),
        CONSTRAINT ck_workspace_autonomy_judgment_claim_revision
            CHECK (expected_revision >= 0),
        CONSTRAINT ck_workspace_autonomy_judgment_claim_generation
            CHECK (lease_generation > 0),
        CONSTRAINT ck_workspace_autonomy_judgment_claim_timestamps
            CHECK (
                created_at_ms >= 0
                AND updated_at_ms >= 0
                AND (lease_expires_at_ms IS NULL OR lease_expires_at_ms >= 0)
                AND (judged_at_ms IS NULL OR judged_at_ms >= 0)
                AND (applied_at_ms IS NULL OR applied_at_ms >= 0)
            ),
        CONSTRAINT ck_workspace_autonomy_judgment_claim_lease
            CHECK (
                (status = 'processing'
                    AND lease_owner IS NOT NULL
                    AND lease_expires_at_ms IS NOT NULL)
                OR (status <> 'processing'
                    AND lease_owner IS NULL
                    AND lease_expires_at_ms IS NULL)
            ),
        CONSTRAINT ck_workspace_autonomy_judgment_claim_snapshot
            CHECK (
                (status IN ('judged', 'applied')
                    AND audit_id IS NOT NULL
                    AND judgment_json IS NOT NULL)
                OR (status NOT IN ('judged', 'applied') AND judgment_json IS NULL)
            ),
        CONSTRAINT ck_workspace_autonomy_judgment_claim_applied
            CHECK (
                (status = 'applied' AND applied_at_ms IS NOT NULL)
                OR (status <> 'applied' AND applied_at_ms IS NULL)
            )
    )
    """,
    """
    CREATE INDEX ix_avn_workspace_autonomy_judgment_claim_lease
        ON avernet.workspace_autonomy_judgment_claims
            (status, lease_expires_at_ms, updated_at_ms, claim_id)
    """,
    """
    CREATE FUNCTION avernet.reject_workspace_autonomy_judgment_claim_snapshot_update()
    RETURNS trigger AS $$
    BEGIN
        IF ROW(
            NEW.tenant_id,
            NEW.project_id,
            NEW.workspace_id,
            NEW.actor_id,
            NEW.idempotency_key,
            NEW.request_hash,
            NEW.expected_revision,
            NEW.created_at_ms
        ) IS DISTINCT FROM ROW(
            OLD.tenant_id,
            OLD.project_id,
            OLD.workspace_id,
            OLD.actor_id,
            OLD.idempotency_key,
            OLD.request_hash,
            OLD.expected_revision,
            OLD.created_at_ms
        ) THEN
            RAISE EXCEPTION
                'workspace_autonomy_judgment_claims snapshot columns are immutable';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE TRIGGER trg_workspace_autonomy_judgment_claim_snapshot_immutable
    BEFORE UPDATE OF
        tenant_id,
        project_id,
        workspace_id,
        actor_id,
        idempotency_key,
        request_hash,
        expected_revision,
        created_at_ms
    ON avernet.workspace_autonomy_judgment_claims
    FOR EACH ROW
    EXECUTE FUNCTION avernet.reject_workspace_autonomy_judgment_claim_snapshot_update()
    """,
    """
    CREATE TABLE avernet.workspace_autonomy_bootstrap_outbox (
        bootstrap_id VARCHAR(191) PRIMARY KEY,
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        workspace_id VARCHAR(128) NOT NULL UNIQUE,
        actor_id VARCHAR(256) NOT NULL,
        objective_title VARCHAR(255) NOT NULL,
        objective_description TEXT,
        status VARCHAR(24) NOT NULL DEFAULT 'pending',
        attempt_count INTEGER NOT NULL DEFAULT 0,
        max_attempts INTEGER NOT NULL DEFAULT 8,
        next_attempt_at_ms BIGINT NOT NULL DEFAULT 0,
        lease_owner VARCHAR(191),
        lease_expires_at_ms BIGINT,
        lease_generation BIGINT NOT NULL DEFAULT 0,
        objective_id VARCHAR(128),
        root_task_id VARCHAR(128),
        last_error VARCHAR(128),
        created_at_ms BIGINT NOT NULL,
        completed_at_ms BIGINT,
        CONSTRAINT fk_workspace_autonomy_bootstrap_profile
            FOREIGN KEY (tenant_id, project_id, workspace_id)
            REFERENCES avernet.workspace_profiles (tenant_id, project_id, workspace_id)
            ON DELETE CASCADE,
        CONSTRAINT ck_workspace_autonomy_bootstrap_status
            CHECK (status IN ('pending', 'processing', 'completed', 'dead_letter')),
        CONSTRAINT ck_workspace_autonomy_bootstrap_title
            CHECK (length(trim(objective_title)) > 0),
        CONSTRAINT ck_workspace_autonomy_bootstrap_attempts
            CHECK (
                attempt_count >= 0
                AND max_attempts > 0
                AND attempt_count <= max_attempts
            ),
        CONSTRAINT ck_workspace_autonomy_bootstrap_timestamps
            CHECK (
                next_attempt_at_ms >= 0
                AND lease_generation >= 0
                AND created_at_ms >= 0
                AND (lease_expires_at_ms IS NULL OR lease_expires_at_ms >= 0)
                AND (completed_at_ms IS NULL OR completed_at_ms >= 0)
            ),
        CONSTRAINT ck_workspace_autonomy_bootstrap_lease
            CHECK (
                (status = 'processing'
                    AND lease_owner IS NOT NULL
                    AND lease_expires_at_ms IS NOT NULL)
                OR (status <> 'processing'
                    AND lease_owner IS NULL
                    AND lease_expires_at_ms IS NULL)
            ),
        CONSTRAINT ck_workspace_autonomy_bootstrap_completion
            CHECK (
                (status = 'completed'
                    AND objective_id IS NOT NULL
                    AND root_task_id IS NOT NULL
                    AND completed_at_ms IS NOT NULL)
                OR (status <> 'completed' AND completed_at_ms IS NULL)
            )
    )
    """,
    """
    CREATE INDEX ix_avn_workspace_autonomy_bootstrap_due
        ON avernet.workspace_autonomy_bootstrap_outbox
            (status, next_attempt_at_ms, lease_expires_at_ms, created_at_ms, bootstrap_id)
    """,
    """
    CREATE FUNCTION avernet.reject_workspace_autonomy_bootstrap_snapshot_update()
    RETURNS trigger AS $$
    BEGIN
        IF ROW(
            NEW.tenant_id,
            NEW.project_id,
            NEW.workspace_id,
            NEW.actor_id,
            NEW.objective_title,
            NEW.objective_description,
            NEW.created_at_ms
        ) IS DISTINCT FROM ROW(
            OLD.tenant_id,
            OLD.project_id,
            OLD.workspace_id,
            OLD.actor_id,
            OLD.objective_title,
            OLD.objective_description,
            OLD.created_at_ms
        ) THEN
            RAISE EXCEPTION
                'workspace_autonomy_bootstrap_outbox snapshot columns are immutable';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE TRIGGER trg_workspace_autonomy_bootstrap_snapshot_immutable
    BEFORE UPDATE OF
        tenant_id,
        project_id,
        workspace_id,
        actor_id,
        objective_title,
        objective_description,
        created_at_ms
    ON avernet.workspace_autonomy_bootstrap_outbox
    FOR EACH ROW
    EXECUTE FUNCTION avernet.reject_workspace_autonomy_bootstrap_snapshot_update()
    """,
    """
    CREATE TABLE avernet.workspace_autonomy_attentions (
        attention_id VARCHAR(384) PRIMARY KEY,
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        workspace_id VARCHAR(128) NOT NULL,
        root_task_id VARCHAR(128),
        source_kind VARCHAR(32) NOT NULL,
        source_id VARCHAR(191) NOT NULL,
        reason TEXT NOT NULL,
        status VARCHAR(24) NOT NULL DEFAULT 'open',
        created_at_ms BIGINT NOT NULL,
        resolved_at_ms BIGINT,
        resolved_by_actor_id VARCHAR(256),
        CONSTRAINT fk_workspace_autonomy_attention_profile
            FOREIGN KEY (tenant_id, project_id, workspace_id)
            REFERENCES avernet.workspace_profiles (tenant_id, project_id, workspace_id)
            ON DELETE CASCADE,
        CONSTRAINT fk_workspace_autonomy_attention_root_task
            FOREIGN KEY (tenant_id, project_id, workspace_id, root_task_id)
            REFERENCES avernet.workspace_tasks (tenant_id, project_id, workspace_id, task_id)
            ON DELETE CASCADE,
        CONSTRAINT uq_workspace_autonomy_attention_source
            UNIQUE (source_kind, source_id),
        CONSTRAINT ck_workspace_autonomy_attention_source_kind
            CHECK (source_kind IN (
                'judge_block', 'judge_escalate', 'progression_dead_letter',
                'bootstrap_dead_letter', 'task_dispatch_dead_letter'
            )),
        CONSTRAINT ck_workspace_autonomy_attention_root_scope
            CHECK (
                (source_kind = 'bootstrap_dead_letter' AND root_task_id IS NULL)
                OR (source_kind IN (
                    'judge_block', 'judge_escalate', 'progression_dead_letter',
                    'task_dispatch_dead_letter'
                ) AND root_task_id IS NOT NULL)
            ),
        CONSTRAINT ck_workspace_autonomy_attention_status
            CHECK (status IN ('open', 'resolved')),
        CONSTRAINT ck_workspace_autonomy_attention_reason
            CHECK (length(trim(reason)) > 0),
        CONSTRAINT ck_workspace_autonomy_attention_timestamps
            CHECK (created_at_ms >= 0 AND (resolved_at_ms IS NULL OR resolved_at_ms >= 0)),
        CONSTRAINT ck_workspace_autonomy_attention_resolution
            CHECK (
                (status = 'open'
                    AND resolved_at_ms IS NULL
                    AND resolved_by_actor_id IS NULL)
                OR (status = 'resolved'
                    AND resolved_at_ms IS NOT NULL
                    AND resolved_by_actor_id IS NOT NULL)
            )
    )
    """,
    """
    CREATE INDEX ix_avn_workspace_autonomy_attention_open
        ON avernet.workspace_autonomy_attentions
            (tenant_id, project_id, workspace_id, root_task_id, status, created_at_ms)
    """,
    """
    CREATE OR REPLACE FUNCTION avernet.create_workspace_autonomy_dead_letter_attention()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    BEGIN
        IF NEW.status = 'dead_letter' AND OLD.status <> 'dead_letter' THEN
            INSERT INTO avernet.workspace_autonomy_attentions (
                attention_id, tenant_id, project_id, workspace_id, root_task_id,
                source_kind, source_id, reason, status, created_at_ms
            ) VALUES (
                'progression:' || NEW.progression_id,
                NEW.tenant_id,
                NEW.project_id,
                NEW.workspace_id,
                NEW.root_task_id,
                'progression_dead_letter',
                NEW.progression_id,
                COALESCE(
                    NEW.last_error,
                    'autonomy progression exhausted its retry budget'
                ),
                'open',
                floor(extract(epoch FROM clock_timestamp()) * 1000)::BIGINT
            )
            ON CONFLICT (source_kind, source_id) DO UPDATE SET
                reason = EXCLUDED.reason,
                status = 'open',
                created_at_ms = EXCLUDED.created_at_ms,
                resolved_at_ms = NULL,
                resolved_by_actor_id = NULL;
        END IF;
        RETURN NEW;
    END
    $$
    """,
    """
    CREATE TRIGGER trg_avn_workspace_autonomy_progression_attention
    AFTER UPDATE OF status ON avernet.workspace_autonomy_progression_outbox
    FOR EACH ROW
    EXECUTE FUNCTION avernet.create_workspace_autonomy_dead_letter_attention()
    """,
    """
    CREATE OR REPLACE FUNCTION avernet.create_workspace_autonomy_bootstrap_attention()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    BEGIN
        IF NEW.status = 'dead_letter' AND OLD.status <> 'dead_letter' THEN
            INSERT INTO avernet.workspace_autonomy_attentions (
                attention_id, tenant_id, project_id, workspace_id, root_task_id,
                source_kind, source_id, reason, status, created_at_ms
            ) VALUES (
                'bootstrap:' || NEW.bootstrap_id,
                NEW.tenant_id,
                NEW.project_id,
                NEW.workspace_id,
                NULL,
                'bootstrap_dead_letter',
                NEW.bootstrap_id,
                COALESCE(
                    NEW.last_error,
                    'autonomy bootstrap exhausted its retry budget'
                ),
                'open',
                floor(extract(epoch FROM clock_timestamp()) * 1000)::BIGINT
            )
            ON CONFLICT (source_kind, source_id) DO UPDATE SET
                reason = EXCLUDED.reason,
                status = 'open',
                created_at_ms = EXCLUDED.created_at_ms,
                resolved_at_ms = NULL,
                resolved_by_actor_id = NULL;
        END IF;
        RETURN NEW;
    END
    $$
    """,
    """
    CREATE TRIGGER trg_avn_workspace_autonomy_bootstrap_attention
    AFTER UPDATE OF status ON avernet.workspace_autonomy_bootstrap_outbox
    FOR EACH ROW
    EXECUTE FUNCTION avernet.create_workspace_autonomy_bootstrap_attention()
    """,
    """
    CREATE OR REPLACE FUNCTION avernet.create_workspace_task_dispatch_attention()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    DECLARE
        resolved_root_task_id VARCHAR(128);
    BEGIN
        IF NEW.status = 'dead_letter' AND OLD.status <> 'dead_letter' THEN
            SELECT root.task_id
            INTO resolved_root_task_id
            FROM avernet.workspace_tasks execution
            JOIN avernet.workspace_tasks root
              ON root.tenant_id = execution.tenant_id
             AND root.project_id = execution.project_id
             AND root.workspace_id = execution.workspace_id
             AND root.task_id = execution.metadata_json->>'root_goal_task_id'
             AND root.metadata_json->>'task_role' = 'goal_root'
            WHERE execution.tenant_id = NEW.tenant_id
              AND execution.project_id = NEW.project_id
              AND execution.workspace_id = NEW.workspace_id
              AND execution.task_id = NEW.task_id
              AND execution.metadata_json->>'task_role' = 'execution_task'
            LIMIT 1;

            INSERT INTO avernet.workspace_autonomy_attentions (
                attention_id, tenant_id, project_id, workspace_id, root_task_id,
                source_kind, source_id, reason, status, created_at_ms
            ) VALUES (
                'task-dispatch:' || NEW.dispatch_id,
                NEW.tenant_id,
                NEW.project_id,
                NEW.workspace_id,
                resolved_root_task_id,
                'task_dispatch_dead_letter',
                NEW.dispatch_id,
                COALESCE(NEW.last_error, 'task dispatch exhausted its retry budget'),
                'open',
                floor(extract(epoch FROM clock_timestamp()) * 1000)::BIGINT
            )
            ON CONFLICT (source_kind, source_id) DO UPDATE SET
                root_task_id = EXCLUDED.root_task_id,
                reason = EXCLUDED.reason,
                status = 'open',
                created_at_ms = EXCLUDED.created_at_ms,
                resolved_at_ms = NULL,
                resolved_by_actor_id = NULL;
        END IF;
        RETURN NEW;
    END
    $$
    """,
    """
    CREATE TRIGGER trg_avn_workspace_task_dispatch_attention
    AFTER UPDATE OF status ON avernet.workspace_task_dispatch_outbox
    FOR EACH ROW
    EXECUTE FUNCTION avernet.create_workspace_task_dispatch_attention()
    """,
    """
    INSERT INTO avernet.workspace_autonomy_attentions (
        attention_id, tenant_id, project_id, workspace_id, root_task_id,
        source_kind, source_id, reason, status, created_at_ms
    )
    SELECT
        'progression:' || progression_id,
        tenant_id,
        project_id,
        workspace_id,
        root_task_id,
        'progression_dead_letter',
        progression_id,
        COALESCE(last_error, 'autonomy progression exhausted its retry budget'),
        'open',
        created_at_ms
    FROM avernet.workspace_autonomy_progression_outbox
    WHERE status = 'dead_letter'
    ON CONFLICT (source_kind, source_id) DO NOTHING
    """,
    """
    INSERT INTO avernet.workspace_autonomy_attentions (
        attention_id, tenant_id, project_id, workspace_id, root_task_id,
        source_kind, source_id, reason, status, created_at_ms
    )
    SELECT
        'bootstrap:' || bootstrap_id,
        tenant_id,
        project_id,
        workspace_id,
        NULL,
        'bootstrap_dead_letter',
        bootstrap_id,
        COALESCE(last_error, 'autonomy bootstrap exhausted its retry budget'),
        'open',
        created_at_ms
    FROM avernet.workspace_autonomy_bootstrap_outbox
    WHERE status = 'dead_letter'
    ON CONFLICT (source_kind, source_id) DO NOTHING
    """,
    """
    INSERT INTO avernet.workspace_autonomy_attentions (
        attention_id, tenant_id, project_id, workspace_id, root_task_id,
        source_kind, source_id, reason, status, created_at_ms
    )
    SELECT
        'task-dispatch:' || dispatch.dispatch_id,
        dispatch.tenant_id,
        dispatch.project_id,
        dispatch.workspace_id,
        (
            SELECT root.task_id
            FROM avernet.workspace_tasks execution
            JOIN avernet.workspace_tasks root
              ON root.tenant_id = execution.tenant_id
             AND root.project_id = execution.project_id
             AND root.workspace_id = execution.workspace_id
             AND root.task_id = execution.metadata_json->>'root_goal_task_id'
             AND root.metadata_json->>'task_role' = 'goal_root'
            WHERE execution.tenant_id = dispatch.tenant_id
              AND execution.project_id = dispatch.project_id
              AND execution.workspace_id = dispatch.workspace_id
              AND execution.task_id = dispatch.task_id
              AND execution.metadata_json->>'task_role' = 'execution_task'
            LIMIT 1
        ),
        'task_dispatch_dead_letter',
        dispatch.dispatch_id,
        COALESCE(dispatch.last_error, 'task dispatch exhausted its retry budget'),
        'open',
        dispatch.created_at_ms
    FROM avernet.workspace_task_dispatch_outbox dispatch
    WHERE dispatch.status = 'dead_letter'
    ON CONFLICT (source_kind, source_id) DO NOTHING
    """,
    """
    ALTER TABLE avernet.workspace_agent_runtime_correlations
        ADD COLUMN provider_event_hash VARCHAR(64),
        ADD COLUMN provider_event_ingested_at TIMESTAMPTZ,
        ADD CONSTRAINT ck_workspace_runtime_provider_event_ingest
            CHECK (
                (provider_event_hash IS NULL AND provider_event_ingested_at IS NULL)
                OR provider_event_hash ~ '^[0-9a-f]{64}$'
            )
    """,
    """
    CREATE INDEX ix_avn_workspace_runtime_provider_event_ingest
        ON avernet.workspace_agent_runtime_correlations
            (provider_run_id, provider_event_hash, provider_event_ingested_at)
    """,
    "REVOKE ALL ON TABLE avernet.workspace_autonomy_judgment_claims FROM PUBLIC",
    "REVOKE ALL ON TABLE avernet.workspace_autonomy_bootstrap_outbox FROM PUBLIC",
    "REVOKE ALL ON TABLE avernet.workspace_autonomy_attentions FROM PUBLIC",
)

_DOWNGRADE_DDL: tuple[str, ...] = (
    """
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM avernet.workspace_autonomy_judgment_claims)
            OR EXISTS (SELECT 1 FROM avernet.workspace_autonomy_bootstrap_outbox)
            OR EXISTS (SELECT 1 FROM avernet.workspace_autonomy_attentions)
        THEN
            RAISE EXCEPTION
                'Workspace Autonomy judgment claims or attentions contain durable data';
        END IF;
        IF EXISTS (
            SELECT 1 FROM avernet.workspace_autonomy_ticks
            WHERE reason = 'no_active_agent'
        ) THEN
            RAISE EXCEPTION
                'Workspace Autonomy ticks contain the v5 no_active_agent reason';
        END IF;
        IF EXISTS (
            SELECT 1 FROM avernet.workspace_agent_runtime_correlations
            WHERE provider_event_hash IS NOT NULL
               OR provider_event_ingested_at IS NOT NULL
        ) THEN
            RAISE EXCEPTION
                'Workspace Runtime correlations contain durable Provider ingest markers';
        END IF;
    END
    $$
    """,
    """
    DROP TRIGGER IF EXISTS trg_avn_workspace_task_dispatch_attention
        ON avernet.workspace_task_dispatch_outbox
    """,
    "DROP INDEX IF EXISTS avernet.ix_avn_workspace_runtime_provider_event_ingest",
    """
    ALTER TABLE avernet.workspace_agent_runtime_correlations
        DROP CONSTRAINT IF EXISTS ck_workspace_runtime_provider_event_ingest,
        DROP COLUMN IF EXISTS provider_event_ingested_at,
        DROP COLUMN IF EXISTS provider_event_hash
    """,
    """
    DROP TRIGGER IF EXISTS trg_avn_workspace_autonomy_bootstrap_attention
        ON avernet.workspace_autonomy_bootstrap_outbox
    """,
    """
    DROP TRIGGER IF EXISTS trg_avn_workspace_autonomy_progression_attention
        ON avernet.workspace_autonomy_progression_outbox
    """,
    """
    DROP TRIGGER IF EXISTS trg_workspace_autonomy_bootstrap_snapshot_immutable
        ON avernet.workspace_autonomy_bootstrap_outbox
    """,
    """
    DROP TRIGGER IF EXISTS trg_workspace_autonomy_judgment_claim_snapshot_immutable
        ON avernet.workspace_autonomy_judgment_claims
    """,
    "DROP FUNCTION IF EXISTS avernet.create_workspace_autonomy_bootstrap_attention()",
    "DROP FUNCTION IF EXISTS avernet.create_workspace_task_dispatch_attention()",
    "DROP FUNCTION IF EXISTS avernet.create_workspace_autonomy_dead_letter_attention()",
    "DROP FUNCTION avernet.reject_workspace_autonomy_bootstrap_snapshot_update()",
    "DROP FUNCTION avernet.reject_workspace_autonomy_judgment_claim_snapshot_update()",
    "DROP INDEX IF EXISTS avernet.ix_avn_workspace_autonomy_attention_open",
    "DROP INDEX IF EXISTS avernet.ix_avn_workspace_autonomy_bootstrap_due",
    "DROP INDEX IF EXISTS avernet.ix_avn_workspace_autonomy_judgment_claim_lease",
    "DROP TABLE avernet.workspace_autonomy_attentions",
    "DROP TABLE avernet.workspace_autonomy_bootstrap_outbox",
    "DROP TABLE avernet.workspace_autonomy_judgment_claims",
    """
    ALTER TABLE avernet.workspace_judge_audits
        DROP CONSTRAINT uq_workspace_judge_audits_scope_id
    """,
    """
    ALTER TABLE avernet.workspace_autonomy_ticks
        DROP CONSTRAINT ck_workspace_autonomy_ticks_reason
    """,
    """
    ALTER TABLE avernet.workspace_autonomy_ticks
        ADD CONSTRAINT ck_workspace_autonomy_ticks_reason
        CHECK (reason IN (
            'triggered', 'blocked_by_judge', 'escalated_by_judge',
            'no_open_root', 'cooling_down'
        ))
    """,
)


def _execute_all(statements: Sequence[str]) -> None:
    for statement in statements:
        op.execute(sa.text(statement))


def upgrade() -> None:
    _execute_all(_UPGRADE_DDL)


def downgrade() -> None:
    _execute_all(_DOWNGRADE_DDL)
