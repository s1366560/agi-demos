//! Tenant-scoped legacy Blackboard HTTP handlers over the Avernet authority.

use std::sync::Arc;

use axum::extract::rejection::JsonRejection;
use axum::extract::{Path, Query};
use axum::http::{HeaderMap, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Extension, Json, Router};
use memstack_workspace_service::{
    PublicCreateBlackboardPostInput, PublicCreateBlackboardReplyInput,
    PublicUpdateBlackboardPostFields, PublicUpdateBlackboardReplyInput,
    PublicWorkspaceBlackboardContext, PublicWorkspaceBlackboardError,
    PublicWorkspaceBlackboardErrorKind, PublicWorkspaceBlackboardPost,
    PublicWorkspaceBlackboardReply, PublicWorkspaceBlackboardService,
};
use serde::Deserialize;
use serde_json::{Map, Value, json};

use super::creation::{body_validation_error, map_public_json_rejection, optional_header};
use super::public_api::caller_from_headers;
use super::{ApiError, WorkspaceCoreState};

const IDEMPOTENCY_HEADER: &str = "idempotency-key";
const IF_MATCH_HEADER: &str = "if-match";
const MAX_TITLE_CHARS: usize = 255;
const BLACKBOARD_STATUSES: &[&str] = &["open", "archived"];

#[derive(Debug, Deserialize)]
struct PageQuery {
    limit: Option<String>,
    offset: Option<String>,
}

pub(super) fn router() -> Router {
    Router::new()
        .route(
            "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/posts",
            get(list_posts).post(create_post),
        )
        .route(
            "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/posts/{post_id}",
            get(get_post).patch(update_post).delete(delete_post),
        )
        .route(
            "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/posts/{post_id}/pin",
            post(pin_post),
        )
        .route(
            "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/posts/{post_id}/unpin",
            post(unpin_post),
        )
        .route(
            "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/posts/{post_id}/replies",
            get(list_replies).post(create_reply),
        )
        .route(
            "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/posts/{post_id}/replies/{reply_id}",
            axum::routing::patch(update_reply).delete(delete_reply),
        )
}

async fn create_post(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
    headers: HeaderMap,
    request: Result<Json<Value>, JsonRejection>,
) -> BlackboardResult<(StatusCode, Json<PublicWorkspaceBlackboardPost>)> {
    let Json(request) = request.map_err(map_public_json_rejection)?;
    let context = blackboard_context(tenant_id, project_id, workspace_id, &headers)?;
    let fields = request_object(&request)?;
    let input = PublicCreateBlackboardPostInput {
        context,
        title: required_text(fields, "title", &request, Some(MAX_TITLE_CHARS))?,
        content: required_text(fields, "content", &request, None)?,
        status: optional_enum(fields, "status", BLACKBOARD_STATUSES)?
            .unwrap_or_else(|| "open".to_string()),
        is_pinned: optional_bool(fields, "is_pinned")?.unwrap_or(false),
        metadata: optional_object(fields, "metadata")?.unwrap_or_else(|| json!({})),
    };
    let outcome = service(&state)
        .create_post(&input)
        .await
        .map_err(map_blackboard_error)?;
    Ok((StatusCode::CREATED, Json(outcome.post)))
}

async fn list_posts(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
    Query(query): Query<PageQuery>,
    headers: HeaderMap,
) -> BlackboardResult<Json<Value>> {
    let context = blackboard_context(tenant_id, project_id, workspace_id, &headers)?;
    let limit = query_integer("limit", query.limit.as_deref(), 50, 1, 200)?;
    let offset = query_integer("offset", query.offset.as_deref(), 0, 0, i64::MAX)?;
    let items = service(&state)
        .list_posts(&context, limit, offset)
        .await
        .map_err(map_blackboard_error)?;
    Ok(Json(json!({"items": items})))
}

async fn get_post(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id, post_id)): Path<(String, String, String, String)>,
    headers: HeaderMap,
) -> BlackboardResult<Json<PublicWorkspaceBlackboardPost>> {
    let context = blackboard_context(tenant_id, project_id, workspace_id, &headers)?;
    let post = service(&state)
        .get_post(&context, post_id.as_str())
        .await
        .map_err(map_blackboard_error)?;
    Ok(Json(post))
}

async fn update_post(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id, post_id)): Path<(String, String, String, String)>,
    headers: HeaderMap,
    request: Result<Json<Value>, JsonRejection>,
) -> BlackboardResult<Json<PublicWorkspaceBlackboardPost>> {
    let Json(request) = request.map_err(map_public_json_rejection)?;
    let context = blackboard_context(tenant_id, project_id, workspace_id, &headers)?;
    let fields = request_object(&request)?;
    let update = PublicUpdateBlackboardPostFields {
        title: optional_text(fields, "title", Some(MAX_TITLE_CHARS))?,
        content: optional_text(fields, "content", None)?,
        status: optional_enum(fields, "status", BLACKBOARD_STATUSES)?,
        is_pinned: optional_bool(fields, "is_pinned")?,
        metadata: optional_object(fields, "metadata")?,
    };
    let outcome = service(&state)
        .update_post(&context, post_id.as_str(), &update)
        .await
        .map_err(map_blackboard_error)?;
    Ok(Json(outcome.post))
}

async fn delete_post(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id, post_id)): Path<(String, String, String, String)>,
    headers: HeaderMap,
) -> BlackboardResult<Json<Value>> {
    let context = blackboard_context(tenant_id, project_id, workspace_id, &headers)?;
    service(&state)
        .delete_post(&context, post_id.as_str())
        .await
        .map(Json)
        .map_err(map_blackboard_error)
}

async fn pin_post(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id, post_id)): Path<(String, String, String, String)>,
    headers: HeaderMap,
) -> BlackboardResult<Json<PublicWorkspaceBlackboardPost>> {
    set_pinned(
        &state,
        tenant_id,
        project_id,
        workspace_id,
        post_id,
        &headers,
        true,
    )
    .await
}

async fn unpin_post(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id, post_id)): Path<(String, String, String, String)>,
    headers: HeaderMap,
) -> BlackboardResult<Json<PublicWorkspaceBlackboardPost>> {
    set_pinned(
        &state,
        tenant_id,
        project_id,
        workspace_id,
        post_id,
        &headers,
        false,
    )
    .await
}

#[allow(clippy::too_many_arguments)]
async fn set_pinned(
    state: &WorkspaceCoreState,
    tenant_id: String,
    project_id: String,
    workspace_id: String,
    post_id: String,
    headers: &HeaderMap,
    is_pinned: bool,
) -> BlackboardResult<Json<PublicWorkspaceBlackboardPost>> {
    let context = blackboard_context(tenant_id, project_id, workspace_id, headers)?;
    let outcome = service(state)
        .set_post_pinned(&context, post_id.as_str(), is_pinned)
        .await
        .map_err(map_blackboard_error)?;
    Ok(Json(outcome.post))
}

async fn create_reply(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id, post_id)): Path<(String, String, String, String)>,
    headers: HeaderMap,
    request: Result<Json<Value>, JsonRejection>,
) -> BlackboardResult<(StatusCode, Json<PublicWorkspaceBlackboardReply>)> {
    let Json(request) = request.map_err(map_public_json_rejection)?;
    let context = blackboard_context(tenant_id, project_id, workspace_id, &headers)?;
    let fields = request_object(&request)?;
    let input = PublicCreateBlackboardReplyInput {
        context,
        content: required_text(fields, "content", &request, None)?,
        metadata: optional_object(fields, "metadata")?.unwrap_or_else(|| json!({})),
    };
    let outcome = service(&state)
        .create_reply(post_id.as_str(), &input)
        .await
        .map_err(map_blackboard_error)?;
    Ok((StatusCode::CREATED, Json(outcome.reply)))
}

async fn list_replies(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id, post_id)): Path<(String, String, String, String)>,
    Query(query): Query<PageQuery>,
    headers: HeaderMap,
) -> BlackboardResult<Json<Value>> {
    let context = blackboard_context(tenant_id, project_id, workspace_id, &headers)?;
    let limit = query_integer("limit", query.limit.as_deref(), 200, 1, 500)?;
    let offset = query_integer("offset", query.offset.as_deref(), 0, 0, i64::MAX)?;
    let items = service(&state)
        .list_replies(&context, post_id.as_str(), limit, offset)
        .await
        .map_err(map_blackboard_error)?;
    Ok(Json(json!({"items": items})))
}

async fn update_reply(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id, post_id, reply_id)): Path<(
        String,
        String,
        String,
        String,
        String,
    )>,
    headers: HeaderMap,
    request: Result<Json<Value>, JsonRejection>,
) -> BlackboardResult<Json<PublicWorkspaceBlackboardReply>> {
    let Json(request) = request.map_err(map_public_json_rejection)?;
    let context = blackboard_context(tenant_id, project_id, workspace_id, &headers)?;
    let fields = request_object(&request)?;
    let input = PublicUpdateBlackboardReplyInput {
        content: required_text(fields, "content", &request, None)?,
        metadata: optional_object(fields, "metadata")?,
    };
    let outcome = service(&state)
        .update_reply(&context, post_id.as_str(), reply_id.as_str(), &input)
        .await
        .map_err(map_blackboard_error)?;
    Ok(Json(outcome.reply))
}

async fn delete_reply(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id, post_id, reply_id)): Path<(
        String,
        String,
        String,
        String,
        String,
    )>,
    headers: HeaderMap,
) -> BlackboardResult<Json<Value>> {
    let context = blackboard_context(tenant_id, project_id, workspace_id, &headers)?;
    service(&state)
        .delete_reply(&context, post_id.as_str(), reply_id.as_str())
        .await
        .map(Json)
        .map_err(map_blackboard_error)
}

fn service(state: &WorkspaceCoreState) -> PublicWorkspaceBlackboardService<'_> {
    PublicWorkspaceBlackboardService::new(state.db.as_ref(), state.sql_flavor)
}

fn blackboard_context(
    tenant_id: String,
    project_id: String,
    workspace_id: String,
    headers: &HeaderMap,
) -> BlackboardResult<PublicWorkspaceBlackboardContext> {
    let caller = caller_from_headers(headers)?;
    Ok(PublicWorkspaceBlackboardContext {
        tenant_id,
        project_id,
        workspace_id,
        user_id: caller.user_id,
        expected_revision: optional_header(headers, IF_MATCH_HEADER)?
            .map(|value| parse_if_match(value.as_str()))
            .transpose()?,
        idempotency_key: optional_header(headers, IDEMPOTENCY_HEADER)?,
    })
}

fn parse_if_match(value: &str) -> BlackboardResult<u64> {
    let value = value.trim();
    let value = value.strip_prefix("W/").unwrap_or(value);
    let value = value
        .strip_prefix('"')
        .and_then(|value| value.strip_suffix('"'))
        .unwrap_or(value);
    value.parse::<u64>().map_err(|_| {
        BlackboardHttpError::response(
            StatusCode::BAD_REQUEST,
            "If-Match must contain a non-negative Workspace revision",
        )
    })
}

fn request_object(request: &Value) -> BlackboardResult<&Map<String, Value>> {
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
    max_chars: Option<usize>,
) -> BlackboardResult<String> {
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

fn optional_text(
    fields: &Map<String, Value>,
    field: &'static str,
    max_chars: Option<usize>,
) -> BlackboardResult<Option<String>> {
    match fields.get(field) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::String(value)) => {
            validate_text(field, value, max_chars)?;
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

fn validate_text(
    field: &'static str,
    value: &str,
    max_chars: Option<usize>,
) -> BlackboardResult<()> {
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
) -> BlackboardResult<Option<String>> {
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

fn optional_bool(
    fields: &Map<String, Value>,
    field: &'static str,
) -> BlackboardResult<Option<bool>> {
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

fn optional_object(
    fields: &Map<String, Value>,
    field: &'static str,
) -> BlackboardResult<Option<Value>> {
    match fields.get(field) {
        None | Some(Value::Null) => Ok(None),
        Some(value @ Value::Object(_)) => Ok(Some(value.clone())),
        Some(value) => Err(body_validation_error(
            "dict_type",
            Some(field),
            "Input should be a valid dictionary",
            value.clone(),
            None,
        )
        .into()),
    }
}

fn query_integer(
    field: &'static str,
    raw: Option<&str>,
    default: i64,
    minimum: i64,
    maximum: i64,
) -> BlackboardResult<i64> {
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
) -> BlackboardHttpError {
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

fn map_blackboard_error(error: PublicWorkspaceBlackboardError) -> BlackboardHttpError {
    match error.kind() {
        PublicWorkspaceBlackboardErrorKind::InvalidRequest => {
            BlackboardHttpError::response(StatusCode::BAD_REQUEST, "Invalid blackboard request")
        }
        PublicWorkspaceBlackboardErrorKind::NotFound => {
            BlackboardHttpError::response(StatusCode::NOT_FOUND, "Blackboard item not found")
        }
        PublicWorkspaceBlackboardErrorKind::Forbidden => {
            BlackboardHttpError::response(StatusCode::FORBIDDEN, "Access denied")
        }
        PublicWorkspaceBlackboardErrorKind::Conflict => BlackboardHttpError::response(
            StatusCode::CONFLICT,
            "Workspace blackboard authority conflict",
        ),
        PublicWorkspaceBlackboardErrorKind::Unavailable => {
            ApiError::InvalidDatabase(error.to_string()).into()
        }
    }
}

type BlackboardResult<T> = Result<T, BlackboardHttpError>;

#[derive(Debug)]
enum BlackboardHttpError {
    Core(ApiError),
    Response(StatusCode, String),
}

impl BlackboardHttpError {
    fn response(status: StatusCode, detail: impl Into<String>) -> Self {
        Self::Response(status, detail.into())
    }
}

impl From<ApiError> for BlackboardHttpError {
    fn from(error: ApiError) -> Self {
        Self::Core(error)
    }
}

impl IntoResponse for BlackboardHttpError {
    fn into_response(self) -> Response {
        match self {
            Self::Core(error) => error.into_response(),
            Self::Response(status, detail) => {
                (status, Json(json!({"detail": detail}))).into_response()
            }
        }
    }
}
