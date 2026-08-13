//! Authenticated internal HTTP adapter for atomic task-session creation.

use std::sync::Arc;

use axum::extract::Path;
use axum::http::{HeaderMap, StatusCode};
use axum::{Extension, Json};
use memstack_workspace_service::{
    CreateTaskSessionError, CreateTaskSessionErrorKind, CreateTaskSessionInput,
    CreateTaskSessionService, TaskSessionContext, TaskSessionMessageInput, TaskSessionPolicyInput,
    TaskSessionWorkspaceInput,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;

use super::public_api::caller_from_headers;
use super::{ApiError, WorkspaceCoreState, required_header};

const IDEMPOTENCY_HEADER: &str = "x-idempotency-key";
const USER_EMAIL_HEADER: &str = "x-memstack-user-email";

#[derive(Debug, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum WorkspaceRequest {
    Create {
        workspace_id: String,
        name: String,
        description: Option<String>,
        #[serde(default = "empty_object")]
        metadata: Value,
        use_case: String,
        collaboration_mode: String,
        sandbox_code_root: Option<String>,
    },
    Existing {
        workspace_id: String,
    },
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct InitialMessageRequest {
    message_id: String,
    content: String,
    #[serde(default)]
    context_items: Vec<Value>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct PolicyRouteRequest {
    provider_id: String,
    model_id: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct PolicyRequest {
    expected_revision: u64,
    route: PolicyRouteRequest,
    reasoning_effort: String,
    permission_mode: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct CreateTaskSessionRequest {
    workspace: WorkspaceRequest,
    conversation_id: String,
    initial_message: InitialMessageRequest,
    workspace_policy: Option<PolicyRequest>,
    capability_mode: String,
}

#[derive(Debug, Serialize)]
pub(super) struct CreateTaskSessionResponse {
    receipt_id: String,
    replayed: bool,
    workspace: Value,
    initial_message: Value,
    policy: Option<Value>,
    capability_version: String,
}

pub(super) async fn create_task_session(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id)): Path<(String, String)>,
    headers: HeaderMap,
    Json(request): Json<CreateTaskSessionRequest>,
) -> Result<(StatusCode, Json<CreateTaskSessionResponse>), ApiError> {
    let caller = caller_from_headers(&headers)?;
    let actor_email = required_header(&headers, USER_EMAIL_HEADER)?;
    let idempotency_key = required_header(&headers, IDEMPOTENCY_HEADER)?;
    let workspace = workspace_input(request.workspace);
    let input = CreateTaskSessionInput {
        context: TaskSessionContext {
            tenant_id,
            project_id,
            actor_id: caller.user_id,
            actor_email,
            actor_is_superuser: caller.is_superuser,
            idempotency_key,
            conversation_id: request.conversation_id,
        },
        workspace,
        initial_message: TaskSessionMessageInput {
            message_id: request.initial_message.message_id,
            content: request.initial_message.content,
            context_items: Value::Array(request.initial_message.context_items),
        },
        policy: request
            .workspace_policy
            .map(|policy| TaskSessionPolicyInput {
                expected_revision: policy.expected_revision,
                provider_id: policy.route.provider_id,
                model_id: policy.route.model_id,
                reasoning_effort: policy.reasoning_effort,
                permission_mode: policy.permission_mode,
            }),
        capability_mode: request.capability_mode,
    };
    let outcome = CreateTaskSessionService::new(
        state.db.as_ref(),
        state.sql_flavor,
        state.provider_registry.as_ref(),
    )
    .create(&input)
    .await
    .map_err(map_service_error)?;
    let response = CreateTaskSessionResponse {
        receipt_id: outcome.receipt_id,
        replayed: outcome.replayed,
        workspace: outcome.response["workspace"].clone(),
        initial_message: outcome.response["initial_message"].clone(),
        policy: outcome.response["policy"]
            .as_object()
            .map(|_| outcome.response["policy"].clone()),
        capability_version: outcome.response["capability_version"]
            .as_str()
            .unwrap_or("avernet-task-session-v1")
            .to_string(),
    };
    Ok((
        if outcome.replayed {
            StatusCode::OK
        } else {
            StatusCode::CREATED
        },
        Json(response),
    ))
}

fn workspace_input(request: WorkspaceRequest) -> TaskSessionWorkspaceInput {
    match request {
        WorkspaceRequest::Create {
            workspace_id,
            name,
            description,
            mut metadata,
            use_case,
            collaboration_mode,
            sandbox_code_root,
        } => {
            if let Some(fields) = metadata.as_object_mut() {
                fields.insert("use_case".to_string(), Value::String(use_case));
                fields.insert(
                    "collaboration_mode".to_string(),
                    Value::String(collaboration_mode),
                );
                if let Some(code_root) = sandbox_code_root {
                    fields.insert("sandbox_code_root".to_string(), Value::String(code_root));
                }
            }
            TaskSessionWorkspaceInput::Create {
                workspace_id,
                name,
                description,
                metadata,
            }
        }
        WorkspaceRequest::Existing { workspace_id } => {
            TaskSessionWorkspaceInput::Existing { workspace_id }
        }
    }
}

fn map_service_error(error: CreateTaskSessionError) -> ApiError {
    match error.kind() {
        CreateTaskSessionErrorKind::Validation => ApiError::InvalidRequest(error.to_string()),
        CreateTaskSessionErrorKind::NotFound => ApiError::NotFound,
        CreateTaskSessionErrorKind::Forbidden => ApiError::Forbidden("Workspace access required"),
        CreateTaskSessionErrorKind::Conflict => ApiError::Conflict(error.to_string()),
        CreateTaskSessionErrorKind::IdempotencyConflict => {
            ApiError::IdempotencyConflict("TASK_SESSION_IDEMPOTENCY_CONFLICT")
        }
        CreateTaskSessionErrorKind::Unavailable => ApiError::InvalidDatabase(error.to_string()),
    }
}

fn empty_object() -> Value {
    Value::Object(Default::default())
}
