//! Legacy-compatible public Workspace message handlers.

use std::sync::Arc;

use axum::extract::rejection::JsonRejection;
use axum::extract::{Path, Query};
use axum::http::{HeaderMap, StatusCode};
use axum::{Extension, Json};
use memstack_workspace_service::{
    PublicSendWorkspaceMessageInput, PublicWorkspaceMessage, PublicWorkspaceMessageContext,
    PublicWorkspaceMessageError, PublicWorkspaceMessageErrorKind, PublicWorkspaceMessageService,
};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value, json};

use super::creation::{body_validation_error, map_public_json_rejection, optional_header};
use super::public_api::caller_from_headers;
use super::{ApiError, WorkspaceCoreState};

const IDEMPOTENCY_HEADER: &str = "idempotency-key";
const USER_EMAIL_HEADER: &str = "x-memstack-user-email";

#[derive(Debug, Deserialize)]
pub(super) struct MessageListQuery {
    limit: Option<String>,
    before: Option<String>,
}

#[derive(Debug, Deserialize)]
pub(super) struct MentionListQuery {
    limit: Option<String>,
}

#[derive(Debug, Serialize)]
pub(super) struct MessageListResponse {
    items: Vec<PublicWorkspaceMessage>,
}

pub(super) async fn send_workspace_message(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
    headers: HeaderMap,
    request: Result<Json<Value>, JsonRejection>,
) -> Result<(StatusCode, Json<PublicWorkspaceMessage>), ApiError> {
    let Json(request) = request.map_err(map_public_json_rejection)?;
    let caller = caller_from_headers(&headers)?;
    let parsed = parse_send_request(request)?;
    let input = PublicSendWorkspaceMessageInput {
        context: message_context(
            tenant_id,
            project_id,
            workspace_id,
            caller.user_id,
            caller.is_superuser,
            &headers,
        )?,
        content: parsed.content,
        sender_type: parsed.sender_type,
        parent_message_id: parsed.parent_message_id,
        mentions: parsed.mentions,
        idempotency_key: optional_header(&headers, IDEMPOTENCY_HEADER)?,
    };
    let outcome = PublicWorkspaceMessageService::new(state.db.as_ref(), state.sql_flavor)
        .send(&input)
        .await
        .map_err(map_message_error)?;
    let status = if outcome.replayed {
        StatusCode::OK
    } else {
        StatusCode::CREATED
    };
    Ok((status, Json(outcome.message)))
}

pub(super) async fn list_workspace_messages(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
    Query(query): Query<MessageListQuery>,
    headers: HeaderMap,
) -> Result<Json<MessageListResponse>, ApiError> {
    let caller = caller_from_headers(&headers)?;
    let context = message_context(
        tenant_id,
        project_id,
        workspace_id,
        caller.user_id,
        caller.is_superuser,
        &headers,
    )?;
    let messages = PublicWorkspaceMessageService::new(state.db.as_ref(), state.sql_flavor)
        .list(
            &context,
            query_limit(query.limit.as_deref())?,
            query.before.as_deref(),
        )
        .await
        .map_err(map_message_error)?;
    Ok(Json(MessageListResponse { items: messages }))
}

pub(super) async fn list_workspace_mentions(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id, target_id)): Path<(String, String, String, String)>,
    Query(query): Query<MentionListQuery>,
    headers: HeaderMap,
) -> Result<Json<MessageListResponse>, ApiError> {
    let caller = caller_from_headers(&headers)?;
    let context = message_context(
        tenant_id,
        project_id,
        workspace_id,
        caller.user_id,
        caller.is_superuser,
        &headers,
    )?;
    let messages = PublicWorkspaceMessageService::new(state.db.as_ref(), state.sql_flavor)
        .mentions(
            &context,
            target_id.as_str(),
            query_limit(query.limit.as_deref())?,
        )
        .await
        .map_err(map_message_error)?;
    Ok(Json(MessageListResponse { items: messages }))
}

struct ParsedSendRequest {
    content: String,
    sender_type: String,
    parent_message_id: Option<String>,
    mentions: Vec<String>,
}

fn parse_send_request(request: Value) -> Result<ParsedSendRequest, ApiError> {
    let fields = request.as_object().ok_or_else(|| {
        body_validation_error(
            "model_attributes_type",
            None,
            "Input should be a valid dictionary or object to extract fields from",
            request.clone(),
            None,
        )
    })?;
    let content = required_content(fields, &request)?;
    let sender_type = optional_string(fields, "sender_type")?.unwrap_or_else(|| "human".into());
    let parent_message_id = optional_string(fields, "parent_message_id")?;
    let mentions = structured_mentions(fields)?;
    Ok(ParsedSendRequest {
        content,
        sender_type,
        parent_message_id,
        mentions,
    })
}

fn required_content(fields: &Map<String, Value>, request: &Value) -> Result<String, ApiError> {
    let value = fields.get("content").ok_or_else(|| {
        body_validation_error(
            "missing",
            Some("content"),
            "Field required",
            request.clone(),
            None,
        )
    })?;
    let content = value.as_str().ok_or_else(|| {
        body_validation_error(
            "string_type",
            Some("content"),
            "Input should be a valid string",
            value.clone(),
            None,
        )
    })?;
    if content.is_empty() {
        return Err(body_validation_error(
            "string_too_short",
            Some("content"),
            "String should have at least 1 character",
            value.clone(),
            Some(json!({"min_length": 1})),
        ));
    }
    Ok(content.to_string())
}

fn optional_string(
    fields: &Map<String, Value>,
    field: &'static str,
) -> Result<Option<String>, ApiError> {
    match fields.get(field) {
        None => Ok(None),
        Some(Value::Null) if field == "parent_message_id" => Ok(None),
        Some(Value::String(value)) => Ok(Some(value.clone())),
        Some(value) => Err(body_validation_error(
            "string_type",
            Some(field),
            "Input should be a valid string",
            value.clone(),
            None,
        )),
    }
}

fn structured_mentions(fields: &Map<String, Value>) -> Result<Vec<String>, ApiError> {
    let Some(value) = fields.get("mentions") else {
        return Ok(Vec::new());
    };
    let values = value.as_array().ok_or_else(|| {
        body_validation_error(
            "list_type",
            Some("mentions"),
            "Input should be a valid list",
            value.clone(),
            None,
        )
    })?;
    values
        .iter()
        .enumerate()
        .map(|(index, value)| {
            value.as_str().map(str::to_string).ok_or_else(|| {
                indexed_body_validation_error(
                    "string_type",
                    "mentions",
                    index,
                    "Input should be a valid string",
                    value.clone(),
                )
            })
        })
        .collect()
}

fn indexed_body_validation_error(
    error_type: &'static str,
    field: &'static str,
    index: usize,
    message: &str,
    input: Value,
) -> ApiError {
    ApiError::Validation(json!([{
        "type": error_type,
        "loc": ["body", field, index],
        "msg": message,
        "input": input,
    }]))
}

fn message_context(
    tenant_id: String,
    project_id: String,
    workspace_id: String,
    user_id: String,
    user_is_superuser: bool,
    headers: &HeaderMap,
) -> Result<PublicWorkspaceMessageContext, ApiError> {
    Ok(PublicWorkspaceMessageContext {
        tenant_id,
        project_id,
        workspace_id,
        user_id,
        user_is_superuser,
        authenticated_email: optional_header(headers, USER_EMAIL_HEADER)?,
    })
}

fn query_limit(raw: Option<&str>) -> Result<i64, ApiError> {
    let Some(raw) = raw else {
        return Ok(50);
    };
    let value = parse_pydantic_integer(raw).ok_or_else(|| {
        query_validation_error(
            "int_parsing",
            "Input should be a valid integer, unable to parse string as an integer",
            raw,
            None,
        )
    })?;
    if value < 1 {
        return Err(query_validation_error(
            "greater_than_equal",
            "Input should be greater than or equal to 1",
            raw,
            Some(json!({"ge": 1})),
        ));
    }
    if value > 200 {
        return Err(query_validation_error(
            "less_than_equal",
            "Input should be less than or equal to 200",
            raw,
            Some(json!({"le": 200})),
        ));
    }
    Ok(value)
}

fn parse_pydantic_integer(raw: &str) -> Option<i64> {
    let normalized = raw.trim();
    if let Ok(value) = normalized.parse::<i64>() {
        return Some(value);
    }
    let (integer, fraction) = normalized.split_once('.')?;
    if integer.is_empty() || fraction.is_empty() || !fraction.bytes().all(|byte| byte == b'0') {
        return None;
    }
    integer.parse::<i64>().ok()
}

fn query_validation_error(
    error_type: &'static str,
    message: &str,
    input: &str,
    context: Option<Value>,
) -> ApiError {
    let mut detail = json!({
        "type": error_type,
        "loc": ["query", "limit"],
        "msg": message,
        "input": input,
    });
    if let Some(context) = context {
        detail["ctx"] = context;
    }
    ApiError::Validation(json!([detail]))
}

fn map_message_error(error: PublicWorkspaceMessageError) -> ApiError {
    match error.kind() {
        PublicWorkspaceMessageErrorKind::InvalidRequest => {
            ApiError::InvalidRequest("Invalid workspace chat request".to_string())
        }
        PublicWorkspaceMessageErrorKind::NotFound => ApiError::NotFound,
        PublicWorkspaceMessageErrorKind::AccessRequired => {
            ApiError::Forbidden("Workspace access required")
        }
        PublicWorkspaceMessageErrorKind::EditorAccessRequired => {
            ApiError::Forbidden("Workspace editor access required")
        }
        PublicWorkspaceMessageErrorKind::Conflict => {
            ApiError::Conflict("Workspace message idempotency conflict".to_string())
        }
        PublicWorkspaceMessageErrorKind::Unavailable => {
            ApiError::InvalidDatabase(error.to_string())
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn send_body_ignores_extra_fields_and_preserves_structured_mentions() -> Result<(), &'static str>
    {
        let parsed = parse_send_request(json!({
            "content": "hello",
            "mentions": ["agent-1", "member-1"],
            "legacy_extra": {"ignored": true}
        }))
        .map_err(|_| "valid message request was rejected")?;
        assert_eq!(parsed.sender_type, "human");
        assert_eq!(parsed.mentions, ["agent-1", "member-1"]);
        Ok(())
    }

    #[test]
    fn empty_content_is_validation_but_whitespace_reaches_the_service() -> Result<(), &'static str>
    {
        assert!(matches!(
            parse_send_request(json!({"content": ""})),
            Err(ApiError::Validation(_))
        ));
        let whitespace = parse_send_request(json!({"content": "  "}))
            .map_err(|_| "transport-valid whitespace was rejected")?;
        assert_eq!(whitespace.content, "  ");
        Ok(())
    }

    #[test]
    fn message_limit_matches_legacy_bounds() {
        assert_eq!(query_limit(None).ok(), Some(50));
        assert_eq!(query_limit(Some("1.0")).ok(), Some(1));
        assert!(matches!(
            query_limit(Some("0")),
            Err(ApiError::Validation(_))
        ));
        assert!(matches!(
            query_limit(Some("201")),
            Err(ApiError::Validation(_))
        ));
    }
}
