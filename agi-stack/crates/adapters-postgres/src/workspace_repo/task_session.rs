use serde_json::{json, Value};
use sqlx::types::Json;
use sqlx::{Postgres, Transaction};

use super::{
    row_to_workspace, CreateTaskSessionRecord, PgWorkspaceRepository, TaskSessionCreationOutcome,
    TaskSessionRepositoryError, TaskSessionWorkspaceRecord, WorkspaceRecord, WORKSPACE_COLS,
};

type TaskSessionResult<T> = Result<T, TaskSessionRepositoryError>;
type ReceiptRow = (String, String, Option<String>, Option<String>, Json<Value>);

const LOCK_TENANT_SCOPE_SQL: &str = "SELECT id FROM tenants \
     WHERE id = $1 \
     FOR SHARE";
const LOCK_PROJECT_SCOPE_SQL: &str = "SELECT owner_id FROM projects \
     WHERE id = $1 AND tenant_id = $2 \
     FOR SHARE";
const LOCK_PROJECT_MEMBERSHIP_SQL: &str = "SELECT role FROM user_projects \
     WHERE project_id = $1 AND user_id = $2 \
     FOR SHARE";
#[cfg(test)]
const AUTHORIZATION_LOCK_QUERIES: [(&str, &str); 3] = [
    ("tenant", LOCK_TENANT_SCOPE_SQL),
    ("project", LOCK_PROJECT_SCOPE_SQL),
    ("user_project", LOCK_PROJECT_MEMBERSHIP_SQL),
];

const LOAD_RECEIPT_SQL: &str =
    "SELECT payload_hash, workspace_id, conversation_id, initial_message_id, response_json \
     FROM task_session_creation_receipts \
     WHERE actor_user_id = $1 AND tenant_id = $2 AND project_id = $3 \
       AND idempotency_key = $4 \
     LIMIT 1";
const LOCK_RECEIPT_SQL: &str =
    "SELECT payload_hash, workspace_id, conversation_id, initial_message_id, response_json \
     FROM task_session_creation_receipts \
     WHERE actor_user_id = $1 AND tenant_id = $2 AND project_id = $3 \
       AND idempotency_key = $4 \
     LIMIT 1 \
     FOR SHARE";

impl PgWorkspaceRepository {
    /// Atomically create a workspace-backed conversation, initial message,
    /// blackboard outbox event, and durable idempotency receipt.
    ///
    /// # Errors
    ///
    /// Returns a stable [`TaskSessionRepositoryError`] for invalid input,
    /// authorization failures, idempotency conflicts, or PostgreSQL failures.
    pub async fn create_task_session(
        &self,
        record: CreateTaskSessionRecord,
    ) -> TaskSessionResult<TaskSessionCreationOutcome> {
        validate_record(&record)?;
        let mut transaction = self.pool.begin().await.map_err(storage)?;
        require_project_write_access(&mut transaction, &record).await?;
        lock_idempotency_scope(&mut transaction, &record).await?;

        if let Some(initial_receipt) = load_receipt(&mut transaction, &record).await? {
            if initial_receipt.0 != record.payload_hash {
                return Err(TaskSessionRepositoryError::IdempotencyConflict);
            }
            load_existing_workspace(
                &mut transaction,
                &initial_receipt.1,
                &record.actor_user_id,
                &record.tenant_id,
                &record.project_id,
            )
            .await?;
            let locked_receipt = lock_receipt(&mut transaction, &record).await?;
            let receipt = require_unchanged_receipt(&initial_receipt, locked_receipt)?;
            let (payload_hash, workspace_id, conversation_id, initial_message_id, snapshot) =
                require_replayable_receipt(receipt)?;
            debug_assert_eq!(payload_hash, record.payload_hash);
            let outcome = outcome_from_receipt(
                snapshot,
                &workspace_id,
                &conversation_id,
                &initial_message_id,
                &record.tenant_id,
                &record.project_id,
            )?;
            transaction.commit().await.map_err(storage)?;
            return Ok(outcome);
        }

        let workspace = resolve_workspace(&mut transaction, &record).await?;
        let workspace_json = workspace_json(&workspace);
        let capability_mode = record.conversation.capability_mode.as_str();
        let agent_config = json!({
            "selected_agent_id": "builtin:all-access",
            "capability_mode": capability_mode,
        });
        let conversation_metadata = json!({
            "runtime": "cloud",
            "source": "task_session",
            "capability_mode": capability_mode,
            "workspace_id": workspace.id,
            "environment": { "kind": "cloud", "label": "Cloud runtime" },
        });
        insert_conversation(
            &mut transaction,
            &record,
            &workspace,
            &agent_config,
            &conversation_metadata,
        )
        .await?;
        let conversation_json =
            conversation_json(&record, &workspace, agent_config, conversation_metadata);

        let message_metadata = json!({
            "runtime": "cloud",
            "source": "task_session",
            "conversation_id": record.conversation.id,
        });
        let initial_message_json = initial_message_json(&record, &workspace, message_metadata);
        insert_initial_message(&mut transaction, &record, &workspace, &initial_message_json)
            .await?;
        insert_blackboard_outbox(&mut transaction, &record, &workspace, &initial_message_json)
            .await?;

        let response_json = json!({
            "workspace": workspace_json,
            "conversation": conversation_json,
            "initial_message": initial_message_json,
        });
        insert_receipt(&mut transaction, &record, &workspace, &response_json).await?;
        transaction.commit().await.map_err(storage)?;
        outcome_from_snapshot(response_json, false)
    }
}

fn validate_record(record: &CreateTaskSessionRecord) -> TaskSessionResult<()> {
    for value in [
        record.receipt_id.as_str(),
        record.actor_user_id.as_str(),
        record.tenant_id.as_str(),
        record.project_id.as_str(),
        record.conversation.id.as_str(),
        record.initial_message_id.as_str(),
        record.blackboard_outbox_id.as_str(),
    ] {
        require_identifier(value)?;
    }
    require_normalized_text(&record.idempotency_key, 255)?;
    require_normalized_text(&record.conversation.title, 255)?;
    require_normalized_text(&record.initial_message_content, 100_000)?;
    if record.payload_hash.len() != 64
        || !record
            .payload_hash
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit())
    {
        return Err(TaskSessionRepositoryError::InvalidInput);
    }
    match &record.workspace {
        TaskSessionWorkspaceRecord::Create {
            workspace,
            owner_member_id,
        } => {
            require_identifier(&workspace.id)?;
            require_identifier(owner_member_id)?;
            require_normalized_text(&workspace.name, 255)?;
            if workspace.tenant_id != record.tenant_id
                || workspace.project_id != record.project_id
                || workspace.created_by != record.actor_user_id
                || workspace.is_archived
                || !workspace.metadata_json.is_object()
                || !workspace.hex_layout_config_json.is_object()
            {
                return Err(TaskSessionRepositoryError::InvalidInput);
            }
        }
        TaskSessionWorkspaceRecord::Existing { workspace_id } => {
            require_identifier(workspace_id)?;
        }
    }
    Ok(())
}

fn require_identifier(value: &str) -> TaskSessionResult<()> {
    if value.is_empty() || value.trim() != value || value.chars().count() > 255 {
        Err(TaskSessionRepositoryError::InvalidInput)
    } else {
        Ok(())
    }
}

fn require_normalized_text(value: &str, max_length: usize) -> TaskSessionResult<()> {
    if value.is_empty() || value.trim() != value || value.chars().count() > max_length {
        Err(TaskSessionRepositoryError::InvalidInput)
    } else {
        Ok(())
    }
}

async fn require_project_write_access(
    transaction: &mut Transaction<'_, Postgres>,
    record: &CreateTaskSessionRecord,
) -> TaskSessionResult<()> {
    // Match tenant deletion's parent-to-child lock order before either fresh
    // creation or receipt replay can touch workspace-scoped rows.
    sqlx::query_scalar::<_, String>(LOCK_TENANT_SCOPE_SQL)
        .bind(&record.tenant_id)
        .fetch_optional(&mut **transaction)
        .await
        .map_err(storage)?
        .ok_or(TaskSessionRepositoryError::ProjectAccessDenied)?;

    let owner_id = sqlx::query_scalar::<_, String>(LOCK_PROJECT_SCOPE_SQL)
        .bind(&record.project_id)
        .bind(&record.tenant_id)
        .fetch_optional(&mut **transaction)
        .await
        .map_err(storage)?
        .ok_or(TaskSessionRepositoryError::ProjectAccessDenied)?;
    let roles = sqlx::query_scalar::<_, String>(LOCK_PROJECT_MEMBERSHIP_SQL)
        .bind(&record.project_id)
        .bind(&record.actor_user_id)
        .fetch_all(&mut **transaction)
        .await
        .map_err(storage)?;
    if owner_id == record.actor_user_id || has_project_write_role(&roles) {
        Ok(())
    } else {
        Err(TaskSessionRepositoryError::ProjectAccessDenied)
    }
}

fn has_project_write_role(roles: &[String]) -> bool {
    roles
        .iter()
        .any(|role| matches!(role.as_str(), "owner" | "admin" | "member" | "editor"))
}

fn has_workspace_write_role(roles: &[String]) -> bool {
    roles
        .iter()
        .any(|role| matches!(role.as_str(), "owner" | "admin" | "editor"))
}

async fn lock_idempotency_scope(
    transaction: &mut Transaction<'_, Postgres>,
    record: &CreateTaskSessionRecord,
) -> TaskSessionResult<()> {
    let scope_key = format!(
        "task-session:{}:{}:{}:{}",
        record.actor_user_id, record.tenant_id, record.project_id, record.idempotency_key
    );
    sqlx::query("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))")
        .bind(scope_key)
        .execute(&mut **transaction)
        .await
        .map_err(storage)?;
    Ok(())
}

async fn load_receipt(
    transaction: &mut Transaction<'_, Postgres>,
    record: &CreateTaskSessionRecord,
) -> TaskSessionResult<Option<ReceiptRow>> {
    fetch_receipt(transaction, record, LOAD_RECEIPT_SQL).await
}

async fn lock_receipt(
    transaction: &mut Transaction<'_, Postgres>,
    record: &CreateTaskSessionRecord,
) -> TaskSessionResult<Option<ReceiptRow>> {
    fetch_receipt(transaction, record, LOCK_RECEIPT_SQL).await
}

async fn fetch_receipt(
    transaction: &mut Transaction<'_, Postgres>,
    record: &CreateTaskSessionRecord,
    query: &str,
) -> TaskSessionResult<Option<ReceiptRow>> {
    sqlx::query_as::<_, ReceiptRow>(query)
        .bind(&record.actor_user_id)
        .bind(&record.tenant_id)
        .bind(&record.project_id)
        .bind(&record.idempotency_key)
        .fetch_optional(&mut **transaction)
        .await
        .map_err(storage)
}

fn require_unchanged_receipt(
    initial: &ReceiptRow,
    locked: Option<ReceiptRow>,
) -> TaskSessionResult<ReceiptRow> {
    match locked {
        Some(locked) if &locked == initial => Ok(locked),
        _ => Err(TaskSessionRepositoryError::IdempotencyConflict),
    }
}

fn require_replayable_receipt(
    receipt: ReceiptRow,
) -> TaskSessionResult<(String, String, String, String, Value)> {
    let (payload_hash, workspace_id, conversation_id, initial_message_id, Json(snapshot)) = receipt;
    let (Some(conversation_id), Some(initial_message_id)) = (conversation_id, initial_message_id)
    else {
        return Err(TaskSessionRepositoryError::IdempotencyConflict);
    };
    Ok((
        payload_hash,
        workspace_id,
        conversation_id,
        initial_message_id,
        snapshot,
    ))
}

async fn resolve_workspace(
    transaction: &mut Transaction<'_, Postgres>,
    record: &CreateTaskSessionRecord,
) -> TaskSessionResult<WorkspaceRecord> {
    match &record.workspace {
        TaskSessionWorkspaceRecord::Create {
            workspace,
            owner_member_id,
        } => insert_workspace(transaction, workspace, owner_member_id).await,
        TaskSessionWorkspaceRecord::Existing { workspace_id } => {
            load_existing_workspace(
                transaction,
                workspace_id,
                &record.actor_user_id,
                &record.tenant_id,
                &record.project_id,
            )
            .await
        }
    }
}

async fn insert_workspace(
    transaction: &mut Transaction<'_, Postgres>,
    workspace: &WorkspaceRecord,
    owner_member_id: &str,
) -> TaskSessionResult<WorkspaceRecord> {
    let row = sqlx::query(&format!(
        "INSERT INTO workspaces \
            (id, tenant_id, project_id, name, description, created_by, is_archived, \
             metadata_json, office_status, hex_layout_config_json, \
             default_blocking_categories_json, created_at, updated_at) \
         VALUES ($1,$2,$3,$4,$5,$6,false,$7,$8,$9,$10,$11,$12) \
         RETURNING {WORKSPACE_COLS}"
    ))
    .bind(&workspace.id)
    .bind(&workspace.tenant_id)
    .bind(&workspace.project_id)
    .bind(&workspace.name)
    .bind(&workspace.description)
    .bind(&workspace.created_by)
    .bind(Json(&workspace.metadata_json))
    .bind(&workspace.office_status)
    .bind(Json(&workspace.hex_layout_config_json))
    .bind(Json(&workspace.default_blocking_categories_json))
    .bind(workspace.created_at)
    .bind(workspace.updated_at)
    .fetch_one(&mut **transaction)
    .await
    .map_err(workspace_insert_error)?;

    sqlx::query(
        "INSERT INTO workspace_members \
            (id, workspace_id, user_id, role, invited_by, created_at, updated_at) \
         VALUES ($1, $2, $3, 'owner', $3, $4, NULL)",
    )
    .bind(owner_member_id)
    .bind(&workspace.id)
    .bind(&workspace.created_by)
    .bind(workspace.created_at)
    .execute(&mut **transaction)
    .await
    .map_err(storage)?;
    row_to_workspace(row).map_err(core_storage)
}

async fn load_existing_workspace(
    transaction: &mut Transaction<'_, Postgres>,
    workspace_id: &str,
    actor_user_id: &str,
    tenant_id: &str,
    project_id: &str,
) -> TaskSessionResult<WorkspaceRecord> {
    let row = sqlx::query(&format!(
        "SELECT {WORKSPACE_COLS} FROM workspaces \
         WHERE id = $1 AND tenant_id = $2 AND project_id = $3 AND is_archived = false \
         FOR SHARE"
    ))
    .bind(workspace_id)
    .bind(tenant_id)
    .bind(project_id)
    .fetch_optional(&mut **transaction)
    .await
    .map_err(storage)?
    .ok_or(TaskSessionRepositoryError::WorkspaceNotFound)?;

    let roles = sqlx::query_scalar::<_, String>(
        "SELECT role FROM workspace_members \
         WHERE workspace_id = $1 AND user_id = $2 \
         FOR SHARE",
    )
    .bind(workspace_id)
    .bind(actor_user_id)
    .fetch_all(&mut **transaction)
    .await
    .map_err(storage)?;
    if !has_workspace_write_role(&roles) {
        return Err(TaskSessionRepositoryError::WorkspaceAccessDenied);
    }
    row_to_workspace(row).map_err(core_storage)
}

async fn insert_conversation(
    transaction: &mut Transaction<'_, Postgres>,
    record: &CreateTaskSessionRecord,
    workspace: &WorkspaceRecord,
    agent_config: &Value,
    metadata: &Value,
) -> TaskSessionResult<()> {
    sqlx::query(
        "INSERT INTO conversations \
            (id, project_id, tenant_id, user_id, title, status, agent_config, meta, \
             message_count, current_mode, merge_strategy, participant_agents, \
             conversation_mode, workspace_id, created_at, updated_at) \
         VALUES ($1,$2,$3,$4,$5,'active',$6,$7,0,'plan','result_only',$8, \
                 'workspace',$9,$10,$10)",
    )
    .bind(&record.conversation.id)
    .bind(&record.project_id)
    .bind(&record.tenant_id)
    .bind(&record.actor_user_id)
    .bind(&record.conversation.title)
    .bind(Json(agent_config))
    .bind(Json(metadata))
    .bind(Json(Vec::<String>::new()))
    .bind(&workspace.id)
    .bind(record.created_at)
    .execute(&mut **transaction)
    .await
    .map_err(storage)?;
    Ok(())
}

async fn insert_initial_message(
    transaction: &mut Transaction<'_, Postgres>,
    record: &CreateTaskSessionRecord,
    workspace: &WorkspaceRecord,
    initial_message_json: &Value,
) -> TaskSessionResult<()> {
    let metadata = initial_message_json
        .get("metadata")
        .cloned()
        .ok_or_else(corrupt_snapshot)?;
    sqlx::query(
        "INSERT INTO workspace_messages \
            (id, workspace_id, sender_id, sender_type, content, mentions_json, \
             parent_message_id, metadata_json, created_at) \
         VALUES ($1,$2,$3,'human',$4,$5,NULL,$6,$7)",
    )
    .bind(&record.initial_message_id)
    .bind(&workspace.id)
    .bind(&record.actor_user_id)
    .bind(&record.initial_message_content)
    .bind(Json(Vec::<String>::new()))
    .bind(Json(metadata))
    .bind(record.created_at)
    .execute(&mut **transaction)
    .await
    .map_err(storage)?;
    Ok(())
}

async fn insert_blackboard_outbox(
    transaction: &mut Transaction<'_, Postgres>,
    record: &CreateTaskSessionRecord,
    workspace: &WorkspaceRecord,
    initial_message_json: &Value,
) -> TaskSessionResult<()> {
    let payload = json!({ "message": initial_message_json });
    let metadata = json!({
        "tenant_id": record.tenant_id,
        "project_id": record.project_id,
        "surface_owner": "workspace-chat",
        "surface_boundary": "hosted",
        "authority_class": "non-authoritative",
        "signal_role": "sensing-capable",
    });
    sqlx::query(
        "INSERT INTO workspace_blackboard_outbox \
            (id, workspace_id, tenant_id, project_id, event_type, payload_json, metadata_json, \
             correlation_id, status, attempt_count, max_attempts, created_at, updated_at) \
         VALUES ($1,$2,$3,$4,'workspace_message_created',$5,$6,NULL,'pending',0,10,$7,NULL)",
    )
    .bind(&record.blackboard_outbox_id)
    .bind(&workspace.id)
    .bind(&record.tenant_id)
    .bind(&record.project_id)
    .bind(Json(payload))
    .bind(Json(metadata))
    .bind(record.created_at)
    .execute(&mut **transaction)
    .await
    .map_err(storage)?;
    Ok(())
}

async fn insert_receipt(
    transaction: &mut Transaction<'_, Postgres>,
    record: &CreateTaskSessionRecord,
    workspace: &WorkspaceRecord,
    response_json: &Value,
) -> TaskSessionResult<()> {
    sqlx::query(
        "INSERT INTO task_session_creation_receipts \
            (id, actor_user_id, tenant_id, project_id, idempotency_key, payload_hash, \
             workspace_id, conversation_id, initial_message_id, response_json, created_at) \
         VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)",
    )
    .bind(&record.receipt_id)
    .bind(&record.actor_user_id)
    .bind(&record.tenant_id)
    .bind(&record.project_id)
    .bind(&record.idempotency_key)
    .bind(&record.payload_hash)
    .bind(&workspace.id)
    .bind(&record.conversation.id)
    .bind(&record.initial_message_id)
    .bind(Json(response_json))
    .bind(record.created_at)
    .execute(&mut **transaction)
    .await
    .map_err(storage)?;
    Ok(())
}

fn workspace_json(workspace: &WorkspaceRecord) -> Value {
    json!({
        "id": workspace.id,
        "tenant_id": workspace.tenant_id,
        "project_id": workspace.project_id,
        "name": workspace.name,
        "created_by": workspace.created_by,
        "description": workspace.description,
        "is_archived": workspace.is_archived,
        "metadata": workspace.metadata_json,
        "office_status": workspace.office_status,
        "hex_layout_config": workspace.hex_layout_config_json,
        "created_at": workspace.created_at.to_rfc3339(),
        "updated_at": workspace.updated_at.map(|value| value.to_rfc3339()),
    })
}

fn conversation_json(
    record: &CreateTaskSessionRecord,
    workspace: &WorkspaceRecord,
    agent_config: Value,
    metadata: Value,
) -> Value {
    json!({
        "id": record.conversation.id,
        "project_id": record.project_id,
        "user_id": record.actor_user_id,
        "tenant_id": record.tenant_id,
        "title": record.conversation.title,
        "status": "active",
        "message_count": 0,
        "created_at": record.created_at.to_rfc3339(),
        "updated_at": record.created_at.to_rfc3339(),
        "summary": Value::Null,
        "agent_config": agent_config,
        "metadata": metadata,
        "parent_conversation_id": Value::Null,
        "branch_point_message_id": Value::Null,
        "conversation_mode": "workspace",
        "current_mode": "plan",
        "workspace_id": workspace.id,
        "linked_workspace_task_id": Value::Null,
        "workspace_name": workspace.name,
        "participant_agents": [],
        "coordinator_agent_id": Value::Null,
        "focused_agent_id": Value::Null,
    })
}

fn initial_message_json(
    record: &CreateTaskSessionRecord,
    workspace: &WorkspaceRecord,
    metadata: Value,
) -> Value {
    json!({
        "id": record.initial_message_id,
        "workspace_id": workspace.id,
        "sender_id": record.actor_user_id,
        "sender_type": "human",
        "content": record.initial_message_content,
        "mentions": [],
        "parent_message_id": Value::Null,
        "metadata": metadata,
        "created_at": record.created_at.to_rfc3339(),
    })
}

fn outcome_from_receipt(
    snapshot: Value,
    receipt_workspace_id: &str,
    receipt_conversation_id: &str,
    receipt_initial_message_id: &str,
    tenant_id: &str,
    project_id: &str,
) -> TaskSessionResult<TaskSessionCreationOutcome> {
    let outcome = outcome_from_snapshot(snapshot, true)?;
    validate_receipt_snapshot(
        &outcome,
        receipt_workspace_id,
        receipt_conversation_id,
        receipt_initial_message_id,
        tenant_id,
        project_id,
    )?;
    Ok(outcome)
}

fn outcome_from_snapshot(
    snapshot: Value,
    replayed: bool,
) -> TaskSessionResult<TaskSessionCreationOutcome> {
    let object = snapshot.as_object().ok_or_else(corrupt_snapshot)?;
    Ok(TaskSessionCreationOutcome {
        replayed,
        workspace: object
            .get("workspace")
            .cloned()
            .ok_or_else(corrupt_snapshot)?,
        conversation: object
            .get("conversation")
            .cloned()
            .ok_or_else(corrupt_snapshot)?,
        initial_message: object
            .get("initial_message")
            .cloned()
            .ok_or_else(corrupt_snapshot)?,
    })
}

fn validate_receipt_snapshot(
    outcome: &TaskSessionCreationOutcome,
    receipt_workspace_id: &str,
    receipt_conversation_id: &str,
    receipt_initial_message_id: &str,
    tenant_id: &str,
    project_id: &str,
) -> TaskSessionResult<()> {
    let workspace_id = string_field(&outcome.workspace, "id")?;
    let conversation_id = string_field(&outcome.conversation, "id")?;
    let initial_message_id = string_field(&outcome.initial_message, "id")?;
    let selected_agent_id = outcome
        .conversation
        .get("agent_config")
        .and_then(|value| value.get("selected_agent_id"))
        .and_then(Value::as_str)
        .ok_or_else(corrupt_snapshot)?;
    let valid = string_field(&outcome.workspace, "tenant_id")? == tenant_id
        && string_field(&outcome.workspace, "project_id")? == project_id
        && string_field(&outcome.conversation, "tenant_id")? == tenant_id
        && string_field(&outcome.conversation, "project_id")? == project_id
        && string_field(&outcome.conversation, "workspace_id")? == workspace_id
        && string_field(&outcome.conversation, "conversation_mode")? == "workspace"
        && string_field(&outcome.conversation, "current_mode")? == "plan"
        && string_field(&outcome.initial_message, "workspace_id")? == workspace_id
        && string_field(&outcome.initial_message, "sender_type")? == "human"
        && selected_agent_id == "builtin:all-access"
        && receipt_workspace_id == workspace_id
        && receipt_conversation_id == conversation_id
        && receipt_initial_message_id == initial_message_id;
    if valid {
        Ok(())
    } else {
        Err(corrupt_snapshot())
    }
}

fn string_field<'a>(value: &'a Value, field: &str) -> TaskSessionResult<&'a str> {
    value
        .get(field)
        .and_then(Value::as_str)
        .ok_or_else(corrupt_snapshot)
}

fn corrupt_snapshot() -> TaskSessionRepositoryError {
    TaskSessionRepositoryError::Storage("task session receipt snapshot is inconsistent".to_string())
}

fn workspace_insert_error(error: sqlx::Error) -> TaskSessionRepositoryError {
    if error
        .as_database_error()
        .and_then(|database_error| database_error.constraint())
        == Some("uq_workspaces_project_name")
    {
        TaskSessionRepositoryError::WorkspaceNameConflict
    } else {
        storage(error)
    }
}

fn core_storage(error: impl std::fmt::Display) -> TaskSessionRepositoryError {
    TaskSessionRepositoryError::Storage(error.to_string())
}

fn storage(error: sqlx::Error) -> TaskSessionRepositoryError {
    TaskSessionRepositoryError::Storage(error.to_string())
}

#[cfg(test)]
mod tests;
