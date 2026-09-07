CREATE TABLE IF NOT EXISTS workspace_contract_actor_resolution_audits (
    audit_id TEXT NOT NULL,
    service_principal_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    purpose TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    outcome TEXT NOT NULL,
    reason TEXT NOT NULL,
    resolved_actor_user_id TEXT,
    resolved_participant_actor_id TEXT,
    authority_revision INTEGER,
    policy_version TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (audit_id),
    UNIQUE (service_principal_id,operation_id),
    CHECK (length(request_hash) = 64 AND request_hash NOT GLOB '*[^0-9a-f]*'),
    CHECK (purpose IN (
        'planner_turn',
        'supervisor_turn',
        'verifier_turn',
        'worktree_turn',
        'iteration_review_turn'
    )),
    CHECK (outcome IN ('resolved','rejected')),
    CHECK (reason IN (
        'resolved',
        'scope_unavailable',
        'workspace_inactive',
        'owner_unavailable',
        'owner_ambiguous'
    )),
    CHECK (authority_revision IS NULL OR authority_revision >= 0),
    CHECK (
        (outcome = 'resolved'
         AND reason = 'resolved'
         AND resolved_actor_user_id IS NOT NULL
         AND resolved_participant_actor_id IS NOT NULL
         AND authority_revision IS NOT NULL)
        OR
        (outcome = 'rejected'
         AND reason <> 'resolved'
         AND resolved_actor_user_id IS NULL
         AND resolved_participant_actor_id IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS ix_avn_workspace_contract_actor_audit_scope
    ON workspace_contract_actor_resolution_audits
    (tenant_id,project_id,workspace_id,created_at);

CREATE TRIGGER IF NOT EXISTS trg_avn_workspace_contract_actor_audit_no_update
BEFORE UPDATE ON workspace_contract_actor_resolution_audits
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'workspace contract actor authority audit is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_avn_workspace_contract_actor_audit_no_delete
BEFORE DELETE ON workspace_contract_actor_resolution_audits
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'workspace contract actor authority audit is append-only');
END;
