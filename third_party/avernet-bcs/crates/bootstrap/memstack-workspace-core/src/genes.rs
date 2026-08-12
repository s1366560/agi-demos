//! Tenant-scoped legacy Gene HTTP handlers over the Avernet authority.

use std::sync::Arc;

use axum::extract::rejection::JsonRejection;
use axum::extract::{Path, Query};
use axum::http::{HeaderMap, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::get;
use axum::{Extension, Json, Router};
use memstack_workspace_service::{
    PublicCreateWorkspaceGeneInput, PublicUpdateWorkspaceGeneFields, PublicWorkspaceGene,
    PublicWorkspaceGeneContext, PublicWorkspaceGeneError, PublicWorkspaceGeneErrorKind,
    PublicWorkspaceGeneService,
};
use serde::Deserialize;
use serde_json::{Map, Value, json};

use super::creation::{body_validation_error, map_public_json_rejection, optional_header};
use super::public_api::caller_from_headers;
use super::{ApiError, WorkspaceCoreState};

const IDEMPOTENCY_HEADER: &str = "idempotency-key";
const IF_MATCH_HEADER: &str = "if-match";
const CATEGORIES: &[&str] = &["skill", "knowledge", "tool", "workflow"];

#[derive(Debug, Deserialize)]
struct GeneListQuery {
    category: Option<String>,
    is_active: Option<String>,
    limit: Option<String>,
    offset: Option<String>,
}

pub(super) fn router() -> Router {
    Router::new()
        .route(
            "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/genes",
            get(list_genes).post(create_gene),
        )
        .route(
            "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/genes/{gene_id}",
            get(get_gene).patch(update_gene).delete(delete_gene),
        )
}

async fn create_gene(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
    headers: HeaderMap,
    request: Result<Json<Value>, JsonRejection>,
) -> GeneResult<(StatusCode, Json<PublicWorkspaceGene>)> {
    let Json(request) = request.map_err(map_public_json_rejection)?;
    let fields = request_object(&request)?;
    let context = gene_context(tenant_id, project_id, workspace_id, &headers)?;
    let input = PublicCreateWorkspaceGeneInput {
        context,
        name: required_text(fields, "name", &request, 200)?,
        category: optional_enum(fields, "category", CATEGORIES)?
            .unwrap_or_else(|| "skill".to_string()),
        description: optional_text(fields, "description", None)?,
        config_json: optional_config(fields)?,
        version: optional_text(fields, "version", None)?.unwrap_or_else(|| "1.0.0".to_string()),
        is_active: optional_bool(fields, "is_active")?.unwrap_or(true),
    };
    let outcome = service(&state)
        .create(&input)
        .await
        .map_err(map_gene_error)?;
    Ok((StatusCode::CREATED, Json(outcome.gene)))
}

async fn list_genes(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
    Query(query): Query<GeneListQuery>,
    headers: HeaderMap,
) -> GeneResult<Json<Value>> {
    if let Some(category) = query.category.as_deref()
        && !CATEGORIES.contains(&category)
    {
        return Err(query_validation_error(
            "enum",
            "category",
            "Input should be a valid enum value",
            category,
        ));
    }
    let is_active = query
        .is_active
        .as_deref()
        .map(|value| query_bool("is_active", value))
        .transpose()?;
    let limit = query_integer("limit", query.limit.as_deref(), 100, 1, 500)?;
    let offset = query_integer("offset", query.offset.as_deref(), 0, 0, i64::MAX)?;
    let context = gene_context(tenant_id, project_id, workspace_id, &headers)?;
    let items = service(&state)
        .list(
            &context,
            query.category.as_deref(),
            is_active,
            limit,
            offset,
        )
        .await
        .map_err(map_gene_error)?;
    let total = items.len();
    Ok(Json(json!({"items": items, "total": total})))
}

async fn get_gene(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id, gene_id)): Path<(String, String, String, String)>,
    headers: HeaderMap,
) -> GeneResult<Json<PublicWorkspaceGene>> {
    let context = gene_context(tenant_id, project_id, workspace_id, &headers)?;
    service(&state)
        .get(&context, gene_id.as_str())
        .await
        .map(Json)
        .map_err(map_gene_error)
}

async fn update_gene(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id, gene_id)): Path<(String, String, String, String)>,
    headers: HeaderMap,
    request: Result<Json<Value>, JsonRejection>,
) -> GeneResult<Json<PublicWorkspaceGene>> {
    let Json(request) = request.map_err(map_public_json_rejection)?;
    let fields = request_object(&request)?;
    let context = gene_context(tenant_id, project_id, workspace_id, &headers)?;
    let update = PublicUpdateWorkspaceGeneFields {
        name: optional_limited_text(fields, "name", 200)?,
        category: optional_enum(fields, "category", CATEGORIES)?,
        description: optional_text(fields, "description", None)?,
        config_json: optional_config(fields)?,
        version: optional_text(fields, "version", None)?,
        is_active: optional_bool(fields, "is_active")?,
    };
    let outcome = service(&state)
        .update(&context, gene_id.as_str(), &update)
        .await
        .map_err(map_gene_error)?;
    Ok(Json(outcome.gene))
}

async fn delete_gene(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id, gene_id)): Path<(String, String, String, String)>,
    headers: HeaderMap,
) -> GeneResult<StatusCode> {
    let context = gene_context(tenant_id, project_id, workspace_id, &headers)?;
    service(&state)
        .delete(&context, gene_id.as_str())
        .await
        .map_err(map_gene_error)?;
    Ok(StatusCode::NO_CONTENT)
}

fn service(state: &WorkspaceCoreState) -> PublicWorkspaceGeneService<'_> {
    PublicWorkspaceGeneService::new(state.db.as_ref(), state.sql_flavor)
}

fn gene_context(
    tenant_id: String,
    project_id: String,
    workspace_id: String,
    headers: &HeaderMap,
) -> GeneResult<PublicWorkspaceGeneContext> {
    let caller = caller_from_headers(headers)?;
    Ok(PublicWorkspaceGeneContext {
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

fn parse_if_match(value: &str) -> GeneResult<u64> {
    let value = value.trim();
    let value = value.strip_prefix("W/").unwrap_or(value);
    let value = value
        .strip_prefix('"')
        .and_then(|value| value.strip_suffix('"'))
        .unwrap_or(value);
    value.parse::<u64>().map_err(|_| {
        GeneHttpError::response(
            StatusCode::BAD_REQUEST,
            "If-Match must contain a non-negative Workspace revision",
        )
    })
}

fn request_object(request: &Value) -> GeneResult<&Map<String, Value>> {
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
) -> GeneResult<String> {
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
    validate_text(field, value, Some(max_chars))?;
    Ok(value.to_string())
}

fn optional_limited_text(
    fields: &Map<String, Value>,
    field: &'static str,
    max_chars: usize,
) -> GeneResult<Option<String>> {
    let value = optional_text(fields, field, Some(max_chars))?;
    if let Some(value) = &value {
        validate_text(field, value, Some(max_chars))?;
    }
    Ok(value)
}

fn optional_text(
    fields: &Map<String, Value>,
    field: &'static str,
    max_chars: Option<usize>,
) -> GeneResult<Option<String>> {
    match fields.get(field) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::String(value)) => {
            if let Some(max_chars) = max_chars
                && value.chars().count() > max_chars
            {
                validate_text(field, value, Some(max_chars))?;
            }
            Ok(Some(value.clone()))
        }
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

fn validate_text(field: &'static str, value: &str, max_chars: Option<usize>) -> GeneResult<()> {
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
    if let Some(max_chars) = max_chars
        && chars > max_chars
    {
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

fn optional_enum(
    fields: &Map<String, Value>,
    field: &'static str,
    allowed: &[&str],
) -> GeneResult<Option<String>> {
    let value = optional_text(fields, field, None)?;
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

fn optional_bool(fields: &Map<String, Value>, field: &'static str) -> GeneResult<Option<bool>> {
    match fields.get(field) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Bool(value)) => Ok(Some(*value)),
        Some(value) => Err(body_validation_error(
            "bool_type",
            Some(field),
            "Input should be a valid boolean",
            value.clone(),
            None,
        )
        .into()),
    }
}

fn optional_config(fields: &Map<String, Value>) -> GeneResult<Option<String>> {
    let config = optional_text(fields, "config_json", None)?;
    let Some(config) = config else {
        return Ok(None);
    };
    if config.is_empty() {
        return Ok(Some(config));
    }
    let parsed: Value = serde_json::from_str(config.as_str()).map_err(|_| {
        GeneHttpError::response(
            StatusCode::UNPROCESSABLE_ENTITY,
            "config_json is not valid JSON",
        )
    })?;
    if !parsed.is_object() {
        return Err(GeneHttpError::response(
            StatusCode::UNPROCESSABLE_ENTITY,
            "config_json must be a JSON object",
        ));
    }
    Ok(Some(config))
}

fn query_integer(
    field: &'static str,
    raw: Option<&str>,
    default: i64,
    minimum: i64,
    maximum: i64,
) -> GeneResult<i64> {
    let Some(raw) = raw else {
        return Ok(default);
    };
    let value = raw.parse::<i64>().map_err(|_| {
        query_validation_error(
            "int_parsing",
            field,
            "Input should be a valid integer, unable to parse string as an integer",
            raw,
        )
    })?;
    if !(minimum..=maximum).contains(&value) {
        return Err(query_validation_error(
            "value_error",
            field,
            "Input should be within the allowed range",
            raw,
        ));
    }
    Ok(value)
}

fn query_bool(field: &'static str, raw: &str) -> GeneResult<bool> {
    match raw {
        "true" | "1" | "on" | "yes" => Ok(true),
        "false" | "0" | "off" | "no" => Ok(false),
        _ => Err(query_validation_error(
            "bool_parsing",
            field,
            "Input should be a valid boolean",
            raw,
        )),
    }
}

fn query_validation_error(
    error_type: &'static str,
    field: &'static str,
    message: &str,
    input: &str,
) -> GeneHttpError {
    ApiError::Validation(json!([{
        "type": error_type,
        "loc": ["query", field],
        "msg": message,
        "input": input,
    }]))
    .into()
}

fn map_gene_error(error: PublicWorkspaceGeneError) -> GeneHttpError {
    match error.kind() {
        PublicWorkspaceGeneErrorKind::InvalidRequest => {
            GeneHttpError::response(StatusCode::UNPROCESSABLE_ENTITY, "Invalid Gene request")
        }
        PublicWorkspaceGeneErrorKind::NotFound => {
            GeneHttpError::response(StatusCode::NOT_FOUND, "Gene not found")
        }
        PublicWorkspaceGeneErrorKind::Forbidden => {
            GeneHttpError::response(StatusCode::FORBIDDEN, "Access denied")
        }
        PublicWorkspaceGeneErrorKind::Conflict => {
            GeneHttpError::response(StatusCode::CONFLICT, "Workspace Gene authority conflict")
        }
        PublicWorkspaceGeneErrorKind::Unavailable => {
            ApiError::InvalidDatabase(error.to_string()).into()
        }
    }
}

type GeneResult<T> = Result<T, GeneHttpError>;

#[derive(Debug)]
enum GeneHttpError {
    Core(ApiError),
    Response(StatusCode, String),
}

impl GeneHttpError {
    fn response(status: StatusCode, detail: impl Into<String>) -> Self {
        Self::Response(status, detail.into())
    }
}

impl From<ApiError> for GeneHttpError {
    fn from(error: ApiError) -> Self {
        Self::Core(error)
    }
}

impl IntoResponse for GeneHttpError {
    fn into_response(self) -> Response {
        match self {
            Self::Core(error) => error.into_response(),
            Self::Response(status, detail) => {
                (status, Json(json!({"detail": detail}))).into_response()
            }
        }
    }
}
