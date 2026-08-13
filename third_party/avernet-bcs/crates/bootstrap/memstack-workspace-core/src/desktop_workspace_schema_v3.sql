CREATE UNIQUE INDEX IF NOT EXISTS uq_avn_workspace_task_receipts_task_session_scope
    ON workspace_task_receipts(tenant_id, project_id, actor_id, idempotency_key)
    WHERE action = 'create_task_session';
