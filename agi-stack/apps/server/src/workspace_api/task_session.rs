use sha2::{Digest, Sha256};

use super::*;

const TASK_SESSION_IDEMPOTENCY_CONFLICT_CODE: &str = "TASK_SESSION_IDEMPOTENCY_CONFLICT";
const TASK_SESSION_IDEMPOTENCY_CONFLICT_DETAIL: &str =
    "Task session idempotency key is already bound to a different request";

#[derive(Debug, Clone, Hash, PartialEq, Eq)]
pub(super) struct DevTaskSessionReceiptKey {
    actor_user_id: String,
    tenant_id: String,
    project_id: String,
    idempotency_key: String,
}

#[derive(Debug, Clone)]
pub(super) struct DevTaskSessionReceipt {
    pub(super) payload_hash: String,
    pub(super) workspace_id: String,
    pub(super) initial_message_id: String,
    pub(super) response: Option<CreateTaskSessionView>,
}

impl PgWorkspaceService {
    pub(super) async fn pg_create_task_session(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        body: CreateTaskSessionPayload,
    ) -> Result<CreateTaskSessionView, WorkspaceApiError> {
        let record = prepare_task_session_record(user_id, tenant_id, project_id, body)?;
        self.repo
            .create_task_session(record)
            .await
            .map(task_session_view)
            .map_err(task_session_repository_error)
    }
}

impl DevWorkspaceService {
    pub(super) async fn dev_create_task_session(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        body: CreateTaskSessionPayload,
    ) -> Result<CreateTaskSessionView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let record = prepare_task_session_record(user_id, tenant_id, project_id, body)?;
        let receipt_key = DevTaskSessionReceiptKey {
            actor_user_id: record.actor_user_id.clone(),
            tenant_id: record.tenant_id.clone(),
            project_id: record.project_id.clone(),
            idempotency_key: record.idempotency_key.clone(),
        };
        let mut state = self.lock_state()?;
        if let Some(receipt) = state.task_session_receipts.get(&receipt_key).cloned() {
            if receipt.payload_hash != record.payload_hash {
                return Err(task_session_idempotency_conflict());
            }
            if let Some(workspace) = state.workspaces.get(&receipt.workspace_id).cloned() {
                if workspace.tenant_id != record.tenant_id
                    || workspace.project_id != record.project_id
                    || workspace.is_archived
                {
                    return Err(task_session_idempotency_conflict());
                }
                if !state.messages.contains_key(&receipt.initial_message_id) {
                    if let Some(stored_receipt) = state.task_session_receipts.get_mut(&receipt_key)
                    {
                        stored_receipt.response = None;
                    }
                    return Err(task_session_idempotency_conflict());
                }
                let writable = state.workspace_members.iter().any(|member| {
                    member.workspace_id == receipt.workspace_id
                        && member.user_id == record.actor_user_id
                        && matches!(member.role.as_str(), "owner" | "admin" | "editor")
                });
                if !writable {
                    return Err(WorkspaceApiError::forbidden());
                }
                let Some(mut response) = receipt.response else {
                    return Err(task_session_idempotency_conflict());
                };
                response.replayed = true;
                return Ok(response);
            }
            // A deleted root invalidates the complete aggregate. All other partial states retain
            // the receipt as an at-most-once tombstone and fail closed above.
            state.task_session_receipts.remove(&receipt_key);
        }

        let (workspace, owner) = match record.workspace {
            TaskSessionWorkspaceRecord::Create {
                workspace,
                owner_member_id,
            } => {
                let workspace = *workspace;
                if state.workspaces.values().any(|candidate| {
                    candidate.tenant_id == record.tenant_id
                        && candidate.project_id == record.project_id
                        && !candidate.is_archived
                        && candidate.name == workspace.name
                }) {
                    return Err(WorkspaceApiError::conflict("Workspace already exists"));
                }
                let owner = WorkspaceMemberRecord {
                    id: owner_member_id,
                    workspace_id: workspace.id.clone(),
                    user_id: record.actor_user_id.clone(),
                    user_email: None,
                    role: "owner".to_string(),
                    invited_by: Some(record.actor_user_id.clone()),
                    created_at: record.created_at,
                    updated_at: None,
                };
                (workspace, Some(owner))
            }
            TaskSessionWorkspaceRecord::Existing { workspace_id } => {
                let workspace = state
                    .workspaces
                    .get(&workspace_id)
                    .filter(|workspace| {
                        workspace.tenant_id == record.tenant_id
                            && workspace.project_id == record.project_id
                            && !workspace.is_archived
                    })
                    .cloned()
                    .ok_or_else(WorkspaceApiError::workspace_not_found)?;
                let writable = state.workspace_members.iter().any(|member| {
                    member.workspace_id == workspace_id
                        && member.user_id == record.actor_user_id
                        && matches!(member.role.as_str(), "owner" | "admin" | "editor")
                });
                if !writable {
                    return Err(WorkspaceApiError::forbidden());
                }
                (workspace, None)
            }
        };
        let workspace_id = workspace.id.clone();
        let capability_mode = repository_capability_mode(record.conversation.capability_mode);
        let message = WorkspaceMessageRecord {
            id: record.initial_message_id,
            workspace_id: workspace_id.clone(),
            sender_id: record.actor_user_id.clone(),
            sender_type: "human".to_string(),
            content: record.initial_message_content,
            mentions_json: Vec::new(),
            parent_message_id: None,
            metadata_json: json!({
                "runtime": "in_memory_dev",
                "source": "task_session",
                "conversation_id": record.conversation.id,
                "sender_name": record.actor_user_id,
            }),
            created_at: record.created_at,
        };
        let message_view = MessageView::from(message.clone());
        let conversation = json!({
            "id": record.conversation.id,
            "project_id": record.project_id,
            "tenant_id": record.tenant_id,
            "user_id": record.actor_user_id,
            "title": record.conversation.title,
            "status": "active",
            "message_count": 0,
            "created_at": iso(record.created_at),
            "updated_at": Value::Null,
            "summary": Value::Null,
            "agent_config": {
                "selected_agent_id": "builtin:all-access",
                "capability_mode": capability_mode,
            },
            "metadata": {
                "runtime": "in_memory_dev",
                "source": "task_session",
            },
            "conversation_mode": "workspace",
            "current_mode": "plan",
            "workspace_id": workspace_id.clone(),
            "linked_workspace_task_id": Value::Null,
            "workspace_name": workspace.name,
            "participant_agents": [],
            "coordinator_agent_id": Value::Null,
            "focused_agent_id": Value::Null,
        });
        let workspace_value = serde_json::to_value(WorkspaceView::from(workspace.clone()))
            .map_err(WorkspaceApiError::internal)?;
        let message_value =
            serde_json::to_value(&message_view).map_err(WorkspaceApiError::internal)?;
        let initial_message_id = message.id.clone();
        let response = CreateTaskSessionView {
            replayed: false,
            workspace: workspace_value,
            conversation,
            initial_message: message_value,
        };
        let outbox = BlackboardOutboxRecord {
            id: record.blackboard_outbox_id,
            workspace_id: workspace.id.clone(),
            tenant_id: workspace.tenant_id.clone(),
            project_id: workspace.project_id.clone(),
            event_type: "workspace_message_created".to_string(),
            payload_json: json!({ "message": &message_view }),
            metadata_json: json!({
                "tenant_id": workspace.tenant_id,
                "project_id": workspace.project_id,
                "surface_owner": "workspace-chat",
                "surface_boundary": "hosted",
                "authority_class": "non-authoritative",
                "signal_role": "sensing-capable",
                "source": "task_session",
            }),
            correlation_id: Some(record.conversation.id),
        };

        if let Some(owner) = owner {
            state.workspace_members.push(owner);
            state.workspaces.insert(workspace.id.clone(), workspace);
        }
        state.messages.insert(message.id.clone(), message);
        state.outbox.push(outbox);
        state.task_session_receipts.insert(
            receipt_key,
            DevTaskSessionReceipt {
                payload_hash: record.payload_hash,
                workspace_id,
                initial_message_id,
                response: Some(response.clone()),
            },
        );
        Ok(response)
    }
}

fn prepare_task_session_record(
    user_id: &str,
    tenant_id: &str,
    project_id: &str,
    body: CreateTaskSessionPayload,
) -> Result<CreateTaskSessionRecord, WorkspaceApiError> {
    let payload_hash = task_session_payload_hash(tenant_id, project_id, &body)?;
    let idempotency_key = required_text(&body.idempotency_key, "idempotency_key", 255)?;
    let title = required_text(&body.conversation.title, "conversation.title", 255)?;
    let initial_message_content = required_text(
        &body.initial_message.content,
        "initial_message.content",
        100_000,
    )?;
    let capability_mode = match body.conversation.capability_mode {
        TaskSessionCapabilityMode::Work => RepoTaskSessionCapabilityMode::Work,
        TaskSessionCapabilityMode::Code => RepoTaskSessionCapabilityMode::Code,
    };
    let now = Utc::now();
    let workspace = match body.workspace {
        TaskSessionWorkspacePayload::Create {
            name,
            description,
            metadata,
            use_case,
            collaboration_mode,
            sandbox_code_root,
        } => {
            let name = required_text(&name, "workspace.name", 255)?;
            let metadata = compose_workspace_metadata(WorkspaceCreatePayload {
                name: name.clone(),
                description: description.clone(),
                metadata: Value::Object(metadata.unwrap_or_default()),
                use_case: Some(use_case.as_str().to_string()),
                collaboration_mode: Some(collaboration_mode.as_str().to_string()),
                autonomy_profile: None,
                sandbox_code_root,
            });
            TaskSessionWorkspaceRecord::Create {
                workspace: Box::new(WorkspaceRecord {
                    id: new_id(),
                    tenant_id: tenant_id.to_string(),
                    project_id: project_id.to_string(),
                    name,
                    description,
                    created_by: user_id.to_string(),
                    is_archived: false,
                    metadata_json: metadata,
                    office_status: "inactive".to_string(),
                    hex_layout_config_json: json!({}),
                    default_blocking_categories_json: Vec::new(),
                    created_at: now,
                    updated_at: None,
                }),
                owner_member_id: new_id(),
            }
        }
        TaskSessionWorkspacePayload::Existing { workspace_id } => {
            TaskSessionWorkspaceRecord::Existing {
                workspace_id: required_text(&workspace_id, "workspace.workspace_id", 255)?,
            }
        }
    };
    Ok(CreateTaskSessionRecord {
        receipt_id: new_id(),
        actor_user_id: user_id.to_string(),
        tenant_id: tenant_id.to_string(),
        project_id: project_id.to_string(),
        idempotency_key,
        payload_hash,
        workspace,
        conversation: TaskSessionConversationRecord {
            id: new_id(),
            title,
            capability_mode,
        },
        initial_message_id: new_id(),
        initial_message_content,
        blackboard_outbox_id: new_id(),
        created_at: now,
    })
}

fn task_session_payload_hash(
    tenant_id: &str,
    project_id: &str,
    body: &CreateTaskSessionPayload,
) -> Result<String, WorkspaceApiError> {
    let payload = json!({
        "tenant_id": tenant_id,
        "project_id": project_id,
        "body": body,
    });
    let canonical = canonical_json(payload);
    let encoded = serde_json::to_vec(&canonical).map_err(WorkspaceApiError::internal)?;
    Ok(format!("{:x}", Sha256::digest(encoded)))
}

fn canonical_json(value: Value) -> Value {
    match value {
        Value::Array(items) => Value::Array(items.into_iter().map(canonical_json).collect()),
        Value::Object(map) => {
            let mut entries: Vec<_> = map.into_iter().collect();
            entries.sort_by(|left, right| left.0.cmp(&right.0));
            Value::Object(
                entries
                    .into_iter()
                    .map(|(key, value)| (key, canonical_json(value)))
                    .collect(),
            )
        }
        scalar => scalar,
    }
}

fn required_text(value: &str, field: &str, max_length: usize) -> Result<String, WorkspaceApiError> {
    let value = value.trim();
    if value.is_empty() || value.chars().count() > max_length {
        return Err(WorkspaceApiError::bad_request(format!(
            "{field} must be a non-empty string of at most {max_length} characters"
        )));
    }
    Ok(value.to_string())
}

fn repository_capability_mode(mode: RepoTaskSessionCapabilityMode) -> &'static str {
    match mode {
        RepoTaskSessionCapabilityMode::Work => "work",
        RepoTaskSessionCapabilityMode::Code => "code",
    }
}

fn task_session_view(outcome: TaskSessionCreationOutcome) -> CreateTaskSessionView {
    CreateTaskSessionView {
        replayed: outcome.replayed,
        workspace: outcome.workspace,
        conversation: outcome.conversation,
        initial_message: outcome.initial_message,
    }
}

fn task_session_repository_error(error: TaskSessionRepositoryError) -> WorkspaceApiError {
    match error {
        TaskSessionRepositoryError::InvalidInput => {
            WorkspaceApiError::bad_request("Task session input is invalid")
        }
        TaskSessionRepositoryError::ProjectAccessDenied
        | TaskSessionRepositoryError::WorkspaceAccessDenied => WorkspaceApiError::forbidden(),
        TaskSessionRepositoryError::WorkspaceNotFound => WorkspaceApiError::workspace_not_found(),
        TaskSessionRepositoryError::WorkspaceNameConflict => {
            WorkspaceApiError::conflict("Workspace already exists")
        }
        TaskSessionRepositoryError::IdempotencyConflict => task_session_idempotency_conflict(),
        TaskSessionRepositoryError::Storage(_) => {
            WorkspaceApiError::internal("Task session storage failed")
        }
    }
}

fn task_session_idempotency_conflict() -> WorkspaceApiError {
    WorkspaceApiError::coded_conflict(
        TASK_SESSION_IDEMPOTENCY_CONFLICT_CODE,
        TASK_SESSION_IDEMPOTENCY_CONFLICT_DETAIL,
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn storage_errors_do_not_expose_database_details() {
        let error = task_session_repository_error(TaskSessionRepositoryError::Storage(
            "duplicate key violates uq_private_schema".to_string(),
        ));

        assert_eq!(error.status, StatusCode::INTERNAL_SERVER_ERROR);
        assert_eq!(error.detail, "Task session storage failed");
    }

    #[tokio::test]
    async fn idempotency_conflicts_use_the_exact_cross_runtime_contract() {
        let response =
            axum::response::IntoResponse::into_response(task_session_idempotency_conflict());
        assert_eq!(response.status(), StatusCode::CONFLICT);
        let body = axum::body::to_bytes(response.into_body(), usize::MAX)
            .await
            .expect("conflict response body");
        let body: Value = serde_json::from_slice(&body).expect("conflict response json");
        assert_eq!(
            body,
            json!({
                "code": "TASK_SESSION_IDEMPOTENCY_CONFLICT",
                "detail": "Task session idempotency key is already bound to a different request",
            })
        );
    }

    #[tokio::test]
    async fn uncoded_workspace_errors_keep_the_existing_json_contract() {
        let response = axum::response::IntoResponse::into_response(WorkspaceApiError::conflict(
            "Workspace already exists",
        ));
        assert_eq!(response.status(), StatusCode::CONFLICT);
        let body = axum::body::to_bytes(response.into_body(), usize::MAX)
            .await
            .expect("uncoded response body");
        let body: Value = serde_json::from_slice(&body).expect("uncoded response json");
        assert_eq!(body, json!({ "detail": "Workspace already exists" }));
    }
}
