//! Legacy-compatible Workspace execution diagnostics HTTP adapter.

use std::sync::Arc;

use axum::extract::{Path, Query};
use axum::http::{HeaderMap, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::get;
use axum::{Extension, Json, Router};
use memstack_workspace_service::{
    PublicWorkspaceExecutionDiagnostics, PublicWorkspaceExecutionDiagnosticsError,
    PublicWorkspaceExecutionDiagnosticsErrorKind, PublicWorkspaceExecutionDiagnosticsInput,
    PublicWorkspaceExecutionDiagnosticsService,
};
use serde::Deserialize;
use serde_json::{Value, json};

use super::public_api::caller_from_headers;
use super::{ApiError, WorkspaceCoreState};

#[derive(Debug, Deserialize)]
struct DiagnosticsQuery {
    task_limit: Option<String>,
    tool_limit_per_conversation: Option<String>,
}

pub(super) fn router() -> Router {
    Router::new().route(
        "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/execution-diagnostics",
        get(read_execution_diagnostics),
    )
}

async fn read_execution_diagnostics(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
    Query(query): Query<DiagnosticsQuery>,
    headers: HeaderMap,
) -> DiagnosticsResult<Json<PublicWorkspaceExecutionDiagnostics>> {
    let caller = caller_from_headers(&headers)?;
    let input = PublicWorkspaceExecutionDiagnosticsInput {
        tenant_id,
        project_id,
        workspace_id,
        user_id: caller.user_id,
        task_limit: query_integer("task_limit", query.task_limit.as_deref(), 100, 1, 200)?,
        tool_limit_per_conversation: query_integer(
            "tool_limit_per_conversation",
            query.tool_limit_per_conversation.as_deref(),
            100,
            1,
            500,
        )?,
    };
    let diagnostics =
        PublicWorkspaceExecutionDiagnosticsService::new(state.db.as_ref(), state.sql_flavor)
            .read(&input)
            .await
            .map_err(map_diagnostics_error)?;
    Ok(Json(diagnostics))
}

fn query_integer(
    field: &'static str,
    raw: Option<&str>,
    default: i64,
    minimum: i64,
    maximum: i64,
) -> DiagnosticsResult<i64> {
    let Some(raw) = raw else {
        return Ok(default);
    };
    let value = raw.trim().parse::<i64>().map_err(|_| {
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
            format!("Input should be greater than or equal to {minimum}").as_str(),
            raw,
            Some(json!({"ge": minimum})),
        ));
    }
    if value > maximum {
        return Err(query_validation_error(
            "less_than_equal",
            field,
            format!("Input should be less than or equal to {maximum}").as_str(),
            raw,
            Some(json!({"le": maximum})),
        ));
    }
    Ok(value)
}

fn query_validation_error(
    error_type: &'static str,
    field: &'static str,
    message: &str,
    input: &str,
    context: Option<Value>,
) -> DiagnosticsHttpError {
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

fn map_diagnostics_error(error: PublicWorkspaceExecutionDiagnosticsError) -> DiagnosticsHttpError {
    match error.kind() {
        PublicWorkspaceExecutionDiagnosticsErrorKind::InvalidRequest => {
            DiagnosticsHttpError::response(StatusCode::BAD_REQUEST, "Invalid blackboard request")
        }
        PublicWorkspaceExecutionDiagnosticsErrorKind::NotFound => {
            DiagnosticsHttpError::response(StatusCode::NOT_FOUND, "Blackboard item not found")
        }
        PublicWorkspaceExecutionDiagnosticsErrorKind::Forbidden => {
            DiagnosticsHttpError::response(StatusCode::FORBIDDEN, "Access denied")
        }
        PublicWorkspaceExecutionDiagnosticsErrorKind::Unavailable => {
            tracing::error!(error = %error, "Workspace execution diagnostics request failed");
            DiagnosticsHttpError::response(
                StatusCode::INTERNAL_SERVER_ERROR,
                "Internal server error",
            )
        }
    }
}

type DiagnosticsResult<T> = Result<T, DiagnosticsHttpError>;

#[derive(Debug)]
enum DiagnosticsHttpError {
    Core(ApiError),
    Response(StatusCode, String),
}

impl DiagnosticsHttpError {
    fn response(status: StatusCode, detail: impl Into<String>) -> Self {
        Self::Response(status, detail.into())
    }
}

impl From<ApiError> for DiagnosticsHttpError {
    fn from(error: ApiError) -> Self {
        Self::Core(error)
    }
}

impl IntoResponse for DiagnosticsHttpError {
    fn into_response(self) -> Response {
        match self {
            Self::Core(error) => error.into_response(),
            Self::Response(status, detail) => {
                (status, Json(json!({"detail": detail}))).into_response()
            }
        }
    }
}
