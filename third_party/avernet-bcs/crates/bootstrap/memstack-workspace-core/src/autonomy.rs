//! Legacy-compatible Workspace Autonomy HTTP route.

use std::sync::Arc;

use axum::body::Bytes;
use axum::extract::Path;
use axum::http::{HeaderMap, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Extension, Json, Router};
use memstack_workspace_service::{
    PublicWorkspaceAutonomyAttention, PublicWorkspaceAutonomyAttentionError,
    PublicWorkspaceAutonomyAttentionErrorKind, PublicWorkspaceAutonomyAttentionService,
    PublicWorkspaceAutonomyContext, PublicWorkspaceAutonomyError, PublicWorkspaceAutonomyErrorKind,
    PublicWorkspaceAutonomyService, PublicWorkspaceAutonomyTickResponse,
};
use serde::Serialize;
use serde_json::{Value, json};

use super::public_api::caller_from_headers;
use super::workspace_scope::{WorkspaceScopeError, resolve_workspace_scope};
use super::{ApiError, WorkspaceCoreState};

const IDEMPOTENCY_HEADER: &str = "idempotency-key";
const IF_MATCH_HEADER: &str = "if-match";

pub(super) fn router() -> Router {
    Router::new()
        .route(
            "/api/v1/workspaces/{workspace_id}/autonomy/tick",
            post(trigger_autonomy_tick),
        )
        .route(
            "/api/v1/workspaces/{workspace_id}/autonomy/attentions",
            get(list_autonomy_attentions),
        )
        .route(
            "/api/v1/workspaces/{workspace_id}/autonomy/attentions/{attention_id}/retry",
            post(retry_autonomy_attention),
        )
        .route(
            "/api/v1/workspaces/{workspace_id}/autonomy/attentions/{attention_id}/resolve",
            post(resolve_autonomy_attention),
        )
}

#[derive(Debug, Serialize)]
struct AutonomyAttentionRetryResponse {
    attention_id: String,
    status: &'static str,
}

async fn list_autonomy_attentions(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path(workspace_id): Path<String>,
    headers: HeaderMap,
) -> Result<Json<Vec<PublicWorkspaceAutonomyAttention>>, Response> {
    let context = attention_context(&state, workspace_id.as_str(), &headers).await?;
    PublicWorkspaceAutonomyAttentionService::new(state.db.as_ref(), state.sql_flavor)
        .list_open(&context)
        .await
        .map(Json)
        .map_err(attention_error_response)
}

async fn retry_autonomy_attention(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((workspace_id, attention_id)): Path<(String, String)>,
    headers: HeaderMap,
) -> Result<Json<AutonomyAttentionRetryResponse>, Response> {
    let context = attention_context(&state, workspace_id.as_str(), &headers).await?;
    PublicWorkspaceAutonomyAttentionService::new(state.db.as_ref(), state.sql_flavor)
        .retry(
            &context,
            attention_id.as_str(),
            chrono::Utc::now().timestamp_millis(),
        )
        .await
        .map_err(attention_error_response)?;
    Ok(Json(AutonomyAttentionRetryResponse {
        attention_id,
        status: "retry_queued",
    }))
}

async fn resolve_autonomy_attention(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((workspace_id, attention_id)): Path<(String, String)>,
    headers: HeaderMap,
) -> Result<
    Json<memstack_workspace_service::PublicWorkspaceAutonomyAttentionResolveResponse>,
    Response,
> {
    let mut context = attention_context(&state, workspace_id.as_str(), &headers).await?;
    context.expected_revision =
        Some(required_revision(&headers).map_err(IntoResponse::into_response)?);
    context.idempotency_key = Some(
        super::required_header(&headers, IDEMPOTENCY_HEADER)
            .map_err(IntoResponse::into_response)?,
    );
    PublicWorkspaceAutonomyAttentionService::new(state.db.as_ref(), state.sql_flavor)
        .resolve_judge_attention(
            &context,
            attention_id.as_str(),
            chrono::Utc::now().timestamp_millis(),
        )
        .await
        .map(Json)
        .map_err(attention_error_response)
}

async fn attention_context(
    state: &WorkspaceCoreState,
    workspace_id: &str,
    headers: &HeaderMap,
) -> Result<PublicWorkspaceAutonomyContext, Response> {
    let caller = caller_from_headers(headers).map_err(IntoResponse::into_response)?;
    let scope = resolve_workspace_scope(state, workspace_id, caller.user_id.as_str())
        .await
        .map_err(scope_error_response)?;
    Ok(PublicWorkspaceAutonomyContext {
        tenant_id: scope.tenant_id,
        project_id: scope.project_id,
        workspace_id: scope.workspace_id,
        user_id: caller.user_id,
        is_superuser: caller.is_superuser,
        expected_revision: None,
        idempotency_key: None,
    })
}

async fn trigger_autonomy_tick(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path(workspace_id): Path<String>,
    headers: HeaderMap,
    body: Bytes,
) -> Result<Json<PublicWorkspaceAutonomyTickResponse>, Response> {
    let caller = caller_from_headers(&headers).map_err(IntoResponse::into_response)?;
    let scope = resolve_workspace_scope(&state, workspace_id.as_str(), caller.user_id.as_str())
        .await
        .map_err(scope_error_response)?;
    let force = parse_force(&body).map_err(IntoResponse::into_response)?;
    let context = PublicWorkspaceAutonomyContext {
        tenant_id: scope.tenant_id,
        project_id: scope.project_id,
        workspace_id: scope.workspace_id,
        user_id: caller.user_id,
        is_superuser: caller.is_superuser,
        expected_revision: optional_revision(&headers).map_err(IntoResponse::into_response)?,
        idempotency_key: optional_header(&headers, IDEMPOTENCY_HEADER)
            .map_err(IntoResponse::into_response)?,
    };
    PublicWorkspaceAutonomyService::new(
        state.db.as_ref(),
        state.sql_flavor,
        state.autonomy_judge.as_ref(),
    )
    .tick(&context, force)
    .await
    .map(|outcome| Json(outcome.response))
    .map_err(autonomy_error_response)
}

fn parse_force(body: &[u8]) -> Result<bool, ApiError> {
    if body.is_empty() {
        return Ok(false);
    }
    let value: Value = serde_json::from_slice(body)
        .map_err(|_| ApiError::Validation(json!([{"type": "json_invalid", "loc": ["body"]}])))?;
    if value.is_null() {
        return Ok(false);
    }
    let Some(fields) = value.as_object() else {
        return Err(ApiError::Validation(json!([{
            "type": "model_attributes_type",
            "loc": ["body"],
            "msg": "Input should be a valid dictionary or object to extract fields from",
            "input": value
        }])));
    };
    if let Some((field, input)) = fields.iter().find(|(field, _)| field.as_str() != "force") {
        return Err(ApiError::Validation(json!([{
            "type": "extra_forbidden",
            "loc": ["body", field],
            "msg": "Extra inputs are not permitted",
            "input": input
        }])));
    }
    match fields.get("force") {
        None | Some(Value::Null) => Ok(false),
        Some(Value::Bool(force)) => Ok(*force),
        Some(input) => Err(ApiError::Validation(json!([{
            "type": "bool_type",
            "loc": ["body", "force"],
            "msg": "Input should be a valid boolean",
            "input": input
        }]))),
    }
}

fn optional_revision(headers: &HeaderMap) -> Result<Option<u64>, ApiError> {
    optional_header(headers, IF_MATCH_HEADER)?
        .map(|value| {
            let value = value.trim();
            let value = value.strip_prefix("W/").unwrap_or(value);
            let value = value
                .strip_prefix('"')
                .and_then(|value| value.strip_suffix('"'))
                .unwrap_or(value);
            value.parse::<u64>().map_err(|_| {
                ApiError::InvalidRequest(
                    "If-Match must contain a non-negative Workspace revision".to_string(),
                )
            })
        })
        .transpose()
}

fn required_revision(headers: &HeaderMap) -> Result<u64, ApiError> {
    optional_revision(headers)?
        .ok_or_else(|| ApiError::InvalidRequest("missing If-Match header".to_string()))
}

fn optional_header(headers: &HeaderMap, name: &'static str) -> Result<Option<String>, ApiError> {
    headers
        .get(name)
        .map(|value| {
            value
                .to_str()
                .map(str::to_string)
                .map_err(|_| ApiError::InvalidRequest(format!("Invalid {name} header")))
        })
        .transpose()
}

fn scope_error_response(error: WorkspaceScopeError) -> Response {
    match error {
        WorkspaceScopeError::NotFound => (StatusCode::NOT_FOUND, "Workspace not found"),
        WorkspaceScopeError::AccessRequired => (StatusCode::FORBIDDEN, "Access denied"),
        WorkspaceScopeError::InvalidRecord(_) | WorkspaceScopeError::Database(_) => (
            StatusCode::INTERNAL_SERVER_ERROR,
            "Workspace autonomy unavailable",
        ),
    }
    .into_response()
}

fn autonomy_error_response(error: PublicWorkspaceAutonomyError) -> Response {
    match error.kind() {
        PublicWorkspaceAutonomyErrorKind::InvalidRequest => (
            StatusCode::UNPROCESSABLE_ENTITY,
            "Invalid Workspace autonomy request",
        ),
        PublicWorkspaceAutonomyErrorKind::NotFound => {
            (StatusCode::NOT_FOUND, "Workspace not found")
        }
        PublicWorkspaceAutonomyErrorKind::Forbidden => (StatusCode::FORBIDDEN, "Access denied"),
        PublicWorkspaceAutonomyErrorKind::Conflict => {
            (StatusCode::CONFLICT, "Workspace autonomy conflict")
        }
        PublicWorkspaceAutonomyErrorKind::Unavailable => (
            StatusCode::SERVICE_UNAVAILABLE,
            "Workspace autonomy unavailable",
        ),
    }
    .into_response()
}

fn attention_error_response(error: PublicWorkspaceAutonomyAttentionError) -> Response {
    match error.kind() {
        PublicWorkspaceAutonomyAttentionErrorKind::InvalidRequest => (
            StatusCode::UNPROCESSABLE_ENTITY,
            "Invalid Workspace autonomy attention request",
        ),
        PublicWorkspaceAutonomyAttentionErrorKind::Forbidden => {
            (StatusCode::FORBIDDEN, "Workspace editor access required")
        }
        PublicWorkspaceAutonomyAttentionErrorKind::Conflict => (
            StatusCode::CONFLICT,
            "Workspace autonomy attention conflict",
        ),
        PublicWorkspaceAutonomyAttentionErrorKind::Unavailable => (
            StatusCode::INTERNAL_SERVER_ERROR,
            "Workspace autonomy attention unavailable",
        ),
    }
    .into_response()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn optional_body_defaults_force_and_rejects_unknown_fields() {
        assert_eq!(parse_force(b"").ok(), Some(false));
        assert_eq!(parse_force(b"null").ok(), Some(false));
        assert_eq!(parse_force(br#"{"force":true}"#).ok(), Some(true));
        assert!(parse_force(br#"{"force":false,"mode":"auto"}"#).is_err());
    }
}
