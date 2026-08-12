//! Legacy-compatible public Workspace update and delete handlers.

use std::sync::Arc;

use axum::extract::Path;
use axum::extract::rejection::JsonRejection;
use axum::http::{HeaderMap, StatusCode};
use axum::{Extension, Json};
use memstack_workspace_service::{
    PublicDeleteWorkspaceInput, PublicUpdateWorkspaceInput, PublicWorkspaceMutationContext,
    PublicWorkspaceMutationError, PublicWorkspaceMutationErrorKind, PublicWorkspaceMutationService,
};
use serde_json::{Map, Value, json};

use super::creation::{
    body_validation_error, map_public_json_rejection, optional_header, optional_string_field,
};
use super::public_api::caller_from_headers;
use super::{ApiError, WorkspaceCoreState};

const IDEMPOTENCY_HEADER: &str = "idempotency-key";
const IF_MATCH_HEADER: &str = "if-match";
const WORKSPACE_NAME_MAX_CHARS: usize = 255;

pub(super) async fn update_public_workspace(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
    headers: HeaderMap,
    request: Result<Json<Value>, JsonRejection>,
) -> Result<Json<Value>, ApiError> {
    let Json(request) = request.map_err(map_public_json_rejection)?;
    let caller = caller_from_headers(&headers)?;
    let input = parse_update_request(
        mutation_context(
            tenant_id,
            project_id,
            workspace_id,
            caller.user_id,
            &headers,
        )?,
        request,
    )?;
    let outcome = PublicWorkspaceMutationService::new(state.db.as_ref(), state.sql_flavor)
        .update(&input)
        .await
        .map_err(map_service_error)?;
    Ok(Json(outcome.response))
}

pub(super) async fn delete_public_workspace(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
    headers: HeaderMap,
) -> Result<StatusCode, ApiError> {
    let caller = caller_from_headers(&headers)?;
    let input = PublicDeleteWorkspaceInput {
        context: mutation_context(
            tenant_id,
            project_id,
            workspace_id,
            caller.user_id,
            &headers,
        )?,
    };
    let _outcome = PublicWorkspaceMutationService::new(state.db.as_ref(), state.sql_flavor)
        .delete(&input)
        .await
        .map_err(map_service_error)?;
    Ok(StatusCode::NO_CONTENT)
}

pub(super) fn mutation_context(
    tenant_id: String,
    project_id: String,
    workspace_id: String,
    user_id: String,
    headers: &HeaderMap,
) -> Result<PublicWorkspaceMutationContext, ApiError> {
    Ok(PublicWorkspaceMutationContext {
        tenant_id,
        project_id,
        workspace_id,
        user_id,
        expected_revision: optional_header(headers, IF_MATCH_HEADER)?
            .map(|value| parse_if_match(&value))
            .transpose()?,
        idempotency_key: optional_header(headers, IDEMPOTENCY_HEADER)?,
    })
}

fn parse_if_match(value: &str) -> Result<u64, ApiError> {
    let value = value.trim();
    let value = value.strip_prefix("W/").unwrap_or(value);
    let value = value
        .strip_prefix('"')
        .and_then(|value| value.strip_suffix('"'))
        .unwrap_or(value);
    value.parse::<u64>().map_err(|_| {
        ApiError::InvalidRequest("If-Match must contain a non-negative Workspace revision".into())
    })
}

fn parse_update_request(
    context: PublicWorkspaceMutationContext,
    request: Value,
) -> Result<PublicUpdateWorkspaceInput, ApiError> {
    let Some(fields) = request.as_object() else {
        return Err(body_validation_error(
            "model_attributes_type",
            None,
            "Input should be a valid dictionary or object to extract fields from",
            request,
            None,
        ));
    };
    let name = optional_workspace_name(fields)?;
    let description = optional_string_field(fields, "description")?;
    let is_archived = match fields.get("is_archived") {
        None | Some(Value::Null) => None,
        Some(Value::Bool(value)) => Some(*value),
        Some(value) => {
            return Err(body_validation_error(
                "bool_type",
                Some("is_archived"),
                "Input should be a valid boolean",
                value.clone(),
                None,
            ));
        }
    };
    let metadata = match fields.get("metadata") {
        None | Some(Value::Null) => None,
        Some(value) if value.is_object() => Some(value.clone()),
        Some(value) => {
            return Err(body_validation_error(
                "dict_type",
                Some("metadata"),
                "Input should be a valid dictionary",
                value.clone(),
                None,
            ));
        }
    };
    Ok(PublicUpdateWorkspaceInput {
        context,
        name,
        description,
        is_archived,
        metadata,
    })
}

fn optional_workspace_name(fields: &Map<String, Value>) -> Result<Option<String>, ApiError> {
    let Some(value) = fields.get("name") else {
        return Ok(None);
    };
    if value.is_null() {
        return Ok(None);
    }
    let name = value.as_str().ok_or_else(|| {
        body_validation_error(
            "string_type",
            Some("name"),
            "Input should be a valid string",
            value.clone(),
            None,
        )
    })?;
    let name_chars = name.chars().count();
    if name_chars == 0 {
        return Err(body_validation_error(
            "string_too_short",
            Some("name"),
            "String should have at least 1 character",
            value.clone(),
            Some(json!({"min_length": 1})),
        ));
    }
    if name_chars > WORKSPACE_NAME_MAX_CHARS {
        return Err(body_validation_error(
            "string_too_long",
            Some("name"),
            "String should have at most 255 characters",
            value.clone(),
            Some(json!({"max_length": WORKSPACE_NAME_MAX_CHARS})),
        ));
    }
    Ok(Some(name.to_string()))
}

pub(super) fn map_service_error(error: PublicWorkspaceMutationError) -> ApiError {
    match error.kind() {
        PublicWorkspaceMutationErrorKind::Validation => {
            ApiError::InvalidRequest("Invalid workspace request".to_string())
        }
        PublicWorkspaceMutationErrorKind::NotFound => ApiError::NotFound,
        PublicWorkspaceMutationErrorKind::Forbidden => ApiError::Forbidden("Access denied"),
        PublicWorkspaceMutationErrorKind::Conflict => ApiError::Conflict(error.to_string()),
        PublicWorkspaceMutationErrorKind::Unavailable => {
            ApiError::InvalidDatabase(error.to_string())
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn if_match_accepts_plain_strong_and_weak_revision_tags() {
        assert_eq!(parse_if_match("7").ok(), Some(7));
        assert_eq!(parse_if_match("\"8\"").ok(), Some(8));
        assert_eq!(parse_if_match("W/\"9\"").ok(), Some(9));
        assert!(parse_if_match("latest").is_err());
    }
}
