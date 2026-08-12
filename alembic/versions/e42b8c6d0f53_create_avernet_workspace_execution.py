"""Create Avernet Workspace execution, outbox, and migration authority tables.

Revision ID: e42b8c6d0f53
Revises: a0b1c2d3e4f5
Create Date: 2026-08-10
"""

from collections.abc import Iterable

import sqlalchemy as sa

from alembic import op

revision = "e42b8c6d0f53"
down_revision = "a0b1c2d3e4f5"
branch_labels = None
depends_on = None

_TABLE_DDL: tuple[str, ...] = (
    """
    CREATE TABLE avernet.workspace_authorities (
        workspace_id VARCHAR(128) PRIMARY KEY,
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        revision BIGINT NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_workspace_authorities_profile
            FOREIGN KEY (tenant_id, project_id, workspace_id)
            REFERENCES avernet.workspace_profiles (tenant_id, project_id, workspace_id)
            ON DELETE CASCADE,
        CONSTRAINT ck_workspace_authorities_revision CHECK (revision >= 0)
    )
    """,
    """
    CREATE TABLE avernet.workspace_revision_credentials (
        credential_id VARCHAR(128) PRIMARY KEY,
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        workspace_id VARCHAR(128) NOT NULL,
        revision BIGINT NOT NULL,
        previous_revision BIGINT NOT NULL,
        actor_id VARCHAR(256) NOT NULL,
        mutation_hash CHAR(64) NOT NULL,
        credential_hash CHAR(64) NOT NULL,
        issued_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_workspace_revision_credentials_profile
            FOREIGN KEY (tenant_id, project_id, workspace_id)
            REFERENCES avernet.workspace_profiles (tenant_id, project_id, workspace_id)
            ON DELETE CASCADE,
        CONSTRAINT uq_workspace_revision_credentials_revision
            UNIQUE (workspace_id, revision),
        CONSTRAINT ck_workspace_revision_credentials_monotonic
            CHECK (revision > previous_revision AND previous_revision >= 0),
        CONSTRAINT ck_workspace_revision_credentials_hashes
            CHECK (
                mutation_hash ~ '^[0-9a-f]{64}$'
                AND credential_hash ~ '^[0-9a-f]{64}$'
            )
    )
    """,
    """
    CREATE TABLE avernet.workspace_mutation_receipts (
        receipt_id VARCHAR(128) PRIMARY KEY,
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        workspace_id VARCHAR(128) NOT NULL,
        actor_id VARCHAR(256) NOT NULL,
        contract_version VARCHAR(20) NOT NULL,
        surface VARCHAR(32) NOT NULL,
        action VARCHAR(64) NOT NULL,
        idempotency_key VARCHAR(256) NOT NULL,
        request_hash CHAR(64) NOT NULL,
        expected_revision BIGINT NOT NULL,
        committed_revision BIGINT,
        response_json JSONB,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        committed_at TIMESTAMPTZ,
        CONSTRAINT fk_workspace_mutation_receipts_profile
            FOREIGN KEY (tenant_id, project_id, workspace_id)
            REFERENCES avernet.workspace_profiles (tenant_id, project_id, workspace_id)
            ON DELETE CASCADE,
        CONSTRAINT uq_workspace_mutation_receipts_intent
            UNIQUE (workspace_id, actor_id, idempotency_key),
        CONSTRAINT ck_workspace_mutation_receipts_hash
            CHECK (request_hash ~ '^[0-9a-f]{64}$'),
        CONSTRAINT ck_workspace_mutation_receipts_revision
            CHECK (expected_revision >= 0),
        CONSTRAINT ck_workspace_mutation_receipts_commit
            CHECK (
                committed_revision IS NULL
                OR committed_revision > expected_revision
            )
    )
    """,
    """
    CREATE TABLE avernet.workspace_plans (
        plan_id VARCHAR(128) PRIMARY KEY,
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        workspace_id VARCHAR(128) NOT NULL,
        source_task_id VARCHAR(128),
        collaboration_definition_id VARCHAR(128) NOT NULL,
        collaboration_definition_version INTEGER NOT NULL,
        state_machine_run_id VARCHAR(128),
        goal TEXT NOT NULL,
        goal_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        status VARCHAR(40) NOT NULL DEFAULT 'draft',
        revision BIGINT NOT NULL DEFAULT 0,
        created_by_actor_id VARCHAR(256),
        metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMPTZ,
        CONSTRAINT fk_workspace_plans_profile
            FOREIGN KEY (tenant_id, project_id, workspace_id)
            REFERENCES avernet.workspace_profiles (tenant_id, project_id, workspace_id)
            ON DELETE CASCADE,
        CONSTRAINT fk_workspace_plans_source_task
            FOREIGN KEY (tenant_id, project_id, workspace_id, source_task_id)
            REFERENCES avernet.workspace_tasks (tenant_id, project_id, workspace_id, task_id)
            ON DELETE SET NULL (source_task_id),
        CONSTRAINT uq_workspace_plans_scope_id
            UNIQUE (tenant_id, project_id, workspace_id, plan_id),
        CONSTRAINT uq_workspace_plans_state_machine_run
            UNIQUE (state_machine_run_id),
        CONSTRAINT ck_workspace_plans_revision CHECK (revision >= 0),
        CONSTRAINT ck_workspace_plans_definition_version
            CHECK (collaboration_definition_version > 0)
    )
    """,
    """
    CREATE TABLE avernet.workspace_plan_nodes (
        node_id VARCHAR(128) PRIMARY KEY,
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        workspace_id VARCHAR(128) NOT NULL,
        plan_id VARCHAR(128) NOT NULL,
        workspace_task_id VARCHAR(128),
        parent_id VARCHAR(128),
        kind VARCHAR(40) NOT NULL,
        title VARCHAR(500) NOT NULL,
        description TEXT,
        intent TEXT,
        status VARCHAR(40) NOT NULL DEFAULT 'pending',
        sequence_number INTEGER NOT NULL,
        dependencies_json JSONB NOT NULL DEFAULT '[]'::jsonb,
        inputs_schema_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        outputs_schema_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        acceptance_criteria_json JSONB NOT NULL DEFAULT '[]'::jsonb,
        feature_checkpoint_json JSONB,
        handoff_package_json JSONB,
        recommended_capabilities_json JSONB NOT NULL DEFAULT '[]'::jsonb,
        preferred_agent_id VARCHAR(128),
        estimated_effort_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        priority INTEGER NOT NULL DEFAULT 0,
        progress_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        assignee_agent_id VARCHAR(128),
        current_attempt_id VARCHAR(128),
        max_attempts INTEGER NOT NULL DEFAULT 1,
        timeout_deadline_at TIMESTAMPTZ,
        metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMPTZ,
        CONSTRAINT fk_workspace_plan_nodes_plan
            FOREIGN KEY (tenant_id, project_id, workspace_id, plan_id)
            REFERENCES avernet.workspace_plans (tenant_id, project_id, workspace_id, plan_id)
            ON DELETE CASCADE,
        CONSTRAINT fk_workspace_plan_nodes_task
            FOREIGN KEY (tenant_id, project_id, workspace_id, workspace_task_id)
            REFERENCES avernet.workspace_tasks (tenant_id, project_id, workspace_id, task_id)
            ON DELETE SET NULL (workspace_task_id),
        CONSTRAINT fk_workspace_plan_nodes_parent
            FOREIGN KEY (tenant_id, project_id, workspace_id, plan_id, parent_id)
            REFERENCES avernet.workspace_plan_nodes
                (tenant_id, project_id, workspace_id, plan_id, node_id)
            ON DELETE SET NULL (parent_id),
        CONSTRAINT uq_workspace_plan_nodes_scope_id
            UNIQUE (tenant_id, project_id, workspace_id, plan_id, node_id),
        CONSTRAINT uq_workspace_plan_nodes_sequence UNIQUE (plan_id, sequence_number),
        CONSTRAINT ck_workspace_plan_nodes_sequence CHECK (sequence_number >= 0),
        CONSTRAINT ck_workspace_plan_nodes_max_attempts CHECK (max_attempts > 0)
    )
    """,
    """
    CREATE TABLE avernet.workspace_plan_blackboard_entries (
        entry_id VARCHAR(128) PRIMARY KEY,
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        workspace_id VARCHAR(128) NOT NULL,
        plan_id VARCHAR(128) NOT NULL,
        key VARCHAR(500) NOT NULL,
        version BIGINT NOT NULL,
        value_json JSONB NOT NULL,
        content_hash CHAR(64) NOT NULL,
        created_by_actor_id VARCHAR(256),
        schema_ref TEXT,
        metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_workspace_plan_blackboard_plan
            FOREIGN KEY (tenant_id, project_id, workspace_id, plan_id)
            REFERENCES avernet.workspace_plans (tenant_id, project_id, workspace_id, plan_id)
            ON DELETE CASCADE,
        CONSTRAINT uq_workspace_plan_blackboard_version
            UNIQUE (plan_id, key, version),
        CONSTRAINT ck_workspace_plan_blackboard_version CHECK (version > 0),
        CONSTRAINT ck_workspace_plan_blackboard_hash
            CHECK (content_hash ~ '^[0-9a-f]{64}$')
    )
    """,
    """
    CREATE TABLE avernet.workspace_plan_events (
        event_id VARCHAR(128) PRIMARY KEY,
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        workspace_id VARCHAR(128) NOT NULL,
        plan_id VARCHAR(128) NOT NULL,
        event_sequence BIGINT NOT NULL,
        node_id VARCHAR(128),
        attempt_id VARCHAR(128),
        event_type VARCHAR(80) NOT NULL,
        source VARCHAR(80) NOT NULL DEFAULT 'system',
        actor_id VARCHAR(256),
        payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_workspace_plan_events_plan
            FOREIGN KEY (tenant_id, project_id, workspace_id, plan_id)
            REFERENCES avernet.workspace_plans (tenant_id, project_id, workspace_id, plan_id)
            ON DELETE CASCADE,
        CONSTRAINT uq_workspace_plan_events_sequence UNIQUE (plan_id, event_sequence),
        CONSTRAINT ck_workspace_plan_events_sequence CHECK (event_sequence >= 0)
    )
    """,
    """
    CREATE TABLE avernet.workspace_outbox (
        outbox_id VARCHAR(128) PRIMARY KEY,
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        workspace_id VARCHAR(128) NOT NULL,
        aggregate_type VARCHAR(40) NOT NULL,
        aggregate_id VARCHAR(128) NOT NULL,
        event_type VARCHAR(80) NOT NULL,
        stream_name VARCHAR(128) NOT NULL,
        event_sequence BIGINT NOT NULL,
        payload_json JSONB NOT NULL,
        metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        correlation_id VARCHAR(128),
        idempotency_key VARCHAR(256) NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'pending',
        legacy_status VARCHAR(20),
        attempt_count INTEGER NOT NULL DEFAULT 0,
        max_attempts INTEGER NOT NULL DEFAULT 10,
        lease_owner VARCHAR(255),
        lease_expires_at TIMESTAMPTZ,
        last_error TEXT,
        next_attempt_at TIMESTAMPTZ,
        dispatched_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_workspace_outbox_profile
            FOREIGN KEY (tenant_id, project_id, workspace_id)
            REFERENCES avernet.workspace_profiles (tenant_id, project_id, workspace_id)
            ON DELETE CASCADE,
        CONSTRAINT uq_workspace_outbox_idempotency UNIQUE (workspace_id, idempotency_key),
        CONSTRAINT uq_workspace_outbox_sequence
            UNIQUE (workspace_id, stream_name, event_sequence),
        CONSTRAINT ck_workspace_outbox_attempts
            CHECK (attempt_count >= 0 AND max_attempts > 0),
        CONSTRAINT ck_workspace_outbox_sequence CHECK (event_sequence >= 0)
    )
    """,
    """
    CREATE TABLE avernet.workspace_pipeline_contracts (
        contract_id VARCHAR(128) PRIMARY KEY,
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        workspace_id VARCHAR(128) NOT NULL,
        plan_id VARCHAR(128),
        provider VARCHAR(40) NOT NULL DEFAULT 'sandbox_native',
        code_root TEXT,
        commands_json JSONB NOT NULL DEFAULT '[]'::jsonb,
        env_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        trigger_policy_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        timeout_seconds INTEGER NOT NULL DEFAULT 600,
        auto_deploy BOOLEAN NOT NULL DEFAULT TRUE,
        preview_port INTEGER,
        health_url TEXT,
        status VARCHAR(20) NOT NULL DEFAULT 'active',
        metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_workspace_pipeline_contracts_profile
            FOREIGN KEY (tenant_id, project_id, workspace_id)
            REFERENCES avernet.workspace_profiles (tenant_id, project_id, workspace_id)
            ON DELETE CASCADE,
        CONSTRAINT uq_workspace_pipeline_contracts_plan UNIQUE (workspace_id, plan_id),
        CONSTRAINT ck_workspace_pipeline_contracts_timeout CHECK (timeout_seconds > 0)
    )
    """,
    """
    CREATE TABLE avernet.workspace_pipeline_runs (
        run_id VARCHAR(128) PRIMARY KEY,
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        workspace_id VARCHAR(128) NOT NULL,
        contract_id VARCHAR(128) NOT NULL,
        plan_id VARCHAR(128),
        node_id VARCHAR(128),
        attempt_id VARCHAR(128),
        commit_ref VARCHAR(255),
        provider VARCHAR(40) NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'pending',
        reason TEXT,
        started_at TIMESTAMPTZ,
        completed_at TIMESTAMPTZ,
        metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_workspace_pipeline_runs_contract
            FOREIGN KEY (contract_id) REFERENCES avernet.workspace_pipeline_contracts (contract_id)
            ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE avernet.workspace_pipeline_stage_runs (
        stage_run_id VARCHAR(128) PRIMARY KEY,
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        workspace_id VARCHAR(128) NOT NULL,
        run_id VARCHAR(128) NOT NULL,
        stage VARCHAR(80) NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'pending',
        command TEXT,
        exit_code INTEGER,
        stdout_preview TEXT,
        stderr_preview TEXT,
        log_ref TEXT,
        artifact_refs_json JSONB NOT NULL DEFAULT '[]'::jsonb,
        started_at TIMESTAMPTZ,
        completed_at TIMESTAMPTZ,
        duration_ms BIGINT,
        metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_workspace_pipeline_stage_runs_run
            FOREIGN KEY (run_id) REFERENCES avernet.workspace_pipeline_runs (run_id)
            ON DELETE CASCADE,
        CONSTRAINT ck_workspace_pipeline_stage_runs_duration
            CHECK (duration_ms IS NULL OR duration_ms >= 0)
    )
    """,
    """
    CREATE TABLE avernet.workspace_deployments (
        deployment_id VARCHAR(128) PRIMARY KEY,
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        workspace_id VARCHAR(128) NOT NULL,
        plan_id VARCHAR(128),
        node_id VARCHAR(128),
        pipeline_run_id VARCHAR(128),
        provider VARCHAR(40) NOT NULL DEFAULT 'sandbox_native',
        status VARCHAR(20) NOT NULL DEFAULT 'pending',
        command TEXT,
        process_id BIGINT,
        process_group_id BIGINT,
        port INTEGER,
        service_id VARCHAR(128),
        service_name VARCHAR(255),
        service_url TEXT,
        websocket_preview_url TEXT,
        required BOOLEAN NOT NULL DEFAULT TRUE,
        preview_url TEXT,
        health_url TEXT,
        restart_count INTEGER NOT NULL DEFAULT 0,
        last_healthy_at TIMESTAMPTZ,
        rollback_ref TEXT,
        log_ref TEXT,
        metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_workspace_deployments_profile
            FOREIGN KEY (tenant_id, project_id, workspace_id)
            REFERENCES avernet.workspace_profiles (tenant_id, project_id, workspace_id)
            ON DELETE CASCADE,
        CONSTRAINT fk_workspace_deployments_pipeline
            FOREIGN KEY (pipeline_run_id) REFERENCES avernet.workspace_pipeline_runs (run_id)
            ON DELETE SET NULL,
        CONSTRAINT ck_workspace_deployments_restart_count CHECK (restart_count >= 0),
        CONSTRAINT ck_workspace_deployments_port
            CHECK (port IS NULL OR (port > 0 AND port <= 65535))
    )
    """,
    """
    CREATE TABLE avernet.workspace_agent_runtime_correlations (
        correlation_id VARCHAR(128) PRIMARY KEY,
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        workspace_id VARCHAR(128) NOT NULL,
        task_id VARCHAR(128),
        attempt_id VARCHAR(128),
        plan_id VARCHAR(128),
        plan_node_id VARCHAR(128),
        conversation_id VARCHAR(128) NOT NULL,
        bcs_session_id VARCHAR(128),
        bcs_message_id VARCHAR(128),
        state_machine_run_id VARCHAR(128),
        delivery_request_id VARCHAR(191),
        provider_run_id VARCHAR(191),
        ray_actor_id VARCHAR(256),
        detached_worker_id VARCHAR(256),
        status VARCHAR(32) NOT NULL DEFAULT 'pending',
        abort_requested_at TIMESTAMPTZ,
        ray_cancelled_at TIMESTAMPTZ,
        local_worker_cancelled_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMPTZ,
        CONSTRAINT fk_workspace_runtime_correlations_profile
            FOREIGN KEY (tenant_id, project_id, workspace_id)
            REFERENCES avernet.workspace_profiles (tenant_id, project_id, workspace_id)
            ON DELETE CASCADE,
        CONSTRAINT uq_workspace_runtime_correlations_delivery UNIQUE (delivery_request_id),
        CONSTRAINT uq_workspace_runtime_correlations_provider_run UNIQUE (provider_run_id),
        CONSTRAINT ck_workspace_runtime_correlations_abort
            CHECK (
                abort_requested_at IS NULL
                OR ray_actor_id IS NOT NULL
                OR detached_worker_id IS NOT NULL
            )
    )
    """,
    """
    CREATE TABLE avernet.workspace_execution_terminals (
        terminal_id VARCHAR(128) PRIMARY KEY,
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        workspace_id VARCHAR(128) NOT NULL,
        correlation_id VARCHAR(128) NOT NULL,
        execution_status VARCHAR(32) NOT NULL,
        terminal_message_id VARCHAR(128) NOT NULL,
        terminal_event_id VARCHAR(128) NOT NULL,
        plan_event_id VARCHAR(128) NOT NULL,
        completion_outbox_id VARCHAR(128) NOT NULL,
        report_hash CHAR(64) NOT NULL,
        persisted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMPTZ NOT NULL,
        CONSTRAINT fk_workspace_execution_terminals_correlation
            FOREIGN KEY (correlation_id)
            REFERENCES avernet.workspace_agent_runtime_correlations (correlation_id)
            ON DELETE CASCADE,
        CONSTRAINT fk_workspace_execution_terminals_plan_event
            FOREIGN KEY (plan_event_id) REFERENCES avernet.workspace_plan_events (event_id),
        CONSTRAINT fk_workspace_execution_terminals_outbox
            FOREIGN KEY (completion_outbox_id) REFERENCES avernet.workspace_outbox (outbox_id),
        CONSTRAINT uq_workspace_execution_terminals_correlation UNIQUE (correlation_id),
        CONSTRAINT uq_workspace_execution_terminals_message UNIQUE (terminal_message_id),
        CONSTRAINT ck_workspace_execution_terminals_hash
            CHECK (report_hash ~ '^[0-9a-f]{64}$'),
        CONSTRAINT ck_workspace_execution_terminals_order
            CHECK (completed_at >= persisted_at)
    )
    """,
    """
    CREATE TABLE avernet.workspace_migration_ledger (
        ledger_id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        migration_run_id VARCHAR(128) NOT NULL,
        migration_version VARCHAR(32) NOT NULL,
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        workspace_id VARCHAR(128),
        entity_type VARCHAR(80) NOT NULL,
        source_id VARCHAR(256) NOT NULL,
        target_table VARCHAR(128) NOT NULL,
        target_id VARCHAR(256) NOT NULL,
        source_hash CHAR(64) NOT NULL,
        target_hash CHAR(64),
        status VARCHAR(20) NOT NULL DEFAULT 'pending',
        attempt_count INTEGER NOT NULL DEFAULT 0,
        error_code VARCHAR(80),
        error_detail TEXT,
        migrated_at TIMESTAMPTZ,
        verified_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT uq_workspace_migration_ledger_source
            UNIQUE (migration_run_id, entity_type, source_id),
        CONSTRAINT ck_workspace_migration_ledger_source_hash
            CHECK (source_hash ~ '^[0-9a-f]{64}$'),
        CONSTRAINT ck_workspace_migration_ledger_target_hash
            CHECK (target_hash IS NULL OR target_hash ~ '^[0-9a-f]{64}$'),
        CONSTRAINT ck_workspace_migration_ledger_attempts CHECK (attempt_count >= 0)
    )
    """,
    """
    CREATE TABLE avernet.workspace_judge_audits (
        audit_id VARCHAR(128) PRIMARY KEY,
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        workspace_id VARCHAR(128),
        plan_id VARCHAR(128),
        plan_node_id VARCHAR(128),
        judgment_type VARCHAR(80) NOT NULL,
        agent_id VARCHAR(128) NOT NULL,
        tool_name VARCHAR(128) NOT NULL,
        input_json JSONB NOT NULL,
        output_json JSONB NOT NULL,
        rationale TEXT NOT NULL,
        latency_ms BIGINT NOT NULL,
        status VARCHAR(20) NOT NULL,
        error_detail TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT ck_workspace_judge_audits_latency CHECK (latency_ms >= 0),
        CONSTRAINT ck_workspace_judge_audits_rationale CHECK (length(rationale) > 0)
    )
    """,
)

_INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX ix_avn_ws_revision_credentials_actor ON avernet.workspace_revision_credentials (workspace_id, actor_id, revision)",
    "CREATE INDEX ix_avn_ws_mutation_receipts_revision ON avernet.workspace_mutation_receipts (tenant_id, project_id, workspace_id, committed_revision)",
    "CREATE INDEX ix_avn_ws_plans_status ON avernet.workspace_plans (workspace_id, status, updated_at)",
    "CREATE INDEX ix_avn_ws_plan_nodes_status ON avernet.workspace_plan_nodes (plan_id, status, sequence_number)",
    "CREATE INDEX ix_avn_ws_plan_nodes_timeout ON avernet.workspace_plan_nodes (status, timeout_deadline_at)",
    "CREATE INDEX ix_avn_ws_plan_blackboard_key ON avernet.workspace_plan_blackboard_entries (plan_id, key, version DESC)",
    "CREATE INDEX ix_avn_ws_plan_events_created ON avernet.workspace_plan_events (plan_id, created_at)",
    "CREATE INDEX ix_avn_ws_plan_events_attempt ON avernet.workspace_plan_events (attempt_id)",
    "CREATE INDEX ix_avn_ws_outbox_ready ON avernet.workspace_outbox (status, next_attempt_at, created_at)",
    "CREATE INDEX ix_avn_ws_outbox_lease ON avernet.workspace_outbox (lease_owner, lease_expires_at)",
    "CREATE INDEX ix_avn_ws_pipeline_runs_plan_node ON avernet.workspace_pipeline_runs (plan_id, node_id)",
    "CREATE INDEX ix_avn_ws_pipeline_runs_status ON avernet.workspace_pipeline_runs (workspace_id, status)",
    "CREATE INDEX ix_avn_ws_pipeline_stages_run ON avernet.workspace_pipeline_stage_runs (run_id, stage)",
    "CREATE INDEX ix_avn_ws_deployments_plan_node ON avernet.workspace_deployments (plan_id, node_id)",
    "CREATE INDEX ix_avn_ws_deployments_status ON avernet.workspace_deployments (workspace_id, status)",
    "CREATE INDEX ix_avn_ws_runtime_conversation ON avernet.workspace_agent_runtime_correlations (workspace_id, conversation_id, created_at)",
    "CREATE INDEX ix_avn_ws_runtime_status ON avernet.workspace_agent_runtime_correlations (status, updated_at)",
    "CREATE INDEX ix_avn_ws_migration_run_status ON avernet.workspace_migration_ledger (migration_run_id, status, entity_type)",
    "CREATE INDEX ix_avn_ws_migration_scope ON avernet.workspace_migration_ledger (tenant_id, project_id, workspace_id)",
    "CREATE INDEX ix_avn_ws_judge_scope ON avernet.workspace_judge_audits (tenant_id, project_id, workspace_id, created_at)",
    "CREATE INDEX ix_avn_ws_judge_plan_node ON avernet.workspace_judge_audits (plan_id, plan_node_id, created_at)",
)

_UPDATED_TABLES: tuple[str, ...] = (
    "workspace_authorities",
    "workspace_plans",
    "workspace_plan_nodes",
    "workspace_outbox",
    "workspace_pipeline_contracts",
    "workspace_pipeline_runs",
    "workspace_pipeline_stage_runs",
    "workspace_deployments",
    "workspace_agent_runtime_correlations",
    "workspace_migration_ledger",
)

_TABLES: tuple[str, ...] = (
    "workspace_execution_terminals",
    "workspace_judge_audits",
    "workspace_migration_ledger",
    "workspace_agent_runtime_correlations",
    "workspace_deployments",
    "workspace_pipeline_stage_runs",
    "workspace_pipeline_runs",
    "workspace_pipeline_contracts",
    "workspace_outbox",
    "workspace_plan_events",
    "workspace_plan_blackboard_entries",
    "workspace_plan_nodes",
    "workspace_plans",
    "workspace_mutation_receipts",
    "workspace_revision_credentials",
    "workspace_authorities",
)


def _execute_all(statements: Iterable[str]) -> None:
    for statement in statements:
        op.execute(sa.text(statement))


def upgrade() -> None:
    _execute_all(_TABLE_DDL)
    _execute_all(_INDEX_DDL)
    for table_name in _UPDATED_TABLES:
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER trg_{table_name}_touch_updated_at
                BEFORE UPDATE ON avernet.{table_name}
                FOR EACH ROW EXECUTE FUNCTION avernet.touch_updated_at()
                """
            )
        )


def downgrade() -> None:
    for table_name in _TABLES:
        op.execute(sa.text(f"DROP TABLE IF EXISTS avernet.{table_name} CASCADE"))
