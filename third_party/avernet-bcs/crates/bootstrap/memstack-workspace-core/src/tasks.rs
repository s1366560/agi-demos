//! Legacy-path Workspace Task handlers over the Avernet-backed authority.

use std::sync::Arc;

use axum::extract::rejection::JsonRejection;
use axum::extract::{Path, Query};
use axum::http::{HeaderMap, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Extension, Json, Router};
use memstack_workspace_service::{
    PublicCreateWorkspaceTaskInput, PublicUpdateWorkspaceTaskFields, PublicWorkspaceTask,
    PublicWorkspaceTaskContext, PublicWorkspaceTaskError, PublicWorkspaceTaskErrorKind,
    PublicWorkspaceTaskRecoveryInput, PublicWorkspaceTaskRecoveryOutcome,
    PublicWorkspaceTaskService,
};
use serde::Deserialize;
use serde_json::{Map, Value, json};

use super::creation::{body_validation_error, map_public_json_rejection, optional_header};
use super::public_api::caller_from_headers;
use super::workspace_scope::{WorkspaceScopeError, resolve_workspace_scope};
use super::{ApiError, WorkspaceCoreState};

const IDEMPOTENCY_HEADER: &str = "idempotency-key";
const IF_MATCH_HEADER: &str = "if-match";
const MAX_TITLE_CHARS: usize = 255;
const MAX_REASON_CHARS: usize = 500;
const TASK_STATUSES: &[&str] = &[
    "todo",
    "in_progress",
    "blocked",
    "done",
    "dispatched",
    "executing",
    "reported",
    "adjudicating",
];
const TASK_PRIORITIES: &[&str] = &["", "P1", "P2", "P3", "P4"];
const PREFERRED_LANGUAGES: &[&str] = &["en-US", "zh-CN"];
const RECOVERY_ACTIONS: &[&str] = &[
    "retry_launch",
    "new_attempt",
    "reassign",
    "mark_human_blocked",
    "terminate_stale_conversation",
];

#[derive(Debug, Deserialize)]
pub(super) struct TaskListQuery {
    status: Option<String>,
    limit: Option<String>,
    offset: Option<String>,
}

pub(super) fn router() -> Router {
    Router::new()
        .route(
            "/api/v1/workspaces/{workspace_id}/tasks",
            get(list_workspace_tasks).post(create_workspace_task),
        )
        .route(
            "/api/v1/workspaces/{workspace_id}/tasks/{task_id}",
            get(get_workspace_task)
                .patch(update_workspace_task)
                .delete(delete_workspace_task),
        )
        .route(
            "/api/v1/workspaces/{workspace_id}/tasks/{task_id}/assign-agent",
            post(assign_workspace_task),
        )
        .route(
            "/api/v1/workspaces/{workspace_id}/tasks/{task_id}/unassign-agent",
            post(unassign_workspace_task),
        )
        .route(
            "/api/v1/workspaces/{workspace_id}/tasks/{task_id}/claim",
            post(claim_workspace_task),
        )
        .route(
            "/api/v1/workspaces/{workspace_id}/tasks/{task_id}/start",
            post(start_workspace_task),
        )
        .route(
            "/api/v1/workspaces/{workspace_id}/tasks/{task_id}/block",
            post(block_workspace_task),
        )
        .route(
            "/api/v1/workspaces/{workspace_id}/tasks/{task_id}/complete",
            post(complete_workspace_task),
        )
        .route(
            "/api/v1/workspaces/{workspace_id}/tasks/{task_id}/experience",
            get(get_workspace_task_experience),
        )
        .route(
            "/api/v1/workspaces/{workspace_id}/tasks/{task_id}/execution-session",
            get(get_workspace_task_execution_session),
        )
        .route(
            "/api/v1/workspaces/{workspace_id}/tasks/{task_id}/recovery-actions",
            post(apply_workspace_task_recovery_action),
        )
}

async fn create_workspace_task(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path(workspace_id): Path<String>,
    headers: HeaderMap,
    request: Result<Json<Value>, JsonRejection>,
) -> TaskResult<(StatusCode, Json<PublicWorkspaceTask>)> {
    let Json(request) = request.map_err(map_public_json_rejection)?;
    let context = task_context(&state, workspace_id, &headers).await?;
    let input = parse_create_request(context, &request)?;
    let outcome = task_service(&state)
        .create(&input)
        .await
        .map_err(map_task_error)?;
    Ok((StatusCode::CREATED, Json(outcome.task)))
}

async fn list_workspace_tasks(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path(workspace_id): Path<String>,
    Query(query): Query<TaskListQuery>,
    headers: HeaderMap,
) -> TaskResult<Json<Vec<PublicWorkspaceTask>>> {
    let context = task_context(&state, workspace_id, &headers).await?;
    let status = query_status(query.status.as_deref())?;
    let limit = query_integer("limit", query.limit.as_deref(), 100, 1, 500)?;
    let offset = query_integer("offset", query.offset.as_deref(), 0, 0, i64::MAX)?;
    let tasks = task_service(&state)
        .list(&context, status.as_deref(), limit, offset)
        .await
        .map_err(map_task_error)?;
    Ok(Json(tasks))
}

async fn get_workspace_task(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((workspace_id, task_id)): Path<(String, String)>,
    headers: HeaderMap,
) -> TaskResult<Json<PublicWorkspaceTask>> {
    let context = task_context(&state, workspace_id, &headers).await?;
    let task = task_service(&state)
        .get(&context, task_id.as_str())
        .await
        .map_err(map_task_error)?;
    Ok(Json(task))
}

async fn update_workspace_task(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((workspace_id, task_id)): Path<(String, String)>,
    headers: HeaderMap,
    request: Result<Json<Value>, JsonRejection>,
) -> TaskResult<Json<PublicWorkspaceTask>> {
    let Json(request) = request.map_err(map_public_json_rejection)?;
    let context = task_context(&state, workspace_id, &headers).await?;
    let fields = parse_update_request(&request)?;
    let outcome = task_service(&state)
        .update(&context, task_id.as_str(), &fields)
        .await
        .map_err(map_task_error)?;
    Ok(Json(outcome.task))
}

async fn delete_workspace_task(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((workspace_id, task_id)): Path<(String, String)>,
    headers: HeaderMap,
) -> TaskResult<StatusCode> {
    let context = task_context(&state, workspace_id, &headers).await?;
    let _outcome = task_service(&state)
        .delete(&context, task_id.as_str())
        .await
        .map_err(map_task_error)?;
    Ok(StatusCode::NO_CONTENT)
}

async fn assign_workspace_task(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((workspace_id, task_id)): Path<(String, String)>,
    headers: HeaderMap,
    request: Result<Json<Value>, JsonRejection>,
) -> TaskResult<Json<PublicWorkspaceTask>> {
    let Json(request) = request.map_err(map_public_json_rejection)?;
    let context = task_context(&state, workspace_id, &headers).await?;
    let (workspace_agent_id, preferred_language) = parse_assign_request(&request)?;
    let outcome = task_service(&state)
        .assign_agent(
            &context,
            task_id.as_str(),
            workspace_agent_id.as_str(),
            preferred_language.as_deref(),
        )
        .await
        .map_err(map_task_error)?;
    Ok(Json(outcome.task))
}

async fn unassign_workspace_task(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((workspace_id, task_id)): Path<(String, String)>,
    headers: HeaderMap,
) -> TaskResult<Json<PublicWorkspaceTask>> {
    let context = task_context(&state, workspace_id, &headers).await?;
    let outcome = task_service(&state)
        .unassign_agent(&context, task_id.as_str())
        .await
        .map_err(map_task_error)?;
    Ok(Json(outcome.task))
}

async fn claim_workspace_task(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((workspace_id, task_id)): Path<(String, String)>,
    headers: HeaderMap,
) -> TaskResult<Json<PublicWorkspaceTask>> {
    let context = task_context(&state, workspace_id, &headers).await?;
    let outcome = task_service(&state)
        .claim(&context, task_id.as_str())
        .await
        .map_err(map_task_error)?;
    Ok(Json(outcome.task))
}

async fn start_workspace_task(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((workspace_id, task_id)): Path<(String, String)>,
    headers: HeaderMap,
) -> TaskResult<Json<PublicWorkspaceTask>> {
    transition_workspace_task(&state, workspace_id, task_id, &headers, "in_progress").await
}

async fn block_workspace_task(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((workspace_id, task_id)): Path<(String, String)>,
    headers: HeaderMap,
) -> TaskResult<Json<PublicWorkspaceTask>> {
    transition_workspace_task(&state, workspace_id, task_id, &headers, "blocked").await
}

async fn complete_workspace_task(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((workspace_id, task_id)): Path<(String, String)>,
    headers: HeaderMap,
) -> TaskResult<Json<PublicWorkspaceTask>> {
    transition_workspace_task(&state, workspace_id, task_id, &headers, "done").await
}

async fn transition_workspace_task(
    state: &WorkspaceCoreState,
    workspace_id: String,
    task_id: String,
    headers: &HeaderMap,
    target: &str,
) -> TaskResult<Json<PublicWorkspaceTask>> {
    let context = task_context(state, workspace_id, headers).await?;
    let outcome = task_service(state)
        .transition(&context, task_id.as_str(), target)
        .await
        .map_err(map_task_error)?;
    Ok(Json(outcome.task))
}

async fn get_workspace_task_experience(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((workspace_id, task_id)): Path<(String, String)>,
    headers: HeaderMap,
) -> TaskResult<Json<Value>> {
    let context = task_context(&state, workspace_id, &headers).await?;
    let response = task_service(&state)
        .experience(&context, task_id.as_str())
        .await
        .map_err(map_task_error)?;
    Ok(Json(response))
}

async fn get_workspace_task_execution_session(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((workspace_id, task_id)): Path<(String, String)>,
    headers: HeaderMap,
) -> TaskResult<Json<Value>> {
    let context = task_context(&state, workspace_id, &headers).await?;
    let response = task_service(&state)
        .execution_session(&context, task_id.as_str())
        .await
        .map_err(map_task_error)?;
    Ok(Json(response))
}

async fn apply_workspace_task_recovery_action(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((workspace_id, task_id)): Path<(String, String)>,
    headers: HeaderMap,
    request: Result<Json<Value>, JsonRejection>,
) -> TaskResult<Json<PublicWorkspaceTaskRecoveryOutcome>> {
    let Json(request) = request.map_err(map_public_json_rejection)?;
    let context = task_context(&state, workspace_id, &headers).await?;
    let input = parse_recovery_request(&request)?;
    let response = task_service(&state)
        .recovery_action(&context, task_id.as_str(), &input)
        .await
        .map_err(map_task_error)?;
    Ok(Json(response))
}

fn task_service(state: &WorkspaceCoreState) -> PublicWorkspaceTaskService<'_> {
    PublicWorkspaceTaskService::new(state.db.as_ref(), state.sql_flavor)
}

async fn task_context(
    state: &WorkspaceCoreState,
    workspace_id: String,
    headers: &HeaderMap,
) -> TaskResult<PublicWorkspaceTaskContext> {
    let caller = caller_from_headers(headers)?;
    let scope = resolve_workspace_scope(state, workspace_id.as_str(), caller.user_id.as_str())
        .await
        .map_err(map_scope_error)?;
    Ok(PublicWorkspaceTaskContext {
        tenant_id: scope.tenant_id,
        project_id: scope.project_id,
        workspace_id: scope.workspace_id,
        user_id: caller.user_id,
        expected_revision: optional_header(headers, IF_MATCH_HEADER)?
            .map(|value| parse_if_match(value.as_str()))
            .transpose()?,
        idempotency_key: optional_header(headers, IDEMPOTENCY_HEADER)?,
    })
}

fn map_scope_error(error: WorkspaceScopeError) -> TaskHttpError {
    match error {
        WorkspaceScopeError::NotFound => {
            TaskHttpError::response(StatusCode::NOT_FOUND, "Workspace task not found")
        }
        WorkspaceScopeError::AccessRequired => {
            TaskHttpError::response(StatusCode::FORBIDDEN, "Access denied")
        }
        WorkspaceScopeError::InvalidRecord(_) | WorkspaceScopeError::Database(_) => {
            ApiError::InvalidDatabase(error.to_string()).into()
        }
    }
}

fn parse_if_match(value: &str) -> TaskResult<u64> {
    let value = value.trim();
    let value = value.strip_prefix("W/").unwrap_or(value);
    let value = value
        .strip_prefix('"')
        .and_then(|value| value.strip_suffix('"'))
        .unwrap_or(value);
    value.parse::<u64>().map_err(|_| {
        TaskHttpError::response(
            StatusCode::BAD_REQUEST,
            "If-Match must contain a non-negative Workspace revision",
        )
    })
}

fn parse_create_request(
    context: PublicWorkspaceTaskContext,
    request: &Value,
) -> TaskResult<PublicCreateWorkspaceTaskInput> {
    let fields = request_object(request)?;
    Ok(PublicCreateWorkspaceTaskInput {
        context,
        title: title_field(fields, "title", request, true)?.unwrap_or_default(),
        description: optional_string_field(fields, "description")?,
        assignee_user_id: optional_string_field(fields, "assignee_user_id")?,
        metadata: optional_object_field(fields, "metadata")?,
        preferred_language: optional_enum_field(fields, "preferred_language", PREFERRED_LANGUAGES)?,
        priority: optional_enum_field(fields, "priority", TASK_PRIORITIES)?,
        estimated_effort: optional_string_field(fields, "estimated_effort")?,
        blocker_reason: optional_string_field(fields, "blocker_reason")?,
    })
}

fn parse_update_request(request: &Value) -> TaskResult<PublicUpdateWorkspaceTaskFields> {
    let fields = request_object(request)?;
    Ok(PublicUpdateWorkspaceTaskFields {
        title: title_field(fields, "title", request, false)?,
        description: optional_string_field(fields, "description")?,
        assignee_user_id: optional_string_field(fields, "assignee_user_id")?,
        status: optional_enum_field(fields, "status", TASK_STATUSES)?,
        metadata: optional_object_field(fields, "metadata")?,
        priority: optional_enum_field(fields, "priority", TASK_PRIORITIES)?,
        estimated_effort: optional_string_field(fields, "estimated_effort")?,
        blocker_reason: optional_string_field(fields, "blocker_reason")?,
    })
}

fn parse_assign_request(request: &Value) -> TaskResult<(String, Option<String>)> {
    let fields = request_object(request)?;
    Ok((
        required_string_field(fields, "workspace_agent_id", request)?,
        optional_enum_field(fields, "preferred_language", PREFERRED_LANGUAGES)?,
    ))
}

fn parse_recovery_request(request: &Value) -> TaskResult<PublicWorkspaceTaskRecoveryInput> {
    let fields = request_object(request)?;
    let action = required_string_field(fields, "action", request)?;
    if !RECOVERY_ACTIONS.contains(&action.as_str()) {
        return Err(field_validation_error(
            "enum",
            "action",
            "Input should be a valid recovery action",
            Value::String(action),
            None,
        ));
    }
    let reason = optional_string_field(fields, "reason")?;
    if reason
        .as_ref()
        .is_some_and(|value| value.chars().count() > MAX_REASON_CHARS)
    {
        return Err(field_validation_error(
            "string_too_long",
            "reason",
            "String should have at most 500 characters",
            fields.get("reason").cloned().unwrap_or(Value::Null),
            Some(json!({"max_length": MAX_REASON_CHARS})),
        ));
    }
    Ok(PublicWorkspaceTaskRecoveryInput {
        action,
        reason,
        workspace_agent_id: optional_string_field(fields, "workspace_agent_id")?,
    })
}

fn request_object(request: &Value) -> TaskResult<&Map<String, Value>> {
    request.as_object().ok_or_else(|| {
        body_validation_error(
            "model_attributes_type",
            None,
            "Input should be a valid dictionary or object to extract fields from",
            request.clone(),
            None,
        )
        .into()
    })
}

fn required_string_field(
    fields: &Map<String, Value>,
    field: &'static str,
    request: &Value,
) -> TaskResult<String> {
    let value = fields.get(field).ok_or_else(|| {
        field_validation_error("missing", field, "Field required", request.clone(), None)
    })?;
    value.as_str().map(str::to_string).ok_or_else(|| {
        field_validation_error(
            "string_type",
            field,
            "Input should be a valid string",
            value.clone(),
            None,
        )
    })
}

fn optional_string_field(
    fields: &Map<String, Value>,
    field: &'static str,
) -> TaskResult<Option<String>> {
    match fields.get(field) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::String(value)) => Ok(Some(value.clone())),
        Some(value) => Err(field_validation_error(
            "string_type",
            field,
            "Input should be a valid string",
            value.clone(),
            None,
        )),
    }
}

fn optional_object_field(
    fields: &Map<String, Value>,
    field: &'static str,
) -> TaskResult<Option<Value>> {
    match fields.get(field) {
        None | Some(Value::Null) => Ok(None),
        Some(value @ Value::Object(_)) => Ok(Some(value.clone())),
        Some(value) => Err(field_validation_error(
            "dict_type",
            field,
            "Input should be a valid dictionary",
            value.clone(),
            None,
        )),
    }
}

fn optional_enum_field(
    fields: &Map<String, Value>,
    field: &'static str,
    allowed: &[&str],
) -> TaskResult<Option<String>> {
    let value = optional_string_field(fields, field)?;
    if value
        .as_ref()
        .is_some_and(|value| !allowed.contains(&value.as_str()))
    {
        return Err(field_validation_error(
            "enum",
            field,
            "Input should be a valid enum value",
            fields.get(field).cloned().unwrap_or(Value::Null),
            None,
        ));
    }
    Ok(value)
}

fn title_field(
    fields: &Map<String, Value>,
    field: &'static str,
    request: &Value,
    required: bool,
) -> TaskResult<Option<String>> {
    let title = if required {
        Some(required_string_field(fields, field, request)?)
    } else {
        optional_string_field(fields, field)?
    };
    let Some(title) = title else {
        return Ok(None);
    };
    let chars = title.chars().count();
    if chars == 0 || chars > MAX_TITLE_CHARS {
        let (error_type, message, context) = if chars == 0 {
            (
                "string_too_short",
                "String should have at least 1 character",
                json!({"min_length": 1}),
            )
        } else {
            (
                "string_too_long",
                "String should have at most 255 characters",
                json!({"max_length": MAX_TITLE_CHARS}),
            )
        };
        return Err(field_validation_error(
            error_type,
            field,
            message,
            Value::String(title),
            Some(context),
        ));
    }
    Ok(Some(title))
}

fn query_status(raw: Option<&str>) -> TaskResult<Option<String>> {
    let Some(status) = raw else {
        return Ok(None);
    };
    if !TASK_STATUSES.contains(&status) {
        return Err(query_validation_error(
            "enum",
            "status",
            "Input should be a valid task status",
            status,
            None,
        ));
    }
    Ok(Some(status.to_string()))
}

fn query_integer(
    field: &'static str,
    raw: Option<&str>,
    default: i64,
    minimum: i64,
    maximum: i64,
) -> TaskResult<i64> {
    let Some(raw) = raw else {
        return Ok(default);
    };
    let value = parse_pydantic_integer(raw).ok_or_else(|| {
        query_validation_error(
            "int_parsing",
            field,
            "Input should be a valid integer, unable to parse string as an integer",
            raw,
            None,
        )
    })?;
    if value < minimum {
        return Err(query_validation_error(
            "greater_than_equal",
            field,
            &format!("Input should be greater than or equal to {minimum}"),
            raw,
            Some(json!({"ge": minimum})),
        ));
    }
    if value > maximum {
        return Err(query_validation_error(
            "less_than_equal",
            field,
            &format!("Input should be less than or equal to {maximum}"),
            raw,
            Some(json!({"le": maximum})),
        ));
    }
    Ok(value)
}

fn parse_pydantic_integer(raw: &str) -> Option<i64> {
    let normalized = raw.trim();
    if let Ok(value) = normalized.parse::<i64>() {
        return Some(value);
    }
    let (integer, fraction) = normalized.split_once('.')?;
    if integer.is_empty() || fraction.is_empty() || !fraction.bytes().all(|byte| byte == b'0') {
        return None;
    }
    integer.parse::<i64>().ok()
}

fn field_validation_error(
    error_type: &'static str,
    field: &'static str,
    message: &str,
    input: Value,
    context: Option<Value>,
) -> TaskHttpError {
    body_validation_error(error_type, Some(field), message, input, context).into()
}

fn query_validation_error(
    error_type: &'static str,
    field: &'static str,
    message: &str,
    input: &str,
    context: Option<Value>,
) -> TaskHttpError {
    let mut detail = json!({
        "type": error_type,
        "loc": ["query", field],
        "msg": message,
        "input": input,
    });
    if let Some(context) = context {
        detail["ctx"] = context;
    }
    ApiError::Validation(json!([detail])).into()
}

fn map_task_error(error: PublicWorkspaceTaskError) -> TaskHttpError {
    if matches!(
        &error,
        PublicWorkspaceTaskError::StructuredAuthorityRequired
    ) {
        return TaskHttpError::response(
            StatusCode::FORBIDDEN,
            "Only workspace plan leader authority may perform this action",
        );
    }
    if matches!(&error, PublicWorkspaceTaskError::BindingWorkspaceMismatch) {
        return TaskHttpError::response(
            StatusCode::BAD_REQUEST,
            "Workspace agent binding does not belong to workspace",
        );
    }
    if let PublicWorkspaceTaskError::InvalidTransition { from, to } = &error
        && from == "todo"
        && to == "done"
    {
        return TaskHttpError::response(
            StatusCode::BAD_REQUEST,
            "Cannot transition task status from todo to done",
        );
    }
    match error.kind() {
        PublicWorkspaceTaskErrorKind::InvalidRequest => {
            TaskHttpError::response(StatusCode::BAD_REQUEST, "Invalid workspace task request")
        }
        PublicWorkspaceTaskErrorKind::NotFound => {
            TaskHttpError::response(StatusCode::NOT_FOUND, "Workspace task not found")
        }
        PublicWorkspaceTaskErrorKind::Forbidden => {
            TaskHttpError::response(StatusCode::FORBIDDEN, "Access denied")
        }
        PublicWorkspaceTaskErrorKind::Conflict => {
            TaskHttpError::response(StatusCode::CONFLICT, "Workspace task authority conflict")
        }
        PublicWorkspaceTaskErrorKind::Unavailable => {
            ApiError::InvalidDatabase(error.to_string()).into()
        }
    }
}

type TaskResult<T> = Result<T, TaskHttpError>;

#[derive(Debug)]
enum TaskHttpError {
    Core(ApiError),
    Response(StatusCode, String),
}

impl TaskHttpError {
    fn response(status: StatusCode, detail: impl Into<String>) -> Self {
        Self::Response(status, detail.into())
    }
}

impl From<ApiError> for TaskHttpError {
    fn from(error: ApiError) -> Self {
        Self::Core(error)
    }
}

impl IntoResponse for TaskHttpError {
    fn into_response(self) -> Response {
        match self {
            Self::Core(error) => error.into_response(),
            Self::Response(status, detail) => {
                (status, Json(json!({"detail": detail}))).into_response()
            }
        }
    }
}
