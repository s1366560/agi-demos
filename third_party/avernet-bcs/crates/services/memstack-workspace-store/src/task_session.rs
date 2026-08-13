//! Atomic Workspace-owned half of task-session creation.

use bcs_db_api::{
    DbCountExpectation, DbError, DbPlugin, DbRow, DbSqlFlavor, DbStatement, DbStatementBuilder,
    DbTransactionStep, DbTransactionStepResult,
};
use serde_json::Value;
use thiserror::Error;

const MESSAGE_EVENT_SEQUENCE_BASE: i64 = 1_i64 << 62;

/// Workspace creation fields included only when the task-session creates its Workspace.
#[derive(Debug, Clone, PartialEq)]
pub struct TaskSessionWorkspaceCreate {
    pub group_id: String,
    pub owner_member_id: String,
    pub name: String,
    pub description: Option<String>,
    pub metadata: Value,
}

/// Optional Workspace Agent Policy committed in the task-session transaction.
#[derive(Debug, Clone, PartialEq)]
pub struct TaskSessionPolicyWrite {
    pub expected_revision: u64,
    pub committed_revision: u64,
    pub roles: Value,
    pub reasoning_effort: String,
    pub permission_mode: String,
    pub updated_at: String,
}

/// Fully validated Core-owned portion of a task-session command.
#[derive(Debug, Clone, PartialEq)]
pub struct TaskSessionWrite {
    pub tenant_id: String,
    pub project_id: String,
    pub workspace_id: String,
    pub actor_id: String,
    pub actor_email: String,
    pub actor_is_superuser: bool,
    pub idempotency_key: String,
    pub payload_hash: String,
    pub receipt_id: String,
    pub conversation_id: String,
    pub message_id: String,
    pub message_content_json: String,
    pub message_metadata_json: String,
    pub message_created_at_ms: i64,
    pub expected_authority_revision: u64,
    pub committed_authority_revision: u64,
    pub response: Value,
    pub workspace_create: Option<TaskSessionWorkspaceCreate>,
    pub policy: Option<TaskSessionPolicyWrite>,
}

/// Committed or replayed Core task-session result.
#[derive(Debug, Clone, PartialEq)]
pub struct TaskSessionWriteOutcome {
    pub receipt_id: String,
    pub response: Value,
    pub replayed: bool,
}

/// Stable persistence failures for the task-session saga boundary.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum TaskSessionStoreError {
    #[error("task-session access denied")]
    AccessDenied,

    #[error("task-session idempotency key was used with a different payload")]
    IdempotencyConflict,

    #[error("task-session receipt is incomplete")]
    IncompleteReceipt,

    #[error("task-session transaction did not satisfy its authority contract")]
    AuthorityConflict,

    #[error("task-session receipt is missing required data: {0}")]
    InvalidReceipt(&'static str),

    #[error("task-session response JSON is invalid: {0}")]
    InvalidResponse(#[source] serde_json::Error),

    #[error(transparent)]
    Database(#[from] DbError),
}

/// PostgreSQL/SQLite task-session persistence with one database transaction.
pub struct TaskSessionStore<'a> {
    db: &'a dyn DbPlugin,
    flavor: DbSqlFlavor,
}

impl<'a> TaskSessionStore<'a> {
    #[must_use]
    pub const fn new(db: &'a dyn DbPlugin, flavor: DbSqlFlavor) -> Self {
        Self { db, flavor }
    }

    /// Commit Workspace/Profile/Policy/Message/receipt/outbox state once, or replay it.
    ///
    /// # Errors
    ///
    /// Returns a stable conflict for payload reuse or an authority/persistence failure.
    pub async fn execute(
        &self,
        write: &TaskSessionWrite,
    ) -> Result<TaskSessionWriteOutcome, TaskSessionStoreError> {
        if let Some(outcome) = self.read_replay(write).await? {
            return Ok(outcome);
        }
        let steps = transaction_steps(self.flavor, write)?;
        let results = match self.db.transaction(steps).await {
            Ok(results) => results,
            Err(error) => {
                if error.is_duplicate_key()
                    && let Some(outcome) = self.read_replay(write).await?
                {
                    return Ok(outcome);
                }
                if error.is_duplicate_key() {
                    return Err(TaskSessionStoreError::AuthorityConflict);
                }
                if matches!(error, DbError::TransactionExpectation { step_index: 0, .. }) {
                    return Err(TaskSessionStoreError::AccessDenied);
                }
                if matches!(error, DbError::TransactionExpectation { .. }) {
                    return Err(TaskSessionStoreError::AuthorityConflict);
                }
                return Err(error.into());
            }
        };
        outcome_from_results(&results, &write.payload_hash, false)
    }

    async fn read_replay(
        &self,
        write: &TaskSessionWrite,
    ) -> Result<Option<TaskSessionWriteOutcome>, TaskSessionStoreError> {
        let rows = self.db.query(receipt_lookup(self.flavor, write)).await?;
        rows.first()
            .map(|row| outcome_from_row(row, &write.payload_hash, true))
            .transpose()
    }
}

fn transaction_steps(
    flavor: DbSqlFlavor,
    write: &TaskSessionWrite,
) -> Result<Vec<DbTransactionStep>, TaskSessionStoreError> {
    let mut steps = Vec::new();
    if let Some(create) = &write.workspace_create {
        steps.push(DbTransactionStep::query_checked(
            project_access(flavor, write),
            DbCountExpectation::exactly(1),
        ));
        steps.push(DbTransactionStep::query_checked(
            workspace_absent(flavor, write, create),
            DbCountExpectation::exactly(0),
        ));
        for statement in create_workspace_statements(flavor, write, create) {
            steps.push(DbTransactionStep::execute_checked(
                statement,
                DbCountExpectation::exactly(1),
            ));
        }
    } else {
        steps.push(DbTransactionStep::query_checked(
            workspace_access(flavor, write, true),
            DbCountExpectation::exactly(1),
        ));
        steps.push(DbTransactionStep::query_checked(
            authority_revision_check(flavor, write),
            DbCountExpectation::exactly(1),
        ));
    }
    if let Some(policy) = &write.policy {
        steps.push(DbTransactionStep::execute_checked(
            policy_upsert(flavor, write, policy),
            DbCountExpectation::exactly(1),
        ));
    }
    if write.workspace_create.is_none() {
        steps.push(DbTransactionStep::execute_checked(
            authority_revision_update(flavor, write),
            DbCountExpectation::exactly(1),
        ));
    }
    steps.extend([
        DbTransactionStep::Execute(message_session_insert(flavor, write)),
        DbTransactionStep::query_checked(
            message_session_scope(flavor, write),
            DbCountExpectation::exactly(1),
        ),
        DbTransactionStep::execute_checked(
            message_session_increment(flavor, write),
            DbCountExpectation::exactly(1),
        ),
        DbTransactionStep::execute_checked(
            message_insert(flavor, write),
            DbCountExpectation::exactly(1),
        ),
        DbTransactionStep::execute_checked(
            message_correlation_insert(flavor, write),
            DbCountExpectation::exactly(1),
        ),
        DbTransactionStep::execute_checked(
            message_outbox_insert(flavor, write),
            DbCountExpectation::exactly(1),
        ),
        DbTransactionStep::execute_checked(
            receipt_insert(flavor, write)?,
            DbCountExpectation::exactly(1),
        ),
        DbTransactionStep::query_checked(
            receipt_lookup(flavor, write),
            DbCountExpectation::exactly(1),
        ),
    ]);
    Ok(steps)
}

fn create_workspace_statements(
    flavor: DbSqlFlavor,
    write: &TaskSessionWrite,
    create: &TaskSessionWorkspaceCreate,
) -> Vec<DbStatement> {
    let profile_metadata = create.metadata.to_string();
    vec![
        DbStatementBuilder::new(flavor)
            .push_static("INSERT INTO bcs_groups (group_id, label, status, driver_bot, originator, env, context, created_by, visibility) VALUES (")
            .bind(create.group_id.as_str()).push_static(", ").bind(create.name.as_str())
            .push_static(", 'active', ").bind(write.actor_id.as_str()).push_static(", ")
            .bind(write.actor_id.as_str()).push_static(", 'memstack', ")
            .bind(create.description.as_deref()).push_static(", ").bind(write.actor_id.as_str())
            .push_static(", 'private')").build(),
        DbStatementBuilder::new(flavor)
            .push_static("INSERT INTO workspace_profiles (workspace_id, tenant_id, project_id, group_id, name, description, created_by, metadata_json) VALUES (")
            .bind(write.workspace_id.as_str()).push_static(", ").bind(write.tenant_id.as_str())
            .push_static(", ").bind(write.project_id.as_str()).push_static(", ")
            .bind(create.group_id.as_str()).push_static(", ").bind(create.name.as_str())
            .push_static(", ").bind(create.description.as_deref()).push_static(", ")
            .bind(write.actor_id.as_str()).push_static(", ").bind(profile_metadata).push_static(")").build(),
        DbStatementBuilder::new(flavor)
            .push_static("INSERT INTO workspace_members (member_id, tenant_id, project_id, workspace_id, user_id, participant_actor_id, role, invited_by) VALUES (")
            .bind(create.owner_member_id.as_str()).push_static(", ").bind(write.tenant_id.as_str())
            .push_static(", ").bind(write.project_id.as_str()).push_static(", ")
            .bind(write.workspace_id.as_str()).push_static(", ").bind(write.actor_id.as_str())
            .push_static(", ").bind(write.actor_id.as_str()).push_static(", 'owner', ")
            .bind(write.actor_id.as_str()).push_static(")").build(),
        DbStatementBuilder::new(flavor)
            .push_static("INSERT INTO workspace_principal_identities (tenant_id, project_id, workspace_id, user_id, participant_actor_id, email, display_name, is_active, identity_authority, source_created_at, source_updated_at) VALUES (")
            .bind(write.tenant_id.as_str()).push_static(", ").bind(write.project_id.as_str())
            .push_static(", ").bind(write.workspace_id.as_str()).push_static(", ")
            .bind(write.actor_id.as_str()).push_static(", ").bind(write.actor_id.as_str())
            .push_static(", ").bind(write.actor_email.as_str())
            .push_static(", NULL, TRUE, 'memstack', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)").build(),
        DbStatementBuilder::new(flavor)
            .push_static("INSERT INTO bcs_group_participants (group_id, bot_uuid, role, env, actor_kind, mode) VALUES (")
            .bind(create.group_id.as_str()).push_static(", ").bind(write.actor_id.as_str())
            .push_static(", 'owner', 'memstack', 'human', 'auto')").build(),
        DbStatementBuilder::new(flavor)
            .push_static("INSERT INTO workspace_authorities (workspace_id, tenant_id, project_id, revision) VALUES (")
            .bind(write.workspace_id.as_str()).push_static(", ").bind(write.tenant_id.as_str())
            .push_static(", ").bind(write.project_id.as_str()).push_static(", 1)").build(),
        workspace_created_outbox(flavor, write, create),
    ]
}

fn project_access(flavor: DbSqlFlavor, write: &TaskSessionWrite) -> DbStatement {
    if write.actor_is_superuser {
        return DbStatement::new("SELECT 1 AS allowed");
    }
    DbStatementBuilder::new(flavor)
        .push_static("SELECT user_id FROM project_principal_memberships WHERE tenant_id = ")
        .bind(write.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(write.project_id.as_str())
        .push_static(" AND user_id = ")
        .bind(write.actor_id.as_str())
        .push_static(" AND participant_actor_id = ")
        .bind(write.actor_id.as_str())
        .push_static(" AND is_active = TRUE")
        .build()
}

fn workspace_absent(
    flavor: DbSqlFlavor,
    write: &TaskSessionWrite,
    create: &TaskSessionWorkspaceCreate,
) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("SELECT workspace_id FROM workspace_profiles WHERE workspace_id = ")
        .bind(write.workspace_id.as_str())
        .push_static(" OR group_id = ")
        .bind(create.group_id.as_str())
        .build()
}

fn workspace_access(flavor: DbSqlFlavor, write: &TaskSessionWrite, manager: bool) -> DbStatement {
    if write.actor_is_superuser {
        return DbStatementBuilder::new(flavor)
            .push_static("SELECT workspace_id FROM workspace_profiles WHERE tenant_id = ")
            .bind(write.tenant_id.as_str())
            .push_static(" AND project_id = ")
            .bind(write.project_id.as_str())
            .push_static(" AND workspace_id = ")
            .bind(write.workspace_id.as_str())
            .push_static(" AND deleted_at IS NULL")
            .build();
    }
    let workspace_roles = if manager {
        " AND m.role IN ('owner', 'editor')"
    } else {
        ""
    };
    let project_roles = if manager {
        " AND pm.role IN ('owner', 'admin')"
    } else {
        ""
    };
    DbStatementBuilder::new(flavor)
        .push_static("SELECT p.workspace_id FROM workspace_profiles p WHERE p.tenant_id = ")
        .bind(write.tenant_id.as_str())
        .push_static(" AND p.project_id = ").bind(write.project_id.as_str())
        .push_static(" AND p.workspace_id = ").bind(write.workspace_id.as_str())
        .push_static(" AND p.deleted_at IS NULL AND (p.created_by = ")
        .bind(write.actor_id.as_str())
        .push_static(" OR EXISTS (SELECT 1 FROM workspace_members m WHERE m.tenant_id = p.tenant_id AND m.project_id = p.project_id AND m.workspace_id = p.workspace_id AND m.user_id = ")
        .bind(write.actor_id.as_str())
        .push_static(workspace_roles)
        .push_static(") OR EXISTS (SELECT 1 FROM project_principal_memberships pm WHERE pm.tenant_id = p.tenant_id AND pm.project_id = p.project_id AND pm.user_id = ")
        .bind(write.actor_id.as_str())
        .push_static(" AND pm.is_active = TRUE")
        .push_static(project_roles)
        .push_static("))")
        .build()
}

fn authority_revision_check(flavor: DbSqlFlavor, write: &TaskSessionWrite) -> DbStatement {
    let builder = DbStatementBuilder::new(flavor)
        .push_static("SELECT revision FROM workspace_authorities WHERE tenant_id = ")
        .bind(write.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(write.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(write.workspace_id.as_str())
        .push_static(" AND revision = ")
        .bind(write.expected_authority_revision);
    match flavor {
        DbSqlFlavor::Postgres | DbSqlFlavor::Mysql => builder.push_static(" FOR UPDATE").build(),
        DbSqlFlavor::Sqlite => builder.build(),
    }
}

fn authority_revision_update(flavor: DbSqlFlavor, write: &TaskSessionWrite) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("UPDATE workspace_authorities SET revision = ")
        .bind(write.committed_authority_revision)
        .push_static(", updated_at = ")
        .push_static(flavor.now())
        .push_static(" WHERE tenant_id = ")
        .bind(write.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(write.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(write.workspace_id.as_str())
        .push_static(" AND revision = ")
        .bind(write.expected_authority_revision)
        .build()
}

fn policy_upsert(
    flavor: DbSqlFlavor,
    write: &TaskSessionWrite,
    policy: &TaskSessionPolicyWrite,
) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("INSERT INTO workspace_agent_policies (workspace_id, tenant_id, project_id, revision, roles_json, fallbacks_json, reasoning_effort, permission_mode, updated_by, created_at, updated_at) SELECT ")
        .bind(write.workspace_id.as_str()).push_static(", ").bind(write.tenant_id.as_str())
        .push_static(", ").bind(write.project_id.as_str()).push_static(", ")
        .bind(policy.committed_revision).push_static(", ").bind(policy.roles.to_string())
        .push_static(", '[]', ").bind(policy.reasoning_effort.as_str()).push_static(", ")
        .bind(policy.permission_mode.as_str()).push_static(", ").bind(write.actor_id.as_str())
        .push_static(", ").bind(policy.updated_at.as_str()).push_static(", ")
        .bind(policy.updated_at.as_str()).push_static(" WHERE ").bind(policy.expected_revision)
        .push_static(" = 0 OR EXISTS (SELECT 1 FROM workspace_agent_policies WHERE workspace_id = ")
        .bind(write.workspace_id.as_str())
        .push_static(") ON CONFLICT(workspace_id) DO UPDATE SET revision = excluded.revision, roles_json = excluded.roles_json, fallbacks_json = excluded.fallbacks_json, reasoning_effort = excluded.reasoning_effort, permission_mode = excluded.permission_mode, updated_by = excluded.updated_by, updated_at = excluded.updated_at WHERE workspace_agent_policies.revision = ")
        .bind(policy.expected_revision).build()
}

fn message_session_insert(flavor: DbSqlFlavor, write: &TaskSessionWrite) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("INSERT INTO bcs_group_sessions (session_id, group_id, env, status, session_kind, caller_id, caller_principal, created_by, participants, current_msg_seq, meta) SELECT ")
        .bind(write.conversation_id.as_str()).push_static(", p.group_id, 'memstack', 'running', 'chat', ")
        .bind(write.actor_id.as_str()).push_static(", ").bind(write.actor_id.as_str())
        .push_static(", ").bind(write.actor_id.as_str())
        .push_static(", '[]', 0, '{\"authority\":\"memstack-workspace\"}' FROM workspace_profiles p WHERE p.workspace_id = ")
        .bind(write.workspace_id.as_str()).push_static(" ON CONFLICT(env, session_id) DO NOTHING").build()
}

fn message_session_scope(flavor: DbSqlFlavor, write: &TaskSessionWrite) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "SELECT s.session_id FROM bcs_group_sessions s JOIN workspace_profiles p ON \
             p.group_id = s.group_id WHERE s.env = 'memstack' AND s.session_id = ",
        )
        .bind(write.conversation_id.as_str())
        .push_static(" AND p.tenant_id = ")
        .bind(write.tenant_id.as_str())
        .push_static(" AND p.project_id = ")
        .bind(write.project_id.as_str())
        .push_static(" AND p.workspace_id = ")
        .bind(write.workspace_id.as_str())
        .build()
}

fn message_session_increment(flavor: DbSqlFlavor, write: &TaskSessionWrite) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("UPDATE bcs_group_sessions SET current_msg_seq = current_msg_seq + 1 WHERE env = 'memstack' AND session_id = ")
        .bind(write.conversation_id.as_str()).push_static(" AND current_msg_seq = 0").build()
}

fn message_insert(flavor: DbSqlFlavor, write: &TaskSessionWrite) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("INSERT INTO bcs_messages (message_id, group_id, session_id, session_seq, env, sender_id, sender_type, message_type, content, client_msg_id, status, created_at, run_id, workspace_id, mentions_json, parent_message_id, metadata_json, source_hash) SELECT ")
        .bind(write.message_id.as_str()).push_static(", p.group_id, ")
        .bind(write.conversation_id.as_str()).push_static(", s.current_msg_seq, 'memstack', ")
        .bind(write.actor_id.as_str()).push_static(", 'human', 'workspace_chat', ")
        .bind(write.message_content_json.as_str()).push_static(", ")
        .bind(write.idempotency_key.as_str()).push_static(", 'normal', ")
        .bind(write.message_created_at_ms).push_static(", '', ").bind(write.workspace_id.as_str())
        .push_static(", '[]', NULL, ").bind(write.message_metadata_json.as_str())
        .push_static(", ").bind(write.payload_hash.as_str())
        .push_static(" FROM workspace_profiles p JOIN bcs_group_sessions s ON s.env = 'memstack' AND s.session_id = ")
        .bind(write.conversation_id.as_str()).push_static(" WHERE p.workspace_id = ")
        .bind(write.workspace_id.as_str()).build()
}

fn message_correlation_insert(flavor: DbSqlFlavor, write: &TaskSessionWrite) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("INSERT INTO workspace_message_correlations (correlation_id, tenant_id, project_id, workspace_id, legacy_message_id, conversation_id, bcs_session_id, bcs_message_id, message_kind, is_terminal, idempotency_key, request_hash, event_outbox_id) VALUES (")
        .bind(format!("task-session:{}", write.receipt_id)).push_static(", ")
        .bind(write.tenant_id.as_str()).push_static(", ").bind(write.project_id.as_str())
        .push_static(", ").bind(write.workspace_id.as_str()).push_static(", ")
        .bind(write.message_id.as_str()).push_static(", ").bind(write.conversation_id.as_str())
        .push_static(", ").bind(write.conversation_id.as_str()).push_static(", ")
        .bind(write.message_id.as_str()).push_static(", 'workspace_chat', FALSE, ")
        .bind(format!("task-session-message:{}", write.idempotency_key)).push_static(", ")
        .bind(write.payload_hash.as_str()).push_static(", ")
        .bind(format!("task-session-message-outbox:{}", write.receipt_id)).push_static(")").build()
}

fn workspace_created_outbox(
    flavor: DbSqlFlavor,
    write: &TaskSessionWrite,
    create: &TaskSessionWorkspaceCreate,
) -> DbStatement {
    let payload = serde_json::json!({
        "workspace_id": write.workspace_id,
        "user_id": write.actor_id,
        "role": "owner",
        "source": "task_session",
    });
    DbStatementBuilder::new(flavor)
        .push_static("INSERT INTO workspace_outbox (outbox_id, tenant_id, project_id, workspace_id, aggregate_type, aggregate_id, event_type, stream_name, event_sequence, payload_json, metadata_json, correlation_id, idempotency_key) VALUES (")
        .bind(format!("task-session-workspace-outbox:{}", write.receipt_id)).push_static(", ")
        .bind(write.tenant_id.as_str()).push_static(", ").bind(write.project_id.as_str())
        .push_static(", ").bind(write.workspace_id.as_str())
        .push_static(", 'workspace', ").bind(write.workspace_id.as_str())
        .push_static(", 'workspace_member_joined', ").bind(format!("workspace:{}", write.workspace_id))
        .push_static(", 1, ").bind(payload.to_string()).push_static(", ")
        .bind(serde_json::json!({"source":"task_session","group_id":create.group_id}).to_string())
        .push_static(", ").bind(write.receipt_id.as_str()).push_static(", ")
        .bind(format!("task-session-workspace:{}", write.idempotency_key)).push_static(")").build()
}

fn message_outbox_insert(flavor: DbSqlFlavor, write: &TaskSessionWrite) -> DbStatement {
    let payload = serde_json::json!({
        "message": {
            "id": write.message_id,
            "workspace_id": write.workspace_id,
            "sender_id": write.actor_id,
            "sender_type": "human",
        }
    });
    DbStatementBuilder::new(flavor)
        .push_static("INSERT INTO workspace_outbox (outbox_id, tenant_id, project_id, workspace_id, aggregate_type, aggregate_id, event_type, stream_name, event_sequence, payload_json, metadata_json, correlation_id, idempotency_key) VALUES (")
        .bind(format!("task-session-message-outbox:{}", write.receipt_id)).push_static(", ")
        .bind(write.tenant_id.as_str()).push_static(", ").bind(write.project_id.as_str())
        .push_static(", ").bind(write.workspace_id.as_str())
        .push_static(", 'workspace_message', ").bind(write.message_id.as_str())
        .push_static(", 'workspace_message_created', ").bind(format!("workspace:{}:events", write.workspace_id))
        .push_static(", COALESCE((SELECT MAX(event_sequence) + 1 FROM workspace_outbox WHERE ")
        .push_static("workspace_id = ").bind(write.workspace_id.as_str())
        .push_static(" AND stream_name = ")
        .bind(format!("workspace:{}:events", write.workspace_id))
        .push_static(" AND event_sequence >= ").bind(MESSAGE_EVENT_SEQUENCE_BASE)
        .push_static("), ").bind(MESSAGE_EVENT_SEQUENCE_BASE + 1).push_static("), ")
        .bind(payload.to_string()).push_static(", '{\"source\":\"task_session\"}', ")
        .bind(write.receipt_id.as_str()).push_static(", ")
        .bind(format!("task-session-message-event:{}", write.idempotency_key)).push_static(")").build()
}

fn receipt_insert(
    flavor: DbSqlFlavor,
    write: &TaskSessionWrite,
) -> Result<DbStatement, TaskSessionStoreError> {
    let response =
        serde_json::to_string(&write.response).map_err(TaskSessionStoreError::InvalidResponse)?;
    Ok(DbStatementBuilder::new(flavor)
        .push_static("INSERT INTO workspace_task_receipts (receipt_id, tenant_id, project_id, workspace_id, task_id, actor_id, action, idempotency_key, payload_hash, expected_revision, committed_revision, result_json, committed_at) VALUES (")
        .bind(write.receipt_id.as_str()).push_static(", ").bind(write.tenant_id.as_str())
        .push_static(", ").bind(write.project_id.as_str()).push_static(", ")
        .bind(write.workspace_id.as_str()).push_static(", NULL, ").bind(write.actor_id.as_str())
        .push_static(", 'create_task_session', ").bind(write.idempotency_key.as_str())
        .push_static(", ").bind(write.payload_hash.as_str()).push_static(", ")
        .bind(write.expected_authority_revision).push_static(", ")
        .bind(write.committed_authority_revision).push_static(", ")
        .bind(response).push_static(", CURRENT_TIMESTAMP)").build())
}

fn receipt_lookup(flavor: DbSqlFlavor, write: &TaskSessionWrite) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("SELECT receipt_id, payload_hash, committed_revision, result_json FROM workspace_task_receipts WHERE tenant_id = ")
        .bind(write.tenant_id.as_str()).push_static(" AND project_id = ")
        .bind(write.project_id.as_str()).push_static(" AND actor_id = ")
        .bind(write.actor_id.as_str()).push_static(" AND idempotency_key = ")
        .bind(write.idempotency_key.as_str()).push_static(" AND action = 'create_task_session'").build()
}

fn outcome_from_results(
    results: &[DbTransactionStepResult],
    expected_hash: &str,
    replayed: bool,
) -> Result<TaskSessionWriteOutcome, TaskSessionStoreError> {
    let Some(DbTransactionStepResult::Rows(rows)) = results.last() else {
        return Err(TaskSessionStoreError::InvalidReceipt("final receipt query"));
    };
    let row = rows
        .first()
        .ok_or(TaskSessionStoreError::IncompleteReceipt)?;
    outcome_from_row(row, expected_hash, replayed)
}

fn outcome_from_row(
    row: &DbRow,
    expected_hash: &str,
    replayed: bool,
) -> Result<TaskSessionWriteOutcome, TaskSessionStoreError> {
    let payload_hash = row
        .get_string("payload_hash")?
        .ok_or(TaskSessionStoreError::InvalidReceipt("payload_hash"))?;
    if payload_hash != expected_hash {
        return Err(TaskSessionStoreError::IdempotencyConflict);
    }
    if row.get_i64("committed_revision")?.is_none() {
        return Err(TaskSessionStoreError::IncompleteReceipt);
    }
    let receipt_id = row
        .get_string("receipt_id")?
        .ok_or(TaskSessionStoreError::InvalidReceipt("receipt_id"))?;
    let raw = row
        .get_string("result_json")?
        .ok_or(TaskSessionStoreError::InvalidReceipt("result_json"))?;
    let response = serde_json::from_str(&raw).map_err(TaskSessionStoreError::InvalidResponse)?;
    Ok(TaskSessionWriteOutcome {
        receipt_id,
        response,
        replayed,
    })
}
