//! Service-authenticated structured Task routes for Agent Runtime.

use std::sync::Arc;

use axum::extract::{Path, Query};
use axum::http::StatusCode;
use axum::routing::{get, post};
use axum::{Extension, Json, Router};
use memstack_workspace_service::{
    StructuredTaskActor, StructuredTaskContext, StructuredTaskError, StructuredTaskErrorKind,
    StructuredTaskMutationFields, StructuredTaskService, StructuredWorkspaceTask,
};
use serde::Deserialize;
use serde_json::Value;

use super::{ApiError, WorkspaceCoreState};

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct StructuredTaskScope {
    tenant_id: String,
    project_id: String,
    workspace_id: String,
    user_id: String,
    leader_agent_id: String,
    expected_revision: Option<u64>,
    idempotency_key: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RootChildrenQuery {
    tenant_id: String,
    project_id: String,
    workspace_id: String,
    user_id: String,
    leader_agent_id: String,
    root_goal_task_id: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct CreateExecutionTaskRequest {
    context: StructuredTaskScope,
    root_goal_task_id: String,
    task: StructuredTaskMutationFields,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct UpdateStructuredTaskRequest {
    context: StructuredTaskScope,
    task: StructuredTaskMutationFields,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct StructuredTaskActionRequest {
    context: StructuredTaskScope,
    workspace_agent_id: Option<String>,
}

pub(super) fn router() -> Router {
    Router::new()
        .route(
            "/internal/v1/structured-tasks",
            get(list_root_children).post(create_execution_task),
        )
        .route(
            "/internal/v1/structured-tasks/{task_id}",
            post(update_structured_task).delete(delete_structured_task),
        )
        .route(
            "/internal/v1/structured-tasks/{task_id}/read",
            post(get_structured_task),
        )
        .route(
            "/internal/v1/structured-tasks/{task_id}/assign-and-start",
            post(assign_and_start_structured_task),
        )
}

async fn list_root_children(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Query(query): Query<RootChildrenQuery>,
) -> Result<Json<Vec<StructuredWorkspaceTask>>, ApiError> {
    let context = StructuredTaskContext {
        tenant_id: query.tenant_id,
        project_id: query.project_id,
        workspace_id: query.workspace_id,
        actor: StructuredTaskActor {
            user_id: query.user_id,
            leader_agent_id: query.leader_agent_id,
        },
        expected_revision: None,
        idempotency_key: None,
    };
    structured_task_service(&state)
        .list_root_children(&context, query.root_goal_task_id.as_str())
        .await
        .map(Json)
        .map_err(map_structured_task_error)
}

async fn create_execution_task(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Json(request): Json<CreateExecutionTaskRequest>,
) -> Result<(StatusCode, Json<Value>), ApiError> {
    let context = context(request.context);
    let outcome = structured_task_service(&state)
        .create_execution_task(&context, &request.task, request.root_goal_task_id.as_str())
        .await
        .map_err(map_structured_task_error)?;
    Ok((
        StatusCode::CREATED,
        Json(serde_json::to_value(outcome).map_err(ApiError::Json)?),
    ))
}

async fn get_structured_task(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path(task_id): Path<String>,
    Json(request): Json<StructuredTaskActionRequest>,
) -> Result<Json<StructuredWorkspaceTask>, ApiError> {
    structured_task_service(&state)
        .get(&context(request.context), task_id.as_str())
        .await
        .map(Json)
        .map_err(map_structured_task_error)
}

async fn update_structured_task(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path(task_id): Path<String>,
    Json(request): Json<UpdateStructuredTaskRequest>,
) -> Result<Json<Value>, ApiError> {
    let outcome = structured_task_service(&state)
        .update(&context(request.context), task_id.as_str(), &request.task)
        .await
        .map_err(map_structured_task_error)?;
    Ok(Json(serde_json::to_value(outcome).map_err(ApiError::Json)?))
}

async fn assign_and_start_structured_task(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path(task_id): Path<String>,
    Json(request): Json<StructuredTaskActionRequest>,
) -> Result<Json<Value>, ApiError> {
    let binding_id = request
        .workspace_agent_id
        .as_deref()
        .ok_or_else(|| ApiError::InvalidRequest("workspace_agent_id is required".to_string()))?;
    let outcome = structured_task_service(&state)
        .assign_and_start(&context(request.context), task_id.as_str(), binding_id)
        .await
        .map_err(map_structured_task_error)?;
    Ok(Json(serde_json::to_value(outcome).map_err(ApiError::Json)?))
}

async fn delete_structured_task(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path(task_id): Path<String>,
    Json(request): Json<StructuredTaskActionRequest>,
) -> Result<Json<Value>, ApiError> {
    let outcome = structured_task_service(&state)
        .delete(&context(request.context), task_id.as_str())
        .await
        .map_err(map_structured_task_error)?;
    Ok(Json(serde_json::to_value(outcome).map_err(ApiError::Json)?))
}

fn context(scope: StructuredTaskScope) -> StructuredTaskContext {
    StructuredTaskContext {
        tenant_id: scope.tenant_id,
        project_id: scope.project_id,
        workspace_id: scope.workspace_id,
        actor: StructuredTaskActor {
            user_id: scope.user_id,
            leader_agent_id: scope.leader_agent_id,
        },
        expected_revision: scope.expected_revision,
        idempotency_key: scope.idempotency_key,
    }
}

fn structured_task_service(state: &WorkspaceCoreState) -> StructuredTaskService<'_> {
    StructuredTaskService::new(state.db.as_ref(), state.sql_flavor)
}

fn map_structured_task_error(error: StructuredTaskError) -> ApiError {
    match error.kind() {
        StructuredTaskErrorKind::InvalidRequest => {
            ApiError::InvalidRequest("invalid structured Workspace Task request".to_string())
        }
        StructuredTaskErrorKind::NotFound => ApiError::NotFound,
        StructuredTaskErrorKind::Forbidden => ApiError::Forbidden("Access denied"),
        StructuredTaskErrorKind::Conflict => ApiError::Conflict(
            "Workspace task mutation conflicted with current authority".to_string(),
        ),
        StructuredTaskErrorKind::Unavailable => {
            tracing::error!(error = %error, "structured Workspace Task request failed");
            ApiError::InvalidDatabase("structured Workspace Task authority failed".to_string())
        }
    }
}
