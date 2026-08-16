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
    session_store::{DesktopTaskSessionError, ProjectTaskSessionInput, ReplayTaskSessionInput},
    tool_authority::canonical_json_digest,
    workspace_core_bridge::{self, WorkspaceCoreTaskSessionRequest},
    ConversationCapabilityMode, ConversationRunMode, LlmRouteTarget, LocalConversation,
    LocalRuntimeState,
};

const TASK_SESSION_ID_NAMESPACE: Uuid = Uuid::from_u128(0xf583_658d_976f_4589_a385_750a_3b0b_8e74);
const TASK_SESSION_IDEMPOTENCY_CONFLICT_CODE: &str = "TASK_SESSION_IDEMPOTENCY_CONFLICT";

#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum WorkspaceUseCase {
    General,
    Programming,
    Conversation,
    Research,
    Operations,
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum WorkspaceCollaborationMode {
    SingleAgent,
    MultiAgentShared,
    MultiAgentIsolated,
    Autonomous,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct CreateTaskSessionBody {
    idempotency_key: String,
    workspace: TaskSessionWorkspaceBody,
    conversation: TaskSessionConversationBody,
    initial_message: TaskSessionInitialMessageBody,
    workspace_policy: Option<Value>,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum TaskSessionWorkspaceBody {
    Create {
        name: String,
        description: Option<String>,
        #[serde(default)]
        metadata: Map<String, Value>,
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

#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum TaskSessionCapabilityMode {
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
    let idempotency_key = required_text(&body.idempotency_key, "idempotency_key", 255)?;
    let title = required_text(&body.conversation.title, "conversation.title", 255)?;
    let initial_content = required_text(
        &body.initial_message.content,
        "initial_message.content",
        100_000,
    )?;
    validate_composer_context_items(&body.initial_message.context_items)
        .map_err(invalid_composer_context)?;
    let payload_hash = canonical_json_digest(
        &serde_json::to_value(&body).map_err(|error| local_store_error(error.to_string()))?,
    )
    .map_err(|error| local_store_error(error.to_string()))?;
    let submitted_llm_route = body
        .workspace_policy
        .as_ref()
        .and_then(|policy| policy.get("route"))
        .map(|route| {
            serde_json::from_value::<LlmRouteTarget>(route.clone()).map_err(|_| {
                super::local_bad_request("workspace_policy.route is invalid".to_string())
            })
        })
        .transpose()?;
    if let Some(outcome) = state
        .session_store
        .replay_task_session(ReplayTaskSessionInput {
            user_id: authenticated.user.user_id.clone(),
            expected_context_revision: authenticated.workspace.revision,
            tenant_id: tenant_id.clone(),
            project_id: project_id.clone(),
            idempotency_key: idempotency_key.clone(),
            payload_hash: payload_hash.clone(),
        })
        .map_err(task_session_error)?
    {
        return task_session_response(outcome);
    }
    if let Some(route) = submitted_llm_route.as_ref() {
        state
            .validate_conversation_llm_route(&tenant_id, route)
            .map_err(super::local_bad_request)?;
    }
    let now = now_iso();
    let conversation_id = stable_task_session_id(
        "conversation",
        &tenant_id,
        &project_id,
        &authenticated.user.user_id,
        &idempotency_key,
    );
    let message_id = stable_task_session_id(
        "message",
        &tenant_id,
        &project_id,
        &authenticated.user.user_id,
        &idempotency_key,
    );
    let workspace = core_workspace_request(
        body.workspace,
        &tenant_id,
        &project_id,
        &authenticated.user.user_id,
        &idempotency_key,
    )?;
    let workspace_id = workspace
        .get("workspace_id")
        .and_then(Value::as_str)
        .ok_or_else(|| workspace_core_bridge::bad_request("Workspace is invalid"))?
        .to_string();
    super::validate_composer_context_authority(
        &state,
        &authenticated,
        &workspace_id,
        &body.initial_message.context_items,
    )?;
    let core_response = workspace_core_bridge::create_task_session(
        &state,
        &authenticated,
        &tenant_id,
        &project_id,
        &idempotency_key,
        WorkspaceCoreTaskSessionRequest {
            workspace,
            conversation_id: conversation_id.clone(),
            initial_message: json!({
                "message_id": message_id,
                "content": initial_content,
                "context_items": body.initial_message.context_items,
            }),
            workspace_policy: body.workspace_policy,
            capability_mode: body.conversation.capability_mode,
        },
    )
    .await?;
    validate_core_response(
        &core_response,
        CoreResponseExpectation {
            tenant_id: &tenant_id,
            project_id: &project_id,
            workspace_id: &workspace_id,
            conversation_id: &conversation_id,
            message_id: &message_id,
            actor_id: &authenticated.user.user_id,
            initial_content: &initial_content,
        },
    )?;
    let committed_llm_route = committed_task_session_route(
        core_response
            .get("policy")
            .ok_or_else(invalid_core_response)?,
        body.conversation.capability_mode,
        submitted_llm_route.as_ref(),
    )?;
    let conversation = LocalConversation {
        id: conversation_id,
        project_id: project_id.clone(),
        tenant_id: tenant_id.clone(),
        title,
        workspace_id: Some(workspace_id),
        capability_mode: body.conversation.capability_mode.into(),
        current_mode: ConversationRunMode::Plan,
        created_at: now.clone(),
        updated_at: now.clone(),
    };
    let mut outcome = state
        .session_store
        .project_task_session(ProjectTaskSessionInput {
            user_id: authenticated.user.user_id,
            expected_context_revision: authenticated.workspace.revision,
            tenant_id,
            project_id,
            idempotency_key,
            payload_hash,
            workspace: core_response["workspace"].clone(),
            conversation,
            initial_message: core_response["initial_message"].clone(),
            policy: core_response.get("policy").cloned().unwrap_or(Value::Null),
            llm_route: committed_llm_route,
            capability_version: core_response["capability_version"]
                .as_str()
                .ok_or_else(invalid_core_response)?
                .to_string(),
            now,
        })
        .map_err(task_session_error)?;
    outcome.replayed |= core_response
        .get("replayed")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    task_session_response(outcome)
}

fn committed_task_session_route(
    policy: &Value,
    capability_mode: TaskSessionCapabilityMode,
    submitted_route: Option<&LlmRouteTarget>,
) -> Result<Option<LlmRouteTarget>, (StatusCode, Json<Value>)> {
    let Some(submitted_route) = submitted_route else {
        return Ok(None);
    };
    if policy.is_null() {
        return Err(invalid_core_response());
    }
    let role = match capability_mode {
        TaskSessionCapabilityMode::Work => super::LlmWorkloadRole::Default,
        TaskSessionCapabilityMode::Code => super::LlmWorkloadRole::Coding,
    };
    let route = super::routing_targets_for_role(policy, role)
        .map_err(|_| invalid_core_response())?
        .into_iter()
        .next()
        .ok_or_else(invalid_core_response)?;
    if route != *submitted_route {
        return Err(invalid_core_response());
    }
    Ok(Some(route))
}

fn task_session_response(
    outcome: super::session_store::ProjectTaskSessionOutcome,
) -> Result<(StatusCode, Json<Value>), (StatusCode, Json<Value>)> {
    let replayed = outcome.replayed;
    let mut response = json!({
        "replayed": replayed,
        "workspace": outcome.workspace,
        "conversation": outcome.conversation,
        "initial_message": outcome.initial_message,
        "capability_version": outcome.capability_version,
    });
    if !outcome.policy.is_null() {
        response["policy"] = outcome.policy;
    }
    Ok((
        if replayed {
            StatusCode::OK
        } else {
            StatusCode::CREATED
        },
        Json(response),
    ))
}

fn core_workspace_request(
    workspace: TaskSessionWorkspaceBody,
    tenant_id: &str,
    project_id: &str,
    actor_id: &str,
    idempotency_key: &str,
) -> Result<Value, (StatusCode, Json<Value>)> {
    match workspace {
        TaskSessionWorkspaceBody::Create {
            name,
            description,
            mut metadata,
            use_case,
            collaboration_mode,
            sandbox_code_root,
        } => {
            let name = required_text(&name, "workspace.name", 255)?;
            metadata
                .entry("runtime".to_string())
                .or_insert_with(|| json!("local"));
            Ok(json!({
                "kind": "create",
                "workspace_id": stable_task_session_id(
                    "workspace",
                    tenant_id,
                    project_id,
                    actor_id,
                    idempotency_key,
                ),
                "name": name,
                "description": description,
                "metadata": metadata,
                "use_case": use_case,
                "collaboration_mode": collaboration_mode,
                "sandbox_code_root": sandbox_code_root,
            }))
        }
        TaskSessionWorkspaceBody::Existing { workspace_id } => Ok(json!({
            "kind": "existing",
            "workspace_id": required_text(&workspace_id, "workspace.workspace_id", 255)?,
        })),
    }
}

fn stable_task_session_id(
    kind: &str,
    tenant_id: &str,
    project_id: &str,
    actor_id: &str,
    idempotency_key: &str,
) -> String {
    let identity = [kind, tenant_id, project_id, actor_id, idempotency_key].join(":");
    Uuid::new_v5(&TASK_SESSION_ID_NAMESPACE, identity.as_bytes()).to_string()
}

struct CoreResponseExpectation<'a> {
    tenant_id: &'a str,
    project_id: &'a str,
    workspace_id: &'a str,
    conversation_id: &'a str,
    message_id: &'a str,
    actor_id: &'a str,
    initial_content: &'a str,
}

fn validate_core_response(
    response: &Value,
    expected: CoreResponseExpectation<'_>,
) -> Result<(), (StatusCode, Json<Value>)> {
    let workspace = response
        .get("workspace")
        .and_then(Value::as_object)
        .ok_or_else(invalid_core_response)?;
    if response.get("replayed").and_then(Value::as_bool).is_none()
        || !response
            .get("receipt_id")
            .and_then(Value::as_str)
            .is_some_and(|receipt_id| !receipt_id.is_empty())
        || !response
            .get("capability_version")
            .and_then(Value::as_str)
            .is_some_and(|capability_version| !capability_version.is_empty())
        || !response
            .get("policy")
            .is_some_and(|policy| policy.is_null() || policy.is_object())
    {
        return Err(invalid_core_response());
    }
    let message = response
        .get("initial_message")
        .and_then(Value::as_object)
        .ok_or_else(invalid_core_response)?;
    if workspace.get("id").and_then(Value::as_str) != Some(expected.workspace_id)
        || workspace.get("tenant_id").and_then(Value::as_str) != Some(expected.tenant_id)
        || workspace.get("project_id").and_then(Value::as_str) != Some(expected.project_id)
        || !workspace
            .get("name")
            .and_then(Value::as_str)
            .is_some_and(|name| !name.is_empty())
        || workspace.get("is_archived").and_then(Value::as_bool) != Some(false)
        || message.get("id").and_then(Value::as_str) != Some(expected.message_id)
        || message.get("workspace_id").and_then(Value::as_str) != Some(expected.workspace_id)
        || message.get("sender_id").and_then(Value::as_str) != Some(expected.actor_id)
        || message.get("sender_type").and_then(Value::as_str) != Some("human")
        || message.get("content").and_then(Value::as_str) != Some(expected.initial_content)
        || !message
            .get("mentions")
            .and_then(Value::as_array)
            .is_some_and(|mentions| mentions.iter().all(Value::is_string))
        || !message.get("parent_message_id").is_some_and(Value::is_null)
        || message
            .get("metadata")
            .and_then(Value::as_object)
            .and_then(|metadata| metadata.get("conversation_id"))
            .and_then(Value::as_str)
            != Some(expected.conversation_id)
        || message
            .get("metadata")
            .and_then(Value::as_object)
            .and_then(|metadata| metadata.get("source"))
            .and_then(Value::as_str)
            != Some("task_session")
        || !message
            .get("created_at")
            .and_then(Value::as_str)
            .is_some_and(|created_at| !created_at.is_empty())
    {
        return Err(invalid_core_response());
    }
    Ok(())
}

fn invalid_core_response() -> (StatusCode, Json<Value>) {
    workspace_core_bridge::unavailable("Workspace Core returned an invalid task session")
}

fn required_text(
    value: &str,
    field: &str,
    max_length: usize,
) -> Result<String, (StatusCode, Json<Value>)> {
    let value = value.trim();
    if value.is_empty() || value.chars().count() > max_length {
        return Err(workspace_core_bridge::bad_request(&format!(
            "{field} must be a non-empty string of at most {max_length} characters"
        )));
    }
    Ok(value.to_string())
}

fn task_session_error(error: DesktopTaskSessionError) -> (StatusCode, Json<Value>) {
    match error {
        DesktopTaskSessionError::IdempotencyConflict => (
            StatusCode::CONFLICT,
            Json(json!({
                "code": TASK_SESSION_IDEMPOTENCY_CONFLICT_CODE,
                "detail": error.to_string(),
            })),
        ),
        DesktopTaskSessionError::ScopeMismatch => active_workspace_scope_error(),
        DesktopTaskSessionError::Storage(error) => local_store_error(error),
    }
}
