//! HTTP boundary parsing and legacy error envelopes for Workspace Plan routes.

use axum::Json;
use axum::extract::rejection::JsonRejection;
use axum::http::{HeaderMap, StatusCode};
use axum::response::{IntoResponse, Response};
use memstack_workspace_service::{
    PublicWorkspacePlanActionInput, PublicWorkspacePlanContext, PublicWorkspacePlanError,
    PublicWorkspacePlanErrorKind,
};
use serde::Deserialize;
use serde_json::{Map, Value, json};

pub(super) const USER_HEADER: &str = "x-memstack-user-id";
pub(super) const SUPERUSER_HEADER: &str = "x-memstack-user-is-superuser";
pub(super) const WORKSPACE_HEADER: &str = "x-memstack-workspace-id";
pub(super) const EXPECTED_REVISION_HEADER: &str = "if-match";
pub(super) const IDEMPOTENCY_HEADER: &str = "idempotency-key";

use crate::workspace_scope::ResolvedWorkspaceScope;

#[derive(Debug, Deserialize)]
pub(super) struct RawSnapshotQuery {
    pub outbox_limit: Option<String>,
    pub event_limit: Option<String>,
    pub include_details: Option<String>,
    pub recover_stale_attempts: Option<String>,
    pub plan_id: Option<String>,
}

#[derive(Debug)]
pub(super) struct SnapshotQuery {
    pub outbox_limit: u64,
    pub event_limit: u64,
    pub include_details: bool,
    pub recover_stale_attempts: bool,
    pub plan_id: Option<String>,
}

#[derive(Debug)]
pub(super) struct ActionBody {
    pub reason: Option<String>,
    pub evidence_refs: Vec<String>,
    pub node_id: Option<String>,
}

#[derive(Debug)]
pub(super) struct PlanCaller {
    pub user_id: String,
    pub is_superuser: bool,
}

#[derive(Debug)]
pub(super) struct PlanHttpError {
    status: StatusCode,
    detail: Value,
}

impl PlanHttpError {
    pub(super) fn unauthorized() -> Self {
        Self::new(StatusCode::UNAUTHORIZED, "Unauthorized")
    }

    pub(super) fn validation(detail: Value) -> Self {
        Self {
            status: StatusCode::UNPROCESSABLE_ENTITY,
            detail,
        }
    }

    pub(super) fn not_found(detail: &str) -> Self {
        Self::new(StatusCode::NOT_FOUND, detail)
    }

    pub(super) fn forbidden(detail: &str) -> Self {
        Self::new(StatusCode::FORBIDDEN, detail)
    }

    pub(super) fn unavailable() -> Self {
        Self::new(
            StatusCode::SERVICE_UNAVAILABLE,
            "Workspace plan operation failed",
        )
    }

    fn new(status: StatusCode, detail: &str) -> Self {
        Self {
            status,
            detail: Value::String(detail.to_string()),
        }
    }
}

impl IntoResponse for PlanHttpError {
    fn into_response(self) -> Response {
        (self.status, Json(json!({"detail": self.detail}))).into_response()
    }
}

pub(super) fn map_service_error(error: PublicWorkspacePlanError) -> PlanHttpError {
    match error.kind() {
        PublicWorkspacePlanErrorKind::Validation => PlanHttpError::validation(json!([{
            "type": "value_error",
            "loc": ["body"],
            "msg": "Invalid workspace plan request",
            "input": null,
        }])),
        PublicWorkspacePlanErrorKind::NotFound => {
            PlanHttpError::new(StatusCode::NOT_FOUND, "Workspace plan not found")
        }
        PublicWorkspacePlanErrorKind::Forbidden => {
            PlanHttpError::new(StatusCode::FORBIDDEN, "Access denied")
        }
        PublicWorkspacePlanErrorKind::Conflict => PlanHttpError::new(
            StatusCode::CONFLICT,
            "Workspace plan revision or transition conflict",
        ),
        PublicWorkspacePlanErrorKind::Unavailable => PlanHttpError::new(
            StatusCode::SERVICE_UNAVAILABLE,
            "Workspace plan operation failed",
        ),
    }
}

pub(super) fn parse_snapshot_query(
    query: RawSnapshotQuery,
) -> Result<SnapshotQuery, PlanHttpError> {
    let outbox_limit =
        bounded_query_integer(query.outbox_limit.as_deref(), "outbox_limit", 20, 100)?;
    let event_limit = bounded_query_integer(query.event_limit.as_deref(), "event_limit", 50, 200)?;
    let include_details = query_boolean(query.include_details.as_deref(), "include_details", true)?;
    let recover_stale_attempts = query_boolean(
        query.recover_stale_attempts.as_deref(),
        "recover_stale_attempts",
        false,
    )?;
    if query
        .plan_id
        .as_ref()
        .is_some_and(|value| value.trim().is_empty())
    {
        return Err(query_error(
            "value_error",
            "plan_id",
            "Value error, value must not be blank",
            query.plan_id.as_deref().unwrap_or_default(),
            None,
        ));
    }
    Ok(SnapshotQuery {
        outbox_limit,
        event_limit,
        include_details,
        recover_stale_attempts,
        plan_id: query.plan_id,
    })
}

pub(super) fn plan_caller(headers: &HeaderMap) -> Result<PlanCaller, PlanHttpError> {
    let is_superuser = optional_header(headers, SUPERUSER_HEADER)?
        .map(|value| match value.as_str() {
            "true" => Ok(true),
            "false" => Ok(false),
            _ => Err(header_error(
                "bool_parsing",
                SUPERUSER_HEADER,
                "Input should be a valid boolean",
                &value,
            )),
        })
        .transpose()?
        .unwrap_or(false);
    Ok(PlanCaller {
        user_id: required_header(headers, USER_HEADER)?,
        is_superuser,
    })
}

pub(super) fn plan_context(
    headers: &HeaderMap,
    caller: PlanCaller,
    scope: ResolvedWorkspaceScope,
) -> Result<PublicWorkspacePlanContext, PlanHttpError> {
    if optional_header(headers, WORKSPACE_HEADER)?
        .is_some_and(|workspace_id| workspace_id != scope.workspace_id)
    {
        return Err(header_error(
            "value_error",
            WORKSPACE_HEADER,
            "Workspace header must match the route workspace",
            headers
                .get(WORKSPACE_HEADER)
                .and_then(|value| value.to_str().ok())
                .unwrap_or_default(),
        ));
    }
    Ok(PublicWorkspacePlanContext {
        tenant_id: scope.tenant_id,
        project_id: scope.project_id,
        workspace_id: scope.workspace_id,
        actor_id: caller.user_id,
        actor_is_superuser: caller.is_superuser,
    })
}

pub(super) fn expected_revision(headers: &HeaderMap) -> Result<Option<u64>, PlanHttpError> {
    optional_header(headers, EXPECTED_REVISION_HEADER)?
        .map(|value| {
            let value = value.trim();
            let value = value.strip_prefix("W/").unwrap_or(value);
            let value = value
                .strip_prefix('"')
                .and_then(|value| value.strip_suffix('"'))
                .unwrap_or(value);
            value.parse::<u64>().map_err(|_| {
                header_error(
                    "int_parsing",
                    EXPECTED_REVISION_HEADER,
                    "Input should be a valid integer",
                    value,
                )
            })
        })
        .transpose()
}

pub(super) fn idempotency_key(headers: &HeaderMap) -> Result<Option<String>, PlanHttpError> {
    let value = optional_header(headers, IDEMPOTENCY_HEADER)?;
    if value
        .as_ref()
        .is_some_and(|key| key.trim().is_empty() || key.chars().count() > 256)
    {
        return Err(header_error(
            "value_error",
            IDEMPOTENCY_HEADER,
            "Idempotency key must contain 1 to 256 characters",
            value.as_deref().unwrap_or_default(),
        ));
    }
    Ok(value)
}

pub(super) fn parse_action_body(
    request: Result<Json<Value>, JsonRejection>,
    allow_node_id: bool,
) -> Result<ActionBody, PlanHttpError> {
    let Json(value) = request.map_err(|error| {
        PlanHttpError::validation(json!([{
            "type": "json_invalid",
            "loc": ["body"],
            "msg": "JSON decode error",
            "input": {},
            "ctx": {"error": error.body_text()},
        }]))
    })?;
    let fields = value.as_object().ok_or_else(|| {
        body_error(
            "model_attributes_type",
            None,
            "Input should be a valid dictionary or object to extract fields from",
            value.clone(),
        )
    })?;
    let allowed_fields: &[&str] = if allow_node_id {
        &["reason", "evidence_refs", "node_id"]
    } else {
        &["reason", "evidence_refs"]
    };
    if let Some((field, input)) = fields
        .iter()
        .find(|(field, _)| !allowed_fields.contains(&field.as_str()))
    {
        return Err(body_error(
            "extra_forbidden",
            Some(field),
            "Extra inputs are not permitted",
            input.clone(),
        ));
    }
    let reason = optional_body_string(fields, "reason", 500)?;
    let evidence_refs = evidence_refs(fields)?;
    let node_id = if allow_node_id {
        optional_body_string(fields, "node_id", 128)?
    } else {
        None
    };
    Ok(ActionBody {
        reason,
        evidence_refs,
        node_id,
    })
}

pub(super) fn action_input(
    context: PublicWorkspacePlanContext,
    action: memstack_workspace_service::PublicWorkspacePlanAction,
    body: ActionBody,
    path_node_id: Option<String>,
    outbox_id: Option<String>,
    headers: &HeaderMap,
) -> Result<PublicWorkspacePlanActionInput, PlanHttpError> {
    Ok(PublicWorkspacePlanActionInput {
        context,
        action,
        node_id: path_node_id.or(body.node_id),
        outbox_id,
        reason: body.reason,
        evidence_refs: body.evidence_refs,
        idempotency_key: idempotency_key(headers)?,
        expected_revision: expected_revision(headers)?,
    })
}

pub(super) fn required_header(
    headers: &HeaderMap,
    name: &'static str,
) -> Result<String, PlanHttpError> {
    optional_header(headers, name)?
        .ok_or_else(|| header_error("missing", name, "Field required", ""))
}

pub(super) fn optional_header(
    headers: &HeaderMap,
    name: &'static str,
) -> Result<Option<String>, PlanHttpError> {
    headers
        .get(name)
        .map(|value| {
            value.to_str().map(str::to_string).map_err(|_| {
                header_error("string_unicode", name, "Input should be a valid string", "")
            })
        })
        .transpose()
}

fn optional_body_string(
    fields: &Map<String, Value>,
    field: &'static str,
    max_chars: usize,
) -> Result<Option<String>, PlanHttpError> {
    match fields.get(field) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::String(value)) if value.chars().count() <= max_chars => Ok(Some(value.clone())),
        Some(Value::String(value)) => Err(body_error(
            "string_too_long",
            Some(field),
            &format!("String should have at most {max_chars} characters"),
            Value::String(value.clone()),
        )),
        Some(value) => Err(body_error(
            "string_type",
            Some(field),
            "Input should be a valid string",
            value.clone(),
        )),
    }
}

fn evidence_refs(fields: &Map<String, Value>) -> Result<Vec<String>, PlanHttpError> {
    let Some(value) = fields.get("evidence_refs") else {
        return Ok(Vec::new());
    };
    let values = value.as_array().ok_or_else(|| {
        body_error(
            "list_type",
            Some("evidence_refs"),
            "Input should be a valid list",
            value.clone(),
        )
    })?;
    if values.len() > 20 {
        return Err(body_error(
            "too_long",
            Some("evidence_refs"),
            "List should have at most 20 items",
            value.clone(),
        ));
    }
    values
        .iter()
        .enumerate()
        .map(|(index, value)| {
            value.as_str().map(str::to_string).ok_or_else(|| {
                PlanHttpError::validation(json!([{
                    "type": "string_type",
                    "loc": ["body", "evidence_refs", index],
                    "msg": "Input should be a valid string",
                    "input": value,
                }]))
            })
        })
        .collect()
}

fn bounded_query_integer(
    raw: Option<&str>,
    field: &'static str,
    default: u64,
    max: u64,
) -> Result<u64, PlanHttpError> {
    let Some(raw) = raw else {
        return Ok(default);
    };
    let value = raw.parse::<u64>().map_err(|_| {
        query_error(
            "int_parsing",
            field,
            "Input should be a valid integer",
            raw,
            None,
        )
    })?;
    if value > max {
        return Err(query_error(
            "less_than_equal",
            field,
            &format!("Input should be less than or equal to {max}"),
            raw,
            Some(json!({"le": max})),
        ));
    }
    Ok(value)
}

fn query_boolean(
    raw: Option<&str>,
    field: &'static str,
    default: bool,
) -> Result<bool, PlanHttpError> {
    let Some(raw) = raw else {
        return Ok(default);
    };
    match raw.to_ascii_lowercase().as_str() {
        "true" | "1" => Ok(true),
        "false" | "0" => Ok(false),
        _ => Err(query_error(
            "bool_parsing",
            field,
            "Input should be a valid boolean",
            raw,
            None,
        )),
    }
}

fn body_error(
    error_type: &'static str,
    field: Option<&str>,
    message: &str,
    input: Value,
) -> PlanHttpError {
    let mut location = vec![Value::String("body".to_string())];
    if let Some(field) = field {
        location.push(Value::String(field.to_string()));
    }
    PlanHttpError::validation(json!([{
        "type": error_type, "loc": location, "msg": message, "input": input,
    }]))
}

fn query_error(
    error_type: &'static str,
    field: &'static str,
    message: &str,
    input: &str,
    context: Option<Value>,
) -> PlanHttpError {
    let mut detail = json!({
        "type": error_type, "loc": ["query", field], "msg": message, "input": input,
    });
    if let Some(context) = context {
        detail["ctx"] = context;
    }
    PlanHttpError::validation(json!([detail]))
}

fn header_error(
    error_type: &'static str,
    field: &'static str,
    message: &str,
    input: &str,
) -> PlanHttpError {
    PlanHttpError::validation(json!([{
        "type": error_type, "loc": ["header", field], "msg": message, "input": input,
    }]))
}
