//! Tenant-scoped legacy Objective HTTP handlers over the Avernet authority.

use std::sync::Arc;

use axum::body::Bytes;
use axum::extract::rejection::JsonRejection;
use axum::extract::{Path, Query};
use axum::http::{HeaderMap, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::get;
use axum::{Extension, Json, Router};
use memstack_workspace_service::{
    PublicCreateWorkspaceObjectiveInput, PublicUpdateWorkspaceObjectiveFields,
    PublicWorkspaceObjective, PublicWorkspaceObjectiveContext, PublicWorkspaceObjectiveError,
    PublicWorkspaceObjectiveErrorKind, PublicWorkspaceObjectiveService,
};
use serde::Deserialize;
use serde_json::{Map, Value, json};

use super::creation::{body_validation_error, map_public_json_rejection, optional_header};
use super::public_api::caller_from_headers;
use super::{ApiError, WorkspaceCoreState};

const IDEMPOTENCY_HEADER: &str = "idempotency-key";
const IF_MATCH_HEADER: &str = "if-match";
const OBJECTIVE_TYPES: &[&str] = &["objective", "key_result"];
const PREFERRED_LANGUAGES: &[&str] = &["en-US", "zh-CN"];

#[derive(Debug, Deserialize)]
struct ObjectiveListQuery {
    obj_type: Option<String>,
    parent_id: Option<String>,
    limit: Option<String>,
    offset: Option<String>,
}

pub(super) fn router() -> Router {
    Router::new()
        .route(
            "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/objectives",
            get(list_objectives).post(create_objective),
        )
        .route(
            "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/objectives/{objective_id}",
            get(get_objective).patch(update_objective).delete(delete_objective),
        )
        .route(
            "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/objectives/{objective_id}/project-to-task",
            axum::routing::post(project_objective_to_task),
        )
}

async fn create_objective(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
    headers: HeaderMap,
    request: Result<Json<Value>, JsonRejection>,
) -> ObjectiveResult<(StatusCode, Json<PublicWorkspaceObjective>)> {
    let Json(request) = request.map_err(map_public_json_rejection)?;
    let fields = request_object(&request)?;
    let input = PublicCreateWorkspaceObjectiveInput {
        context: objective_context(tenant_id, project_id, workspace_id, &headers)?,
        title: required_text(fields, "title", &request, 255)?,
        description: optional_text(fields, "description")?,
        objective_type: optional_enum(fields, "obj_type", OBJECTIVE_TYPES)?
            .unwrap_or_else(|| "objective".to_string()),
        parent_objective_id: optional_text(fields, "parent_id")?,
        progress: optional_number(fields, "progress")?.unwrap_or(0.0),
    };
    let outcome = service(&state)
        .create(&input)
        .await
        .map_err(map_objective_error)?;
    Ok((StatusCode::CREATED, Json(outcome.objective)))
}

async fn list_objectives(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
    Query(query): Query<ObjectiveListQuery>,
    headers: HeaderMap,
) -> ObjectiveResult<Json<Value>> {
    if query
        .obj_type
        .as_ref()
        .is_some_and(|value| !OBJECTIVE_TYPES.contains(&value.as_str()))
    {
        return Err(query_validation_error(
            "obj_type",
            "Input should be a valid enum value",
        ));
    }
    let limit = query_integer("limit", query.limit.as_deref(), 100, 1, 500)?;
    let offset = query_integer("offset", query.offset.as_deref(), 0, 0, i64::MAX)?;
    let context = objective_context(tenant_id, project_id, workspace_id, &headers)?;
    let items = service(&state)
        .list(
            &context,
            query.obj_type.as_deref(),
            query.parent_id.as_deref(),
            limit,
            offset,
        )
        .await
        .map_err(map_objective_error)?;
    Ok(Json(json!({"total": items.len(), "items": items})))
}

async fn get_objective(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id, objective_id)): Path<(
        String,
        String,
        String,
        String,
    )>,
    headers: HeaderMap,
) -> ObjectiveResult<Json<PublicWorkspaceObjective>> {
    let context = objective_context(tenant_id, project_id, workspace_id, &headers)?;
    service(&state)
        .get(&context, objective_id.as_str())
        .await
        .map(Json)
        .map_err(map_objective_error)
}

async fn update_objective(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id, objective_id)): Path<(
        String,
        String,
        String,
        String,
    )>,
    headers: HeaderMap,
    request: Result<Json<Value>, JsonRejection>,
) -> ObjectiveResult<Json<PublicWorkspaceObjective>> {
    let Json(request) = request.map_err(map_public_json_rejection)?;
    let fields = request_object(&request)?;
    let context = objective_context(tenant_id, project_id, workspace_id, &headers)?;
    let update = PublicUpdateWorkspaceObjectiveFields {
        title: optional_limited_text(fields, "title", 255)?,
        description: optional_text(fields, "description")?,
        objective_type: optional_enum(fields, "obj_type", OBJECTIVE_TYPES)?,
        parent_objective_id: optional_text(fields, "parent_id")?,
        progress: optional_number(fields, "progress")?,
    };
    let outcome = service(&state)
        .update(&context, objective_id.as_str(), &update)
        .await
        .map_err(map_objective_error)?;
    Ok(Json(outcome.objective))
}

async fn delete_objective(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id, objective_id)): Path<(
        String,
        String,
        String,
        String,
    )>,
    headers: HeaderMap,
) -> ObjectiveResult<StatusCode> {
    let context = objective_context(tenant_id, project_id, workspace_id, &headers)?;
    service(&state)
        .delete(&context, objective_id.as_str())
        .await
        .map_err(map_objective_error)?;
    Ok(StatusCode::NO_CONTENT)
}

async fn project_objective_to_task(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id, objective_id)): Path<(
        String,
        String,
        String,
        String,
    )>,
    headers: HeaderMap,
    body: Bytes,
) -> ObjectiveResult<(
    StatusCode,
    Json<memstack_workspace_service::PublicWorkspaceTask>,
)> {
    let preferred_language = if body.is_empty() {
        None
    } else {
        let request: Value = serde_json::from_slice(&body).map_err(|_| {
            ObjectiveHttpError::response(StatusCode::UNPROCESSABLE_ENTITY, "Invalid JSON body")
        })?;
        if request.is_null() {
            None
        } else {
            let fields = request_object(&request)?;
            optional_enum(fields, "preferred_language", PREFERRED_LANGUAGES)?
        }
    };
    let context = objective_context(tenant_id, project_id, workspace_id, &headers)?;
    let outcome = service(&state)
        .project_to_task(
            &context,
            objective_id.as_str(),
            preferred_language.as_deref(),
        )
        .await
        .map_err(map_objective_error)?;
    let status = if outcome.existing {
        StatusCode::OK
    } else {
        StatusCode::CREATED
    };
    Ok((status, Json(outcome.task)))
}

fn service(state: &WorkspaceCoreState) -> PublicWorkspaceObjectiveService<'_> {
    PublicWorkspaceObjectiveService::new(state.db.as_ref(), state.sql_flavor)
}

fn objective_context(
    tenant_id: String,
    project_id: String,
    workspace_id: String,
    headers: &HeaderMap,
) -> ObjectiveResult<PublicWorkspaceObjectiveContext> {
    let caller = caller_from_headers(headers)?;
    Ok(PublicWorkspaceObjectiveContext {
        tenant_id,
        project_id,
        workspace_id,
        user_id: caller.user_id,
        is_superuser: caller.is_superuser,
        expected_revision: optional_header(headers, IF_MATCH_HEADER)?
            .map(|value| parse_if_match(value.as_str()))
            .transpose()?,
        idempotency_key: optional_header(headers, IDEMPOTENCY_HEADER)?,
    })
}

fn parse_if_match(value: &str) -> ObjectiveResult<u64> {
    let value = value.trim();
    let value = value.strip_prefix("W/").unwrap_or(value);
    let value = value
        .strip_prefix('"')
        .and_then(|value| value.strip_suffix('"'))
        .unwrap_or(value);
    value.parse::<u64>().map_err(|_| {
        ObjectiveHttpError::response(
            StatusCode::BAD_REQUEST,
            "If-Match must contain a non-negative Workspace revision",
        )
    })
}

fn request_object(request: &Value) -> ObjectiveResult<&Map<String, Value>> {
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

fn required_text(
    fields: &Map<String, Value>,
    field: &'static str,
    request: &Value,
    max_chars: usize,
) -> ObjectiveResult<String> {
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
    validate_text(field, value, max_chars)?;
    Ok(value.to_string())
}

fn optional_limited_text(
    fields: &Map<String, Value>,
    field: &'static str,
    max_chars: usize,
) -> ObjectiveResult<Option<String>> {
    let value = optional_text(fields, field)?;
    if let Some(value) = &value {
        validate_text(field, value, max_chars)?;
    }
    Ok(value)
}

fn optional_text(
    fields: &Map<String, Value>,
    field: &'static str,
) -> ObjectiveResult<Option<String>> {
    match fields.get(field) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::String(value)) => Ok(Some(value.clone())),
        Some(value) => Err(body_validation_error(
            "string_type",
            Some(field),
            "Input should be a valid string",
            value.clone(),
            None,
        )
        .into()),
    }
}

fn optional_enum(
    fields: &Map<String, Value>,
    field: &'static str,
    allowed: &[&str],
) -> ObjectiveResult<Option<String>> {
    let value = optional_text(fields, field)?;
    if value
        .as_ref()
        .is_some_and(|value| !allowed.contains(&value.as_str()))
    {
        return Err(body_validation_error(
            "enum",
            Some(field),
            "Input should be a valid enum value",
            fields.get(field).cloned().unwrap_or(Value::Null),
            None,
        )
        .into());
    }
    Ok(value)
}

fn optional_number(
    fields: &Map<String, Value>,
    field: &'static str,
) -> ObjectiveResult<Option<f64>> {
    match fields.get(field) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Number(value)) => {
            let value = value.as_f64().ok_or_else(|| {
                body_validation_error(
                    "float_type",
                    Some(field),
                    "Input should be a valid number",
                    Value::Number(value.clone()),
                    None,
                )
            })?;
            if !(0.0..=1.0).contains(&value) {
                return Err(body_validation_error(
                    "value_error",
                    Some(field),
                    "Input should be greater than or equal to 0 and less than or equal to 1",
                    Value::from(value),
                    None,
                )
                .into());
            }
            Ok(Some(value))
        }
        Some(value) => Err(body_validation_error(
            "float_type",
            Some(field),
            "Input should be a valid number",
            value.clone(),
            None,
        )
        .into()),
    }
}

fn validate_text(field: &'static str, value: &str, max_chars: usize) -> ObjectiveResult<()> {
    let chars = value.chars().count();
    if chars == 0 {
        return Err(body_validation_error(
            "string_too_short",
            Some(field),
            "String should have at least 1 character",
            Value::String(value.to_string()),
            Some(json!({"min_length": 1})),
        )
        .into());
    }
    if chars > max_chars {
        return Err(body_validation_error(
            "string_too_long",
            Some(field),
            format!("String should have at most {max_chars} characters").as_str(),
            Value::String(value.to_string()),
            Some(json!({"max_length": max_chars})),
        )
        .into());
    }
    Ok(())
}

fn query_integer(
    field: &'static str,
    raw: Option<&str>,
    default: i64,
    minimum: i64,
    maximum: i64,
) -> ObjectiveResult<i64> {
    let Some(raw) = raw else {
        return Ok(default);
    };
    let value = raw.parse::<i64>().map_err(|_| {
        query_validation_error(
            field,
            "Input should be a valid integer, unable to parse string as an integer",
        )
    })?;
    if !(minimum..=maximum).contains(&value) {
        return Err(query_validation_error(
            field,
            "Input should be within the allowed range",
        ));
    }
    Ok(value)
}

fn query_validation_error(field: &'static str, message: &str) -> ObjectiveHttpError {
    ApiError::Validation(json!([{
        "type": "value_error",
        "loc": ["query", field],
        "msg": message,
    }]))
    .into()
}

fn map_objective_error(error: PublicWorkspaceObjectiveError) -> ObjectiveHttpError {
    match error.kind() {
        PublicWorkspaceObjectiveErrorKind::InvalidRequest => ObjectiveHttpError::response(
            StatusCode::UNPROCESSABLE_ENTITY,
            "Invalid Objective request",
        ),
        PublicWorkspaceObjectiveErrorKind::NotFound => {
            ObjectiveHttpError::response(StatusCode::NOT_FOUND, "Objective not found")
        }
        PublicWorkspaceObjectiveErrorKind::Forbidden => {
            ObjectiveHttpError::response(StatusCode::FORBIDDEN, "Access denied")
        }
        PublicWorkspaceObjectiveErrorKind::Conflict => ObjectiveHttpError::response(
            StatusCode::CONFLICT,
            "Workspace Objective authority conflict",
        ),
        PublicWorkspaceObjectiveErrorKind::Unavailable => {
            ApiError::InvalidDatabase(error.to_string()).into()
        }
    }
}

type ObjectiveResult<T> = Result<T, ObjectiveHttpError>;

#[derive(Debug)]
enum ObjectiveHttpError {
    Core(ApiError),
    Response(StatusCode, String),
}

impl ObjectiveHttpError {
    fn response(status: StatusCode, detail: impl Into<String>) -> Self {
        Self::Response(status, detail.into())
    }
}

impl From<ApiError> for ObjectiveHttpError {
    fn from(error: ApiError) -> Self {
        Self::Core(error)
    }
}

impl IntoResponse for ObjectiveHttpError {
    fn into_response(self) -> Response {
        match self {
            Self::Core(error) => error.into_response(),
            Self::Response(status, detail) => {
                (status, Json(json!({"detail": detail}))).into_response()
            }
        }
    }
}
