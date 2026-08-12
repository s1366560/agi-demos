//! Legacy-compatible public Workspace Agent mutation handlers.

use std::sync::Arc;

use axum::extract::Path;
use axum::extract::rejection::JsonRejection;
use axum::http::{HeaderMap, StatusCode};
use axum::{Extension, Json};
use memstack_workspace_service::{
    PublicBindWorkspaceAgentInput, PublicUnbindWorkspaceAgentInput,
    PublicUpdateWorkspaceAgentInput, PublicWorkspaceAgentMutationService,
};
use serde_json::{Map, Value, json};

use super::creation::{body_validation_error, map_public_json_rejection};
use super::mutations::{map_service_error, mutation_context};
use super::public_api::caller_from_headers;
use super::{ApiError, WorkspaceCoreState};

const DISPLAY_NAME_MAX_CHARS: usize = 120;
const DESCRIPTION_MAX_CHARS: usize = 500;
const THEME_COLOR_MAX_CHARS: usize = 32;
const LABEL_MAX_CHARS: usize = 64;
const MAX_HEX_COORDINATE: i64 = 24;
const CREATE_FIELDS: &[&str] = &[
    "agent_id",
    "display_name",
    "description",
    "config",
    "is_active",
    "hex_q",
    "hex_r",
    "theme_color",
    "label",
];
const UPDATE_FIELDS: &[&str] = &[
    "display_name",
    "description",
    "config",
    "is_active",
    "hex_q",
    "hex_r",
    "theme_color",
    "label",
];

pub(super) async fn bind_workspace_agent(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
    headers: HeaderMap,
    request: Result<Json<Value>, JsonRejection>,
) -> Result<(StatusCode, Json<Value>), ApiError> {
    let Json(request) = request.map_err(map_public_json_rejection)?;
    let caller = caller_from_headers(&headers)?;
    let input = parse_bind_request(
        mutation_context(
            tenant_id,
            project_id,
            workspace_id,
            caller.user_id,
            &headers,
        )?,
        request,
    )?;
    let outcome = PublicWorkspaceAgentMutationService::new(
        state.db.as_ref(),
        state.sql_flavor,
        state.agent_registry.as_ref(),
    )
    .bind(&input)
    .await
    .map_err(map_service_error)?;
    Ok((StatusCode::CREATED, Json(outcome.response)))
}

pub(super) async fn update_workspace_agent(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id, workspace_agent_id)): Path<(
        String,
        String,
        String,
        String,
    )>,
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
        workspace_agent_id,
        request,
    )?;
    let outcome = PublicWorkspaceAgentMutationService::new(
        state.db.as_ref(),
        state.sql_flavor,
        state.agent_registry.as_ref(),
    )
    .update(&input)
    .await
    .map_err(map_service_error)?;
    Ok(Json(outcome.response))
}

pub(super) async fn unbind_workspace_agent(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id, workspace_agent_id)): Path<(
        String,
        String,
        String,
        String,
    )>,
    headers: HeaderMap,
) -> Result<StatusCode, ApiError> {
    let caller = caller_from_headers(&headers)?;
    let input = PublicUnbindWorkspaceAgentInput {
        context: mutation_context(
            tenant_id,
            project_id,
            workspace_id,
            caller.user_id,
            &headers,
        )?,
        workspace_agent_id,
    };
    let _outcome = PublicWorkspaceAgentMutationService::new(
        state.db.as_ref(),
        state.sql_flavor,
        state.agent_registry.as_ref(),
    )
    .unbind(&input)
    .await
    .map_err(map_service_error)?;
    Ok(StatusCode::NO_CONTENT)
}

fn parse_bind_request(
    context: memstack_workspace_service::PublicWorkspaceMutationContext,
    request: Value,
) -> Result<PublicBindWorkspaceAgentInput, ApiError> {
    let fields = request_fields(&request, CREATE_FIELDS)?;
    let agent_id = required_string(fields, "agent_id", &request)?;
    let config = match fields.get("config") {
        None => json!({}),
        Some(value) if value.is_object() => value.clone(),
        Some(value) => {
            return Err(body_validation_error(
                "dict_type",
                Some("config"),
                "Input should be a valid dictionary",
                value.clone(),
                None,
            ));
        }
    };
    Ok(PublicBindWorkspaceAgentInput {
        context,
        agent_id,
        display_name: optional_bounded_string(fields, "display_name", DISPLAY_NAME_MAX_CHARS)?,
        description: optional_bounded_string(fields, "description", DESCRIPTION_MAX_CHARS)?,
        config,
        is_active: optional_bool(fields, "is_active")?.unwrap_or(true),
        hex_q: optional_hex(fields, "hex_q")?,
        hex_r: optional_hex(fields, "hex_r")?,
        theme_color: optional_bounded_string(fields, "theme_color", THEME_COLOR_MAX_CHARS)?,
        label: optional_bounded_string(fields, "label", LABEL_MAX_CHARS)?,
    })
}

fn parse_update_request(
    context: memstack_workspace_service::PublicWorkspaceMutationContext,
    workspace_agent_id: String,
    request: Value,
) -> Result<PublicUpdateWorkspaceAgentInput, ApiError> {
    let fields = request_fields(&request, UPDATE_FIELDS)?;
    let config = match fields.get("config") {
        None | Some(Value::Null) => None,
        Some(value) if value.is_object() => Some(value.clone()),
        Some(value) => {
            return Err(body_validation_error(
                "dict_type",
                Some("config"),
                "Input should be a valid dictionary",
                value.clone(),
                None,
            ));
        }
    };
    Ok(PublicUpdateWorkspaceAgentInput {
        context,
        workspace_agent_id,
        display_name: optional_bounded_string(fields, "display_name", DISPLAY_NAME_MAX_CHARS)?,
        description: optional_bounded_string(fields, "description", DESCRIPTION_MAX_CHARS)?,
        config,
        is_active: optional_bool(fields, "is_active")?,
        hex_q: optional_hex(fields, "hex_q")?,
        hex_r: optional_hex(fields, "hex_r")?,
        theme_color: optional_bounded_string(fields, "theme_color", THEME_COLOR_MAX_CHARS)?,
        label: optional_bounded_string(fields, "label", LABEL_MAX_CHARS)?,
    })
}

fn request_fields<'a>(
    request: &'a Value,
    allowed: &[&str],
) -> Result<&'a Map<String, Value>, ApiError> {
    let Some(fields) = request.as_object() else {
        return Err(body_validation_error(
            "model_attributes_type",
            None,
            "Input should be a valid dictionary or object to extract fields from",
            request.clone(),
            None,
        ));
    };
    if let Some((field, value)) = fields
        .iter()
        .find(|(field, _)| !allowed.contains(&field.as_str()))
    {
        return Err(extra_field_error(field, value.clone()));
    }
    Ok(fields)
}

fn required_string(
    fields: &Map<String, Value>,
    field: &'static str,
    request: &Value,
) -> Result<String, ApiError> {
    let value = fields.get(field).ok_or_else(|| {
        body_validation_error(
            "missing",
            Some(field),
            "Field required",
            request.clone(),
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

fn optional_bounded_string(
    fields: &Map<String, Value>,
    field: &'static str,
    max_chars: usize,
) -> Result<Option<String>, ApiError> {
    let Some(value) = fields.get(field) else {
        return Ok(None);
    };
    if value.is_null() {
        return Ok(None);
    }
    let text = value.as_str().ok_or_else(|| {
        body_validation_error(
            "string_type",
            Some(field),
            "Input should be a valid string",
            value.clone(),
            None,
        )
    })?;
    let actual_chars = text.chars().count();
    if actual_chars > max_chars {
        return Err(body_validation_error(
            "string_too_long",
            Some(field),
            &format!("String should have at most {max_chars} characters"),
            value.clone(),
            Some(json!({"max_length": max_chars})),
        ));
    }
    Ok(Some(text.to_string()))
}

fn optional_bool(
    fields: &Map<String, Value>,
    field: &'static str,
) -> Result<Option<bool>, ApiError> {
    match fields.get(field) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Bool(value)) => Ok(Some(*value)),
        Some(value) => Err(body_validation_error(
            "bool_type",
            Some(field),
            "Input should be a valid boolean",
            value.clone(),
            None,
        )),
    }
}

fn optional_hex(fields: &Map<String, Value>, field: &'static str) -> Result<Option<i64>, ApiError> {
    let Some(value) = fields.get(field) else {
        return Ok(None);
    };
    if value.is_null() {
        return Ok(None);
    }
    let Some(coordinate) = value.as_i64() else {
        return Err(body_validation_error(
            "int_type",
            Some(field),
            "Input should be a valid integer",
            value.clone(),
            None,
        ));
    };
    if coordinate < -MAX_HEX_COORDINATE {
        return Err(body_validation_error(
            "greater_than_equal",
            Some(field),
            "Input should be greater than or equal to -24",
            value.clone(),
            Some(json!({"ge": -MAX_HEX_COORDINATE})),
        ));
    }
    if coordinate > MAX_HEX_COORDINATE {
        return Err(body_validation_error(
            "less_than_equal",
            Some(field),
            "Input should be less than or equal to 24",
            value.clone(),
            Some(json!({"le": MAX_HEX_COORDINATE})),
        ));
    }
    Ok(Some(coordinate))
}

fn extra_field_error(field: &str, input: Value) -> ApiError {
    ApiError::Validation(json!([{
        "type": "extra_forbidden",
        "loc": ["body", field],
        "msg": "Extra inputs are not permitted",
        "input": input,
    }]))
}
