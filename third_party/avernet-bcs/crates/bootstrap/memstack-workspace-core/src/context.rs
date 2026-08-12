//! Legacy-compatible public Workspace Context handlers.

use std::sync::Arc;

use axum::extract::rejection::JsonRejection;
use axum::http::{HeaderMap, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::{Extension, Json};
use memstack_workspace_service::{
    PublicSwitchWorkspaceContextInput, PublicWorkspaceContextAccess, PublicWorkspaceContextError,
    PublicWorkspaceContextErrorKind, PublicWorkspaceContextService,
    PublicWorkspaceContextSwitchOutcome,
};
use serde_json::{Map, Value, json};

use super::creation::{body_validation_error, map_public_json_rejection, optional_header};
use super::{ApiError, WorkspaceCoreState, required_header};

const USER_HEADER: &str = "x-memstack-user-id";
const API_KEY_HEADER: &str = "x-memstack-api-key-id";
const SWITCH_FIELDS: &[&str] = &[
    "tenant_id",
    "project_id",
    "expected_revision",
    "idempotency_key",
];

pub(super) async fn get_workspace_context(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    headers: HeaderMap,
) -> Result<Json<PublicWorkspaceContextAccess>, Response> {
    let user_id = required_header(&headers, USER_HEADER).map_err(IntoResponse::into_response)?;
    context_service(&state)
        .get_or_initialize(&user_id)
        .await
        .map(Json)
        .map_err(context_error_response)
}

pub(super) async fn switch_workspace_context(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    headers: HeaderMap,
    request: Result<Json<Value>, JsonRejection>,
) -> Result<Json<PublicWorkspaceContextSwitchOutcome>, Response> {
    let Json(request) =
        request.map_err(|error| map_public_json_rejection(error).into_response())?;
    let user_id = required_header(&headers, USER_HEADER).map_err(IntoResponse::into_response)?;
    let actor_api_key_id =
        optional_header(&headers, API_KEY_HEADER).map_err(IntoResponse::into_response)?;
    let input = parse_switch_request(user_id, actor_api_key_id, request)
        .map_err(IntoResponse::into_response)?;
    context_service(&state)
        .switch(&input)
        .await
        .map(Json)
        .map_err(context_error_response)
}

fn context_service(state: &WorkspaceCoreState) -> PublicWorkspaceContextService<'_> {
    PublicWorkspaceContextService::new(
        state.db.as_ref(),
        state.sql_flavor,
        state.context_judge.as_ref(),
    )
}

fn parse_switch_request(
    user_id: String,
    actor_api_key_id: Option<String>,
    request: Value,
) -> Result<PublicSwitchWorkspaceContextInput, ApiError> {
    let fields = request_fields(&request)?;
    let mut errors = Vec::new();
    let tenant_id = validated_string(fields, "tenant_id", &request, None, None, &mut errors);
    let project_id = validated_string(fields, "project_id", &request, None, None, &mut errors);
    let expected_revision = validated_revision(fields, &request, &mut errors);
    let idempotency_key = validated_string(
        fields,
        "idempotency_key",
        &request,
        Some(1),
        Some(255),
        &mut errors,
    );
    for (field, value) in fields
        .iter()
        .filter(|(field, _)| !SWITCH_FIELDS.contains(&field.as_str()))
    {
        errors.push(validation_detail(
            "extra_forbidden",
            Some(field),
            "Extra inputs are not permitted",
            value.clone(),
            None,
        ));
    }
    if !errors.is_empty() {
        return Err(ApiError::Validation(Value::Array(errors)));
    }
    let (Some(tenant_id), Some(project_id), Some(expected_revision), Some(idempotency_key)) =
        (tenant_id, project_id, expected_revision, idempotency_key)
    else {
        return Err(ApiError::InvalidRequest(
            "validated Workspace Context request is incomplete".to_string(),
        ));
    };
    Ok(PublicSwitchWorkspaceContextInput {
        user_id,
        actor_api_key_id,
        tenant_id,
        project_id,
        expected_revision,
        idempotency_key,
    })
}

fn request_fields(request: &Value) -> Result<&Map<String, Value>, ApiError> {
    let Some(fields) = request.as_object() else {
        return Err(body_validation_error(
            "model_attributes_type",
            None,
            "Input should be a valid dictionary or object to extract fields from",
            request.clone(),
            None,
        ));
    };
    Ok(fields)
}

fn validated_string(
    fields: &Map<String, Value>,
    field: &'static str,
    request: &Value,
    min_length: Option<usize>,
    max_length: Option<usize>,
    errors: &mut Vec<Value>,
) -> Option<String> {
    let Some(value) = fields.get(field) else {
        errors.push(validation_detail(
            "missing",
            Some(field),
            "Field required",
            request.clone(),
            None,
        ));
        return None;
    };
    let Some(value_string) = value.as_str() else {
        errors.push(validation_detail(
            "string_type",
            Some(field),
            "Input should be a valid string",
            value.clone(),
            None,
        ));
        return None;
    };
    let value_length = value_string.chars().count();
    if let Some(min_length) = min_length
        && value_length < min_length
    {
        errors.push(validation_detail(
            "string_too_short",
            Some(field),
            &format!("String should have at least {min_length} character"),
            value.clone(),
            Some(json!({"min_length": min_length})),
        ));
        return None;
    }
    if let Some(max_length) = max_length
        && value_length > max_length
    {
        errors.push(validation_detail(
            "string_too_long",
            Some(field),
            &format!("String should have at most {max_length} characters"),
            value.clone(),
            Some(json!({"max_length": max_length})),
        ));
        return None;
    }
    if value_string.trim().is_empty() {
        errors.push(validation_detail(
            "value_error",
            Some(field),
            "Value error, value must not be blank",
            value.clone(),
            Some(json!({"error": {}})),
        ));
        return None;
    }
    Some(value_string.to_string())
}

fn validated_revision(
    fields: &Map<String, Value>,
    request: &Value,
    errors: &mut Vec<Value>,
) -> Option<u64> {
    let Some(value) = fields.get("expected_revision") else {
        errors.push(validation_detail(
            "missing",
            Some("expected_revision"),
            "Field required",
            request.clone(),
            None,
        ));
        return None;
    };
    if let Some(value) = value.as_u64() {
        return Some(value);
    }
    if value.as_i64().is_some_and(|value| value < 0) {
        errors.push(validation_detail(
            "greater_than_equal",
            Some("expected_revision"),
            "Input should be greater than or equal to 0",
            value.clone(),
            Some(json!({"ge": 0})),
        ));
        return None;
    }
    if let Some(value_string) = value.as_str() {
        match value_string.trim().parse::<i128>() {
            Ok(parsed) if parsed < 0 => {
                errors.push(validation_detail(
                    "greater_than_equal",
                    Some("expected_revision"),
                    "Input should be greater than or equal to 0",
                    value.clone(),
                    Some(json!({"ge": 0})),
                ));
                return None;
            }
            Ok(parsed) => {
                if let Ok(parsed) = u64::try_from(parsed) {
                    return Some(parsed);
                }
            }
            Err(_) => {}
        }
        errors.push(validation_detail(
            "int_parsing",
            Some("expected_revision"),
            "Input should be a valid integer, unable to parse string as an integer",
            value.clone(),
            None,
        ));
        return None;
    }
    let (error_type, message) = if value.is_f64() {
        (
            "int_from_float",
            "Input should be a valid integer, got a number with a fractional part",
        )
    } else {
        ("int_type", "Input should be a valid integer")
    };
    errors.push(validation_detail(
        error_type,
        Some("expected_revision"),
        message,
        value.clone(),
        None,
    ));
    None
}

fn validation_detail(
    error_type: &str,
    field: Option<&str>,
    message: &str,
    input: Value,
    context: Option<Value>,
) -> Value {
    let mut location = vec![json!("body")];
    if let Some(field) = field {
        location.push(json!(field));
    }
    let mut detail = json!({
        "type": error_type,
        "loc": location,
        "msg": message,
        "input": input,
    });
    if let Some(context) = context {
        detail["ctx"] = context;
    }
    detail
}

fn context_error_response(error: PublicWorkspaceContextError) -> Response {
    let kind = error.kind();
    let code = match &error {
        PublicWorkspaceContextError::InvalidInput
        | PublicWorkspaceContextError::Command(_)
        | PublicWorkspaceContextError::JudgeContract(_) => "workspace_context_invalid_input",
        PublicWorkspaceContextError::Unavailable => "workspace_context_unavailable",
        PublicWorkspaceContextError::MembershipRequired => "workspace_context_membership_required",
        PublicWorkspaceContextError::ProjectUnavailable => "workspace_context_project_unavailable",
        PublicWorkspaceContextError::RevisionConflict { .. } => {
            "workspace_context_revision_conflict"
        }
        PublicWorkspaceContextError::IdempotencyConflict => {
            "workspace_context_idempotency_conflict"
        }
        PublicWorkspaceContextError::RevisionExhausted => "workspace_context_revision_exhausted",
        PublicWorkspaceContextError::Judge(_)
        | PublicWorkspaceContextError::Store(_)
        | PublicWorkspaceContextError::Json(_)
        | PublicWorkspaceContextError::AuthorityBusy => {
            return ApiError::InvalidDatabase(error.to_string()).into_response();
        }
        _ => return ApiError::InvalidDatabase(error.to_string()).into_response(),
    };
    let mut detail = json!({"code": code});
    if let PublicWorkspaceContextError::RevisionConflict { expected, actual } = error {
        detail["expected_revision"] = json!(expected);
        detail["actual_revision"] = json!(actual);
    }
    let status = match kind {
        PublicWorkspaceContextErrorKind::Validation => StatusCode::UNPROCESSABLE_ENTITY,
        PublicWorkspaceContextErrorKind::NotFound => StatusCode::NOT_FOUND,
        PublicWorkspaceContextErrorKind::Forbidden => StatusCode::FORBIDDEN,
        PublicWorkspaceContextErrorKind::Conflict => StatusCode::CONFLICT,
        PublicWorkspaceContextErrorKind::Unavailable => StatusCode::SERVICE_UNAVAILABLE,
    };
    (status, Json(json!({"detail": detail}))).into_response()
}
