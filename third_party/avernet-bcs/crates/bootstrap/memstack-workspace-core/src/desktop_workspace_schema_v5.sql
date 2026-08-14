CREATE UNIQUE INDEX IF NOT EXISTS uq_avn_workspace_judge_audits_scope_id
    ON workspace_judge_audits (tenant_id, project_id, workspace_id, audit_id);

CREATE TABLE IF NOT EXISTS workspace_autonomy_judgment_claims (
    claim_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    expected_revision INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'processing',
    lease_owner TEXT,
    lease_expires_at_ms INTEGER,
    lease_generation INTEGER NOT NULL DEFAULT 1,
    audit_id TEXT,
    judgment_json TEXT,
    error_detail TEXT,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    judged_at_ms INTEGER,
    applied_at_ms INTEGER,
    FOREIGN KEY (tenant_id, project_id, workspace_id)
        REFERENCES workspace_profiles(tenant_id, project_id, workspace_id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, project_id, workspace_id, audit_id)
        REFERENCES workspace_judge_audits(tenant_id, project_id, workspace_id, audit_id)
        ON DELETE RESTRICT,
    UNIQUE (workspace_id, actor_id, idempotency_key),
    CHECK (status IN ('processing', 'judged', 'applied', 'failed', 'superseded')),
    CHECK (expected_revision >= 0),
    CHECK (lease_generation > 0),
    CHECK (created_at_ms >= 0 AND updated_at_ms >= 0),
    CHECK (lease_expires_at_ms IS NULL OR lease_expires_at_ms >= 0),
    CHECK (judged_at_ms IS NULL OR judged_at_ms >= 0),
    CHECK (applied_at_ms IS NULL OR applied_at_ms >= 0),
    CHECK (
        (status = 'processing' AND lease_owner IS NOT NULL AND lease_expires_at_ms IS NOT NULL)
        OR (status <> 'processing' AND lease_owner IS NULL AND lease_expires_at_ms IS NULL)
    ),
    CHECK (
        (status IN ('judged', 'applied') AND audit_id IS NOT NULL AND judgment_json IS NOT NULL)
        OR (status NOT IN ('judged', 'applied') AND judgment_json IS NULL)
    ),
    CHECK (
        (status = 'applied' AND applied_at_ms IS NOT NULL)
        OR (status <> 'applied' AND applied_at_ms IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS ix_avn_workspace_autonomy_judgment_claim_lease
    ON workspace_autonomy_judgment_claims
        (status, lease_expires_at_ms, updated_at_ms, claim_id);

CREATE TRIGGER IF NOT EXISTS trg_workspace_autonomy_judgment_claim_snapshot_immutable
BEFORE UPDATE OF
    tenant_id,
    project_id,
    workspace_id,
    actor_id,
    idempotency_key,
    request_hash,
    expected_revision,
    created_at_ms
ON workspace_autonomy_judgment_claims
WHEN
    NEW.tenant_id IS NOT OLD.tenant_id
    OR NEW.project_id IS NOT OLD.project_id
    OR NEW.workspace_id IS NOT OLD.workspace_id
    OR NEW.actor_id IS NOT OLD.actor_id
    OR NEW.idempotency_key IS NOT OLD.idempotency_key
    OR NEW.request_hash IS NOT OLD.request_hash
    OR NEW.expected_revision IS NOT OLD.expected_revision
    OR NEW.created_at_ms IS NOT OLD.created_at_ms
BEGIN
    SELECT RAISE(
        ABORT,
        'workspace_autonomy_judgment_claims snapshot columns are immutable'
    );
END;

CREATE TABLE IF NOT EXISTS workspace_autonomy_bootstrap_outbox (
    bootstrap_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL UNIQUE,
    actor_id TEXT NOT NULL,
    objective_title TEXT NOT NULL,
    objective_description TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 8,
    next_attempt_at_ms INTEGER NOT NULL DEFAULT 0,
    lease_owner TEXT,
    lease_expires_at_ms INTEGER,
    lease_generation INTEGER NOT NULL DEFAULT 0,
    objective_id TEXT,
    root_task_id TEXT,
    last_error TEXT,
    created_at_ms INTEGER NOT NULL,
    completed_at_ms INTEGER,
    FOREIGN KEY (tenant_id, project_id, workspace_id)
        REFERENCES workspace_profiles(tenant_id, project_id, workspace_id) ON DELETE CASCADE,
    CHECK (status IN ('pending', 'processing', 'completed', 'dead_letter')),
    CHECK (length(trim(objective_title)) > 0),
    CHECK (attempt_count >= 0 AND max_attempts > 0 AND attempt_count <= max_attempts),
    CHECK (
        next_attempt_at_ms >= 0
        AND lease_generation >= 0
        AND created_at_ms >= 0
        AND (lease_expires_at_ms IS NULL OR lease_expires_at_ms >= 0)
        AND (completed_at_ms IS NULL OR completed_at_ms >= 0)
    ),
    CHECK (
        (status = 'processing' AND lease_owner IS NOT NULL AND lease_expires_at_ms IS NOT NULL)
        OR (status <> 'processing' AND lease_owner IS NULL AND lease_expires_at_ms IS NULL)
    ),
    CHECK (
        (status = 'completed'
            AND objective_id IS NOT NULL
            AND root_task_id IS NOT NULL
            AND completed_at_ms IS NOT NULL)
        OR (status <> 'completed' AND completed_at_ms IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS ix_avn_workspace_autonomy_bootstrap_due
    ON workspace_autonomy_bootstrap_outbox
        (status, next_attempt_at_ms, lease_expires_at_ms, created_at_ms, bootstrap_id);

CREATE TRIGGER IF NOT EXISTS trg_workspace_autonomy_bootstrap_snapshot_immutable
BEFORE UPDATE OF
    tenant_id,
    project_id,
    workspace_id,
    actor_id,
    objective_title,
    objective_description,
    created_at_ms
ON workspace_autonomy_bootstrap_outbox
WHEN
    NEW.tenant_id IS NOT OLD.tenant_id
    OR NEW.project_id IS NOT OLD.project_id
    OR NEW.workspace_id IS NOT OLD.workspace_id
    OR NEW.actor_id IS NOT OLD.actor_id
    OR NEW.objective_title IS NOT OLD.objective_title
    OR NEW.objective_description IS NOT OLD.objective_description
    OR NEW.created_at_ms IS NOT OLD.created_at_ms
BEGIN
    SELECT RAISE(
        ABORT,
        'workspace_autonomy_bootstrap_outbox snapshot columns are immutable'
    );
END;

CREATE TABLE IF NOT EXISTS workspace_autonomy_attentions (
    attention_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    root_task_id TEXT,
    source_kind TEXT NOT NULL,
    source_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at_ms INTEGER NOT NULL,
    resolved_at_ms INTEGER,
    resolved_by_actor_id TEXT,
    FOREIGN KEY (tenant_id, project_id, workspace_id)
        REFERENCES workspace_profiles(tenant_id, project_id, workspace_id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, project_id, workspace_id, root_task_id)
        REFERENCES workspace_tasks(tenant_id, project_id, workspace_id, task_id)
        ON DELETE CASCADE,
    UNIQUE (source_kind, source_id),
    CHECK (source_kind IN (
        'judge_block', 'judge_escalate', 'progression_dead_letter',
        'bootstrap_dead_letter', 'task_dispatch_dead_letter'
    )),
    CHECK (
        (source_kind = 'bootstrap_dead_letter' AND root_task_id IS NULL)
        OR (source_kind IN (
            'judge_block', 'judge_escalate', 'progression_dead_letter',
            'task_dispatch_dead_letter'
        ) AND root_task_id IS NOT NULL)
    ),
    CHECK (status IN ('open', 'resolved')),
    CHECK (length(trim(reason)) > 0),
    CHECK (created_at_ms >= 0 AND (resolved_at_ms IS NULL OR resolved_at_ms >= 0)),
    CHECK (
        (status = 'open' AND resolved_at_ms IS NULL AND resolved_by_actor_id IS NULL)
        OR (status = 'resolved' AND resolved_at_ms IS NOT NULL AND resolved_by_actor_id IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS ix_avn_workspace_autonomy_attention_open
    ON workspace_autonomy_attentions
        (tenant_id, project_id, workspace_id, root_task_id, status, created_at_ms);

CREATE TRIGGER IF NOT EXISTS trg_avn_workspace_autonomy_progression_attention
AFTER UPDATE OF status ON workspace_autonomy_progression_outbox
WHEN NEW.status = 'dead_letter' AND OLD.status <> 'dead_letter'
BEGIN
    INSERT INTO workspace_autonomy_attentions (
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
        COALESCE(NEW.last_error, 'autonomy progression exhausted its retry budget'),
        'open',
        CAST(strftime('%s', 'now') AS INTEGER) * 1000
    )
    ON CONFLICT(source_kind, source_id) DO UPDATE SET
        reason = excluded.reason,
        status = 'open',
        created_at_ms = excluded.created_at_ms,
        resolved_at_ms = NULL,
        resolved_by_actor_id = NULL;
END;

CREATE TRIGGER IF NOT EXISTS trg_avn_workspace_autonomy_bootstrap_attention
AFTER UPDATE OF status ON workspace_autonomy_bootstrap_outbox
WHEN NEW.status = 'dead_letter' AND OLD.status <> 'dead_letter'
BEGIN
    INSERT INTO workspace_autonomy_attentions (
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
        COALESCE(NEW.last_error, 'autonomy bootstrap exhausted its retry budget'),
        'open',
        CAST(strftime('%s', 'now') AS INTEGER) * 1000
    )
    ON CONFLICT(source_kind, source_id) DO UPDATE SET
        reason = excluded.reason,
        status = 'open',
        created_at_ms = excluded.created_at_ms,
        resolved_at_ms = NULL,
        resolved_by_actor_id = NULL;
END;

CREATE TRIGGER IF NOT EXISTS trg_avn_workspace_task_dispatch_attention
AFTER UPDATE OF status ON workspace_task_dispatch_outbox
WHEN NEW.status = 'dead_letter' AND OLD.status <> 'dead_letter'
BEGIN
    INSERT INTO workspace_autonomy_attentions (
        attention_id, tenant_id, project_id, workspace_id, root_task_id,
        source_kind, source_id, reason, status, created_at_ms
    ) VALUES (
        'task-dispatch:' || NEW.dispatch_id,
        NEW.tenant_id,
        NEW.project_id,
        NEW.workspace_id,
        (
            SELECT root.task_id
            FROM workspace_tasks execution
            JOIN workspace_tasks root
              ON root.tenant_id = execution.tenant_id
             AND root.project_id = execution.project_id
             AND root.workspace_id = execution.workspace_id
             AND root.task_id = json_extract(
                 execution.metadata_json,
                 '$.root_goal_task_id'
             )
             AND json_extract(root.metadata_json, '$.task_role') = 'goal_root'
            WHERE execution.tenant_id = NEW.tenant_id
              AND execution.project_id = NEW.project_id
              AND execution.workspace_id = NEW.workspace_id
              AND execution.task_id = NEW.task_id
              AND json_extract(execution.metadata_json, '$.task_role') = 'execution_task'
            LIMIT 1
        ),
        'task_dispatch_dead_letter',
        NEW.dispatch_id,
        COALESCE(NEW.last_error, 'task dispatch exhausted its retry budget'),
        'open',
        CAST(strftime('%s', 'now') AS INTEGER) * 1000
    )
    ON CONFLICT(source_kind, source_id) DO UPDATE SET
        root_task_id = excluded.root_task_id,
        reason = excluded.reason,
        status = 'open',
        created_at_ms = excluded.created_at_ms,
        resolved_at_ms = NULL,
        resolved_by_actor_id = NULL;
END;

INSERT INTO workspace_autonomy_attentions (
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
FROM workspace_autonomy_progression_outbox
WHERE status = 'dead_letter'
ON CONFLICT(source_kind, source_id) DO NOTHING;

INSERT INTO workspace_autonomy_attentions (
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
FROM workspace_autonomy_bootstrap_outbox
WHERE status = 'dead_letter'
ON CONFLICT(source_kind, source_id) DO NOTHING;

INSERT INTO workspace_autonomy_attentions (
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
        FROM workspace_tasks execution
        JOIN workspace_tasks root
          ON root.tenant_id = execution.tenant_id
         AND root.project_id = execution.project_id
         AND root.workspace_id = execution.workspace_id
         AND root.task_id = json_extract(
             execution.metadata_json,
             '$.root_goal_task_id'
         )
         AND json_extract(root.metadata_json, '$.task_role') = 'goal_root'
        WHERE execution.tenant_id = dispatch.tenant_id
          AND execution.project_id = dispatch.project_id
          AND execution.workspace_id = dispatch.workspace_id
          AND execution.task_id = dispatch.task_id
          AND json_extract(execution.metadata_json, '$.task_role') = 'execution_task'
        LIMIT 1
    ),
    'task_dispatch_dead_letter',
    dispatch.dispatch_id,
    COALESCE(dispatch.last_error, 'task dispatch exhausted its retry budget'),
    'open',
    dispatch.created_at_ms
FROM workspace_task_dispatch_outbox dispatch
WHERE dispatch.status = 'dead_letter'
ON CONFLICT(source_kind, source_id) DO NOTHING;
