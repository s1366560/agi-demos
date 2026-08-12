//! Legacy-compatible public Workspace Agent Policy handlers.

use std::collections::BTreeMap;
use std::sync::Arc;

use axum::extract::rejection::{JsonRejection, QueryRejection};
use axum::extract::{Path, Query};
use axum::http::HeaderMap;
use axum::{Extension, Json};
use memstack_workspace_service::{
    PublicPatchWorkspacePolicyInput, PublicPolicyRouteTarget, PublicPutWorkspacePolicyInput,
    PublicWorkspacePolicyContext, PublicWorkspacePolicyError, PublicWorkspacePolicyErrorKind,
    PublicWorkspacePolicyService,
};
use serde::Deserialize;
use serde_json::{Map, Value, json};

use super::creation::{body_validation_error, map_public_json_rejection};
use super::public_api::caller_from_headers;
use super::{ApiError, WorkspaceCoreState};

const PATCH_FIELDS: &[&str] = &[
    "expected_revision",
    "capability_mode",
    "route",
    "reasoning_effort",
    "permission_mode",
];
const PUT_FIELDS: &[&str] = &[
    "project_id",
    "workspace_id",
    "expected_revision",
    "roles",
    "fallbacks",
];
const ROLE_FIELDS: &[&str] = &["default", "fast", "coding", "vision"];

#[derive(Debug, Deserialize)]
pub(super) struct LegacyPolicyQuery {
    project_id: String,
    workspace_id: String,
}

pub(super) async fn get_workspace_agent_policy(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
    headers: HeaderMap,
) -> Result<Json<Value>, ApiError> {
    let caller = caller_from_headers(&headers)?;
    let response = policy_service(&state)
        .get(&PublicWorkspacePolicyContext {
            tenant_id,
            project_id,
            workspace_id,
            actor_id: caller.user_id,
        })
        .await
        .map_err(map_policy_error)?;
    Ok(Json(response))
}

pub(super) async fn patch_workspace_agent_policy(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
    headers: HeaderMap,
    request: Result<Json<Value>, JsonRejection>,
) -> Result<Json<Value>, ApiError> {
    let Json(request) = request.map_err(map_public_json_rejection)?;
    let caller = caller_from_headers(&headers)?;
    let parsed = parse_patch_request(
        PublicWorkspacePolicyContext {
            tenant_id,
            project_id,
            workspace_id,
            actor_id: caller.user_id,
        },
        request,
    )?;
    let response = policy_service(&state)
        .patch(&parsed)
        .await
        .map_err(map_policy_error)?;
    Ok(Json(response))
}

pub(super) async fn get_legacy_workspace_routing_policy(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    query: Result<Query<LegacyPolicyQuery>, QueryRejection>,
    headers: HeaderMap,
) -> Result<Json<Value>, ApiError> {
    let Query(query) = query
        .map_err(|_| body_validation_error("missing", None, "Field required", Value::Null, None))?;
    let caller = caller_from_headers(&headers)?;
    let response = policy_service(&state)
        .get_legacy(&query.project_id, &query.workspace_id, &caller.user_id)
        .await
        .map_err(map_policy_error)?;
    Ok(Json(response))
}

pub(super) async fn put_legacy_workspace_routing_policy(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    headers: HeaderMap,
    request: Result<Json<Value>, JsonRejection>,
) -> Result<Json<Value>, ApiError> {
    let Json(request) = request.map_err(map_public_json_rejection)?;
    let caller = caller_from_headers(&headers)?;
    let parsed = parse_put_request(caller.user_id, request)?;
    let response = policy_service(&state)
        .put_legacy(&parsed)
        .await
        .map_err(map_policy_error)?;
    Ok(Json(response))
}

fn policy_service(state: &WorkspaceCoreState) -> PublicWorkspacePolicyService<'_> {
    PublicWorkspacePolicyService::new(
        state.db.as_ref(),
        state.sql_flavor,
        state.provider_registry.as_ref(),
    )
}

fn parse_patch_request(
    context: PublicWorkspacePolicyContext,
    request: Value,
) -> Result<PublicPatchWorkspacePolicyInput, ApiError> {
    let fields = request_fields(&request, PATCH_FIELDS)?;
    Ok(PublicPatchWorkspacePolicyInput {
        context,
        expected_revision: required_revision(fields, "expected_revision", &request)?,
        capability_mode: required_enum(
            fields,
            "capability_mode",
            &["work", "code"],
            "Input should be 'work' or 'code'",
        )?,
        route: required_route(fields.get("route"), "route", &request)?,
        reasoning_effort: required_enum(
            fields,
            "reasoning_effort",
            &["low", "medium", "high"],
            "Input should be 'low', 'medium' or 'high'",
        )?,
        permission_mode: required_enum(
            fields,
            "permission_mode",
            &["ask", "automatic", "full_access"],
            "Input should be 'ask', 'automatic' or 'full_access'",
        )?,
    })
}

fn parse_put_request(
    actor_id: String,
    request: Value,
) -> Result<PublicPutWorkspacePolicyInput, ApiError> {
    let fields = request_fields(&request, PUT_FIELDS)?;
    let roles_value = fields
        .get("roles")
        .ok_or_else(|| missing_field("roles", &request))?;
    let roles_object = roles_value.as_object().ok_or_else(|| {
        body_validation_error(
            "dict_type",
            Some("roles"),
            "Input should be a valid dictionary",
            roles_value.clone(),
            None,
        )
    })?;
    if let Some((field, value)) = roles_object
        .iter()
        .find(|(field, _)| !ROLE_FIELDS.contains(&field.as_str()))
    {
        return Err(extra_field_error(field, value.clone()));
    }
    let mut roles = BTreeMap::new();
    for role in ROLE_FIELDS {
        let route = match roles_object.get(*role) {
            None | Some(Value::Null) => None,
            Some(value) => Some(parse_route(value, role)?),
        };
        roles.insert((*role).to_string(), route);
    }
    let fallbacks_value = fields
        .get("fallbacks")
        .ok_or_else(|| missing_field("fallbacks", &request))?;
    let fallbacks = fallbacks_value.as_array().ok_or_else(|| {
        body_validation_error(
            "list_type",
            Some("fallbacks"),
            "Input should be a valid list",
            fallbacks_value.clone(),
            None,
        )
    })?;
    let fallbacks = fallbacks
        .iter()
        .enumerate()
        .map(|(index, value)| parse_route(value, &format!("fallbacks.{index}")))
        .collect::<Result<Vec<_>, _>>()?;
    Ok(PublicPutWorkspacePolicyInput {
        project_id: required_string(fields, "project_id", &request)?,
        workspace_id: required_string(fields, "workspace_id", &request)?,
        actor_id,
        expected_revision: required_revision(fields, "expected_revision", &request)?,
        roles,
        fallbacks,
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

fn required_route(
    value: Option<&Value>,
    field: &'static str,
    request: &Value,
) -> Result<PublicPolicyRouteTarget, ApiError> {
    let value = value.ok_or_else(|| missing_field(field, request))?;
    parse_route(value, field)
}

fn parse_route(value: &Value, field: &str) -> Result<PublicPolicyRouteTarget, ApiError> {
    let fields = value.as_object().ok_or_else(|| {
        ApiError::Validation(json!([{
            "type": "model_attributes_type",
            "loc": ["body", field],
            "msg": "Input should be a valid dictionary or object to extract fields from",
            "input": value,
        }]))
    })?;
    if let Some((extra, value)) = fields
        .iter()
        .find(|(name, _)| !["provider_id", "model_id"].contains(&name.as_str()))
    {
        return Err(extra_field_error(extra, value.clone()));
    }
    Ok(PublicPolicyRouteTarget {
        provider_id: required_string(fields, "provider_id", value)?,
        model_id: required_string(fields, "model_id", value)?,
    })
}

fn required_revision(
    fields: &Map<String, Value>,
    field: &'static str,
    request: &Value,
) -> Result<u64, ApiError> {
    let value = fields
        .get(field)
        .ok_or_else(|| missing_field(field, request))?;
    value.as_u64().ok_or_else(|| {
        body_validation_error(
            "greater_than_equal",
            Some(field),
            "Input should be greater than or equal to 0",
            value.clone(),
            Some(json!({"ge": 0})),
        )
    })
}

fn required_enum(
    fields: &Map<String, Value>,
    field: &'static str,
    allowed: &[&str],
    message: &'static str,
) -> Result<String, ApiError> {
    let value = fields
        .get(field)
        .ok_or_else(|| missing_field(field, &Value::Object(fields.clone())))?;
    let Some(value_string) = value.as_str() else {
        return Err(body_validation_error(
            "string_type",
            Some(field),
            "Input should be a valid string",
            value.clone(),
            None,
        ));
    };
    if !allowed.contains(&value_string) {
        return Err(body_validation_error(
            "literal_error",
            Some(field),
            message,
            value.clone(),
            None,
        ));
    }
    Ok(value_string.to_string())
}

fn required_string(
    fields: &Map<String, Value>,
    field: &'static str,
    request: &Value,
) -> Result<String, ApiError> {
    let value = fields
        .get(field)
        .ok_or_else(|| missing_field(field, request))?;
    value.as_str().map(str::to_string).ok_or_else(|| {
        body_validation_error(
            "string_type",
            Some(field),
            "Input should be a valid string",
            value.clone(),
            None,
        )
    })
}

fn missing_field(field: &'static str, request: &Value) -> ApiError {
    body_validation_error(
        "missing",
        Some(field),
        "Field required",
        request.clone(),
        None,
    )
}

fn extra_field_error(field: &str, value: Value) -> ApiError {
    ApiError::Validation(json!([{
        "type": "extra_forbidden",
        "loc": ["body", field],
        "msg": "Extra inputs are not permitted",
        "input": value,
    }]))
}

fn map_policy_error(error: PublicWorkspacePolicyError) -> ApiError {
    match error.kind() {
        PublicWorkspacePolicyErrorKind::Validation => match error {
            PublicWorkspacePolicyError::DefaultRouteRequired => {
                ApiError::InvalidRequest("Default model route is required".to_string())
            }
            _ => ApiError::InvalidRequest("Invalid provider route".to_string()),
        },
        PublicWorkspacePolicyErrorKind::NotFound => ApiError::NotFound,
        PublicWorkspacePolicyErrorKind::Forbidden => ApiError::Forbidden("Access denied"),
        PublicWorkspacePolicyErrorKind::Conflict => {
            ApiError::Conflict("Workspace policy revision conflict".to_string())
        }
        PublicWorkspacePolicyErrorKind::Unavailable => ApiError::InvalidDatabase(error.to_string()),
    }
}
