CREATE UNIQUE INDEX IF NOT EXISTS uq_avn_workspace_autonomy_ticks_scope_id
    ON workspace_autonomy_ticks (tenant_id, project_id, workspace_id, tick_id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_avn_workspace_agent_bindings_scope_id
    ON workspace_agent_bindings (tenant_id, project_id, workspace_id, binding_id);

CREATE TABLE IF NOT EXISTS workspace_autonomy_progression_outbox (
    progression_id TEXT PRIMARY KEY,
    tick_id TEXT NOT NULL UNIQUE,
    tenant_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    root_task_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    judge_agent_id TEXT NOT NULL,
    workspace_agent_binding_id TEXT NOT NULL,
    task_title TEXT NOT NULL,
    task_description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 8,
    next_attempt_at_ms INTEGER NOT NULL DEFAULT 0,
    lease_owner TEXT,
    lease_expires_at_ms INTEGER,
    lease_generation INTEGER NOT NULL DEFAULT 0,
    execution_task_id TEXT,
    last_error TEXT,
    created_at_ms INTEGER NOT NULL,
    completed_at_ms INTEGER,
    FOREIGN KEY (tenant_id, project_id, workspace_id, tick_id)
        REFERENCES workspace_autonomy_ticks(tenant_id, project_id, workspace_id, tick_id)
        ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, project_id, workspace_id)
        REFERENCES workspace_profiles(tenant_id, project_id, workspace_id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, project_id, workspace_id, root_task_id)
        REFERENCES workspace_tasks(tenant_id, project_id, workspace_id, task_id)
        ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, project_id, workspace_id, workspace_agent_binding_id)
        REFERENCES workspace_agent_bindings(tenant_id, project_id, workspace_id, binding_id)
        ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, project_id, workspace_id, execution_task_id)
        REFERENCES workspace_tasks(tenant_id, project_id, workspace_id, task_id)
        ON DELETE RESTRICT,
    CHECK (status IN ('pending', 'processing', 'completed', 'dead_letter')),
    CHECK (
        attempt_count >= 0
        AND max_attempts > 0
        AND attempt_count <= max_attempts
    ),
    CHECK (
        next_attempt_at_ms >= 0
        AND created_at_ms >= 0
        AND lease_generation >= 0
        AND (lease_expires_at_ms IS NULL OR lease_expires_at_ms >= 0)
        AND (completed_at_ms IS NULL OR completed_at_ms >= 0)
    ),
    CHECK (
        (status = 'processing'
            AND lease_owner IS NOT NULL
            AND lease_expires_at_ms IS NOT NULL)
        OR
        (status <> 'processing'
            AND lease_owner IS NULL
            AND lease_expires_at_ms IS NULL)
    ),
    CHECK (
        (status = 'completed'
            AND execution_task_id IS NOT NULL
            AND completed_at_ms IS NOT NULL)
        OR
        (status <> 'completed' AND completed_at_ms IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS ix_avn_workspace_autonomy_progression_due
    ON workspace_autonomy_progression_outbox
        (status, next_attempt_at_ms, lease_expires_at_ms, created_at_ms, progression_id);

CREATE INDEX IF NOT EXISTS ix_avn_workspace_autonomy_progression_workspace
    ON workspace_autonomy_progression_outbox (workspace_id, created_at_ms, progression_id);

CREATE TRIGGER IF NOT EXISTS trg_workspace_autonomy_progression_snapshot_immutable
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
ON workspace_autonomy_progression_outbox
WHEN
    NEW.tick_id IS NOT OLD.tick_id
    OR NEW.tenant_id IS NOT OLD.tenant_id
    OR NEW.project_id IS NOT OLD.project_id
    OR NEW.workspace_id IS NOT OLD.workspace_id
    OR NEW.root_task_id IS NOT OLD.root_task_id
    OR NEW.actor_id IS NOT OLD.actor_id
    OR NEW.judge_agent_id IS NOT OLD.judge_agent_id
    OR NEW.workspace_agent_binding_id IS NOT OLD.workspace_agent_binding_id
    OR NEW.task_title IS NOT OLD.task_title
    OR NEW.task_description IS NOT OLD.task_description
    OR NEW.created_at_ms IS NOT OLD.created_at_ms
BEGIN
    SELECT RAISE(
        ABORT,
        'workspace_autonomy_progression_outbox snapshot columns are immutable'
    );
END;
