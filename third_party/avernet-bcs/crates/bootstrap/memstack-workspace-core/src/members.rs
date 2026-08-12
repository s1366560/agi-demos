//! Legacy-compatible public Workspace member mutation handlers.

use std::sync::Arc;

use axum::extract::Path;
use axum::extract::rejection::JsonRejection;
use axum::http::{HeaderMap, StatusCode};
use axum::{Extension, Json};
use memstack_workspace_service::{
    PublicAddWorkspaceMemberInput, PublicRemoveWorkspaceMemberInput,
    PublicUpdateWorkspaceMemberInput, PublicWorkspaceMemberMutationService, WorkspaceMemberRole,
};
use serde_json::{Map, Value, json};

use super::creation::{body_validation_error, map_public_json_rejection};
use super::mutations::{map_service_error, mutation_context};
use super::public_api::caller_from_headers;
use super::{ApiError, WorkspaceCoreState};

pub(super) async fn add_public_workspace_member(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
    headers: HeaderMap,
    request: Result<Json<Value>, JsonRejection>,
) -> Result<(StatusCode, Json<Value>), ApiError> {
    let Json(request) = request.map_err(map_public_json_rejection)?;
    let caller = caller_from_headers(&headers)?;
    let (user_id, role) = parse_add_request(request)?;
    let input = PublicAddWorkspaceMemberInput {
        context: mutation_context(
            tenant_id,
            project_id,
            workspace_id,
            caller.user_id,
            &headers,
        )?,
        user_id,
        role,
    };
    let outcome = PublicWorkspaceMemberMutationService::new(state.db.as_ref(), state.sql_flavor)
        .add(&input)
        .await
        .map_err(map_service_error)?;
    Ok((StatusCode::CREATED, Json(outcome.response)))
}

pub(super) async fn update_public_workspace_member(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id, user_id)): Path<(String, String, String, String)>,
    headers: HeaderMap,
    request: Result<Json<Value>, JsonRejection>,
) -> Result<Json<Value>, ApiError> {
    let Json(request) = request.map_err(map_public_json_rejection)?;
    let caller = caller_from_headers(&headers)?;
    let role = parse_required_role(request)?;
    let input = PublicUpdateWorkspaceMemberInput {
        context: mutation_context(
            tenant_id,
            project_id,
            workspace_id,
            caller.user_id,
            &headers,
        )?,
        user_id,
        role,
    };
    let outcome = PublicWorkspaceMemberMutationService::new(state.db.as_ref(), state.sql_flavor)
        .update(&input)
        .await
        .map_err(map_service_error)?;
    Ok(Json(outcome.response))
}

pub(super) async fn remove_public_workspace_member(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id, user_id)): Path<(String, String, String, String)>,
    headers: HeaderMap,
) -> Result<StatusCode, ApiError> {
    let caller = caller_from_headers(&headers)?;
    let input = PublicRemoveWorkspaceMemberInput {
        context: mutation_context(
            tenant_id,
            project_id,
            workspace_id,
            caller.user_id,
            &headers,
        )?,
        user_id,
    };
    let _outcome = PublicWorkspaceMemberMutationService::new(state.db.as_ref(), state.sql_flavor)
        .remove(&input)
        .await
        .map_err(map_service_error)?;
    Ok(StatusCode::NO_CONTENT)
}

fn parse_add_request(request: Value) -> Result<(String, WorkspaceMemberRole), ApiError> {
    let Some(fields) = request.as_object() else {
        return Err(body_validation_error(
            "model_attributes_type",
            None,
            "Input should be a valid dictionary or object to extract fields from",
            request,
            None,
        ));
    };
    let user_id = required_non_empty_string(fields, "user_id")?;
    let role = match fields.get("role") {
        None => WorkspaceMemberRole::Viewer,
        Some(value) => parse_role_value(value)?,
    };
    Ok((user_id, role))
}

fn parse_required_role(request: Value) -> Result<WorkspaceMemberRole, ApiError> {
    let Some(fields) = request.as_object() else {
        return Err(body_validation_error(
            "model_attributes_type",
            None,
            "Input should be a valid dictionary or object to extract fields from",
            request,
            None,
        ));
    };
    let value = fields.get("role").ok_or_else(|| {
        body_validation_error(
            "missing",
            Some("role"),
            "Field required",
            request.clone(),
            None,
        )
    })?;
    parse_role_value(value)
}

fn required_non_empty_string(
    fields: &Map<String, Value>,
    field: &'static str,
) -> Result<String, ApiError> {
    let value = fields.get(field).ok_or_else(|| {
        body_validation_error(
            "missing",
            Some(field),
            "Field required",
            Value::Object(fields.clone()),
            None,
        )
    })?;
    let value = value.as_str().ok_or_else(|| {
        body_validation_error(
            "string_type",
            Some(field),
            "Input should be a valid string",
            value.clone(),
            None,
        )
    })?;
    if value.is_empty() {
        return Err(body_validation_error(
            "string_too_short",
            Some(field),
            "String should have at least 1 character",
            Value::String(value.to_string()),
            Some(json!({"min_length": 1})),
        ));
    }
    Ok(value.to_string())
}

fn parse_role_value(value: &Value) -> Result<WorkspaceMemberRole, ApiError> {
    let role = value
        .as_str()
        .and_then(|value| WorkspaceMemberRole::parse(value).ok());
    role.ok_or_else(|| {
        body_validation_error(
            "enum",
            Some("role"),
            "Input should be 'owner', 'editor' or 'viewer'",
            value.clone(),
            Some(json!({"expected": "'owner', 'editor' or 'viewer'"})),
        )
    })
}
