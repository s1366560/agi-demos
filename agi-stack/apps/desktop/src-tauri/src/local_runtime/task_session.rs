use std::sync::Arc;

use axum::{extract::Extension, extract::Path, extract::State, http::StatusCode, Json};
use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};
use uuid::Uuid;

use super::{
    active_workspace_scope_error,
    auth_context::AuthenticatedContext,
    composer_context::{validate_composer_context_items, ComposerContextItem},
    invalid_composer_context, local_store_error, now_iso,
    resource_registry::{WorkspaceAgentPolicyMutation, WORKSPACE_AGENT_POLICY_CAPABILITY_VERSION},
    session_store::{CreateTaskSessionInput, DesktopTaskSessionError, TaskSessionWorkspaceInput},
    tool_authority::canonical_json_digest,
    ConversationCapabilityMode, ConversationRunMode, LocalConversation, LocalRuntimeState,
};

const TASK_SESSION_IDEMPOTENCY_CONFLICT_CODE: &str = "TASK_SESSION_IDEMPOTENCY_CONFLICT";
const TASK_SESSION_IDEMPOTENCY_CONFLICT_DETAIL: &str =
    "Task session idempotency key is already bound to a different request";

#[derive(Clone, Copy, Debug, Default, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum WorkspaceUseCase {
    General,
    Programming,
    #[default]
    Conversation,
    Research,
    Operations,
}

#[derive(Clone, Copy, Debug, Default, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum WorkspaceCollaborationMode {
    SingleAgent,
    #[default]
    MultiAgentShared,
    MultiAgentIsolated,
    Autonomous,
}

pub(super) struct WorkspaceCreateAttributes {
    pub(super) name: String,
    pub(super) description: Option<String>,
    pub(super) metadata: Option<Map<String, Value>>,
    pub(super) use_case: WorkspaceUseCase,
    pub(super) collaboration_mode: WorkspaceCollaborationMode,
    pub(super) sandbox_code_root: Option<String>,
}

pub(super) fn workspace_value(
    id: String,
    tenant_id: &str,
    project_id: &str,
    attributes: WorkspaceCreateAttributes,
    now: &str,
) -> Value {
    let mut metadata = attributes.metadata.unwrap_or_default();
    metadata
        .entry("runtime".to_string())
        .or_insert_with(|| json!("local"));
    metadata.insert("use_case".to_string(), json!(attributes.use_case));
    metadata.insert(
        "collaboration_mode".to_string(),
        json!(attributes.collaboration_mode),
    );
    if let Some(sandbox_code_root) = attributes.sandbox_code_root.as_ref() {
        metadata.insert("sandbox_code_root".to_string(), json!(sandbox_code_root));
    } else {
        metadata.remove("sandbox_code_root");
    }
    json!({
        "id": id,
        "tenant_id": tenant_id,
        "project_id": project_id,
        "name": attributes.name,
        "description": attributes.description,
        "status": "open",
        "is_archived": false,
        "created_at": now,
        "updated_at": now,
        "metadata": metadata,
        "use_case": attributes.use_case,
        "collaboration_mode": attributes.collaboration_mode,
        "sandbox_code_root": attributes.sandbox_code_root,
    })
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct CreateTaskSessionBody {
    idempotency_key: String,
    workspace: TaskSessionWorkspaceBody,
    conversation: TaskSessionConversationBody,
    initial_message: TaskSessionInitialMessageBody,
    workspace_policy: Option<WorkspaceAgentPolicyMutation>,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum TaskSessionWorkspaceBody {
    Create {
        name: String,
        description: Option<String>,
        metadata: Option<Map<String, Value>>,
        use_case: WorkspaceUseCase,
        collaboration_mode: WorkspaceCollaborationMode,
        sandbox_code_root: Option<String>,
    },
    Existing {
        workspace_id: String,
    },
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct TaskSessionConversationBody {
    title: String,
    capability_mode: TaskSessionCapabilityMode,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum TaskSessionCapabilityMode {
    Work,
    Code,
}

impl From<TaskSessionCapabilityMode> for ConversationCapabilityMode {
    fn from(mode: TaskSessionCapabilityMode) -> Self {
        match mode {
            TaskSessionCapabilityMode::Work => Self::Work,
            TaskSessionCapabilityMode::Code => Self::Code,
        }
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct TaskSessionInitialMessageBody {
    content: String,
    #[serde(default)]
    context_items: Vec<ComposerContextItem>,
}

pub(super) async fn create_task_session(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path((tenant_id, project_id)): Path<(String, String)>,
    Json(body): Json<CreateTaskSessionBody>,
) -> Result<(StatusCode, Json<Value>), (StatusCode, Json<Value>)> {
    if tenant_id != authenticated.workspace.tenant_id
        || project_id != authenticated.workspace.project_id
    {
        return Err(active_workspace_scope_error());
    }
    let idempotency_key = required_text(body.idempotency_key.as_str(), "idempotency_key", 255)?;
    let title = required_text(body.conversation.title.as_str(), "conversation.title", 255)?;
    let initial_content = required_text(
        body.initial_message.content.as_str(),
        "initial_message.content",
        100_000,
    )?;
    validate_composer_context_items(&body.initial_message.context_items)
        .map_err(invalid_composer_context)?;
    let payload = json!({
        "tenant_id": tenant_id,
        "project_id": project_id,
        "body": body,
    });
    let payload_hash =
        canonical_json_digest(&payload).map_err(|error| local_store_error(error.to_string()))?;
    let now = now_iso();

    let (workspace_id, workspace) = match body.workspace {
        TaskSessionWorkspaceBody::Create {
            name,
            description,
            metadata,
            use_case,
            collaboration_mode,
            sandbox_code_root,
        } => {
            let name = required_text(name.as_str(), "workspace.name", 255)?;
            let id = format!("local-workspace-{}", Uuid::new_v4());
            let workspace = workspace_value(
                id.clone(),
                &tenant_id,
                &project_id,
                WorkspaceCreateAttributes {
                    name,
                    description,
                    metadata,
                    use_case,
                    collaboration_mode,
                    sandbox_code_root,
                },
                &now,
            );
            (id, TaskSessionWorkspaceInput::Create(workspace))
        }
        TaskSessionWorkspaceBody::Existing { workspace_id } => {
            let workspace_id = required_text(workspace_id.as_str(), "workspace.workspace_id", 255)?;
            (
                workspace_id.clone(),
                TaskSessionWorkspaceInput::Existing(workspace_id),
            )
        }
    };
    super::validate_composer_context_authority(
        &state,
        &authenticated,
        &workspace_id,
        &body.initial_message.context_items,
    )?;
    let conversation_id = format!("local-conversation-{}", Uuid::new_v4());
    let conversation = LocalConversation {
        id: conversation_id.clone(),
        project_id: project_id.clone(),
        tenant_id: tenant_id.clone(),
        title,
        workspace_id: Some(workspace_id.clone()),
        capability_mode: body.conversation.capability_mode.into(),
        current_mode: ConversationRunMode::Plan,
        created_at: now.clone(),
        updated_at: now.clone(),
    };
    let initial_message = json!({
        "id": format!("local-message-{}", Uuid::new_v4()),
        "workspace_id": workspace_id,
        "parent_message_id": Value::Null,
        "sender_type": "human",
        "sender_id": authenticated.user.user_id,
        "content": initial_content,
        "mentions": [],
        "created_at": now,
        "metadata": {
            "runtime": "local",
            "source": "task_session",
            "conversation_id": conversation_id,
            "context_items": body.initial_message.context_items,
        },
    });
    let outcome = state
        .session_store
        .create_task_session(CreateTaskSessionInput {
            user_id: authenticated.user.user_id,
            expected_context_revision: authenticated.workspace.revision,
            tenant_id,
            project_id,
            idempotency_key,
            payload_hash,
            workspace,
            conversation,
            initial_message,
            workspace_policy: body.workspace_policy,
            now,
        })
        .map_err(task_session_error)?;
    let status = if outcome.replayed {
        StatusCode::OK
    } else {
        StatusCode::CREATED
    };
    Ok((
        status,
        Json(json!({
            "replayed": outcome.replayed,
            "workspace": outcome.workspace,
            "conversation": outcome.conversation,
            "initial_message": outcome.initial_message,
            "policy": outcome.policy,
            "capability_version": WORKSPACE_AGENT_POLICY_CAPABILITY_VERSION,
        })),
    ))
}

fn required_text(
    value: &str,
    field: &str,
    max_length: usize,
) -> Result<String, (StatusCode, Json<Value>)> {
    let value = value.trim();
    if value.is_empty() || value.chars().count() > max_length {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({
                "detail": format!("{field} must be a non-empty string of at most {max_length} characters"),
            })),
        ));
    }
    Ok(value.to_string())
}

fn task_session_error(error: DesktopTaskSessionError) -> (StatusCode, Json<Value>) {
    match error {
        DesktopTaskSessionError::IdempotencyConflict => (
            StatusCode::CONFLICT,
            Json(json!({
                "code": TASK_SESSION_IDEMPOTENCY_CONFLICT_CODE,
                "detail": TASK_SESSION_IDEMPOTENCY_CONFLICT_DETAIL,
            })),
        ),
        DesktopTaskSessionError::WorkspaceNotFound => (
            StatusCode::NOT_FOUND,
            Json(json!({ "detail": error.to_string() })),
        ),
        DesktopTaskSessionError::ScopeMismatch => active_workspace_scope_error(),
        DesktopTaskSessionError::Policy(error) => super::resource_registry_error(error),
        DesktopTaskSessionError::Storage(error) => local_store_error(error),
    }
}
