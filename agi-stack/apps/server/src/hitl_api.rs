//! P3/F7 HITL response ingress.
//!
//! The Python runtime already persists HITL requests in `hitl_requests` and
//! resumes workers from Redis Streams (`hitl:response:{tenant}:{project}`). This
//! module ports the response ingress without touching portable core: Postgres
//! stays in `adapters-postgres`, stream delivery stays behind `EventStream`, and
//! the HTTP/WS wire shape remains FastAPI compatible.

use std::{
    collections::HashMap,
    sync::{Arc, Mutex},
};

use async_trait::async_trait;
use axum::{
    extract::State,
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::post,
    Extension, Json, Router,
};
use chrono::{DateTime, SecondsFormat, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};

use agistack_adapters_postgres::{HitlRequestRecord, PgHitlRequestRepository, PgPool};
use agistack_adapters_secrets::try_encrypt_python_aes256_gcm;
use agistack_core::ports::EventStream;

use crate::{auth::Identity, AppState};

const HITL_RESPONSE_STREAM_MAX_LEN: usize = 1000;
const HITL_RESPONSE_ENCODING: &str = "aes256gcm+json";

pub(crate) type SharedHitlResponses = Arc<dyn HitlResponseService>;

#[async_trait]
pub(crate) trait HitlResponseService: Send + Sync {
    async fn respond(
        &self,
        user_id: &str,
        request: HitlResponsePayload,
    ) -> Result<HitlResponseOutcome, HitlApiError>;
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct HitlResponsePayload {
    pub request_id: String,
    pub hitl_type: String,
    pub response_data: Value,
}

#[derive(Debug, Clone)]
pub(crate) struct HitlResponseOutcome {
    pub request_id: String,
    pub hitl_type: String,
    pub conversation_id: String,
    pub delivery_pending: bool,
}

#[derive(Debug, Serialize)]
pub(crate) struct HumanInteractionResponse {
    success: bool,
    message: String,
}

#[derive(Debug)]
pub(crate) struct HitlApiError {
    status: StatusCode,
    detail: String,
}

impl HitlApiError {
    fn new(status: StatusCode, detail: impl Into<String>) -> Self {
        Self {
            status,
            detail: detail.into(),
        }
    }

    fn bad_request(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::BAD_REQUEST, detail)
    }

    fn forbidden(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::FORBIDDEN, detail)
    }

    fn not_found(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::NOT_FOUND, detail)
    }

    fn internal(detail: impl std::fmt::Display) -> Self {
        Self::new(StatusCode::INTERNAL_SERVER_ERROR, detail.to_string())
    }

    pub(crate) fn detail(&self) -> &str {
        &self.detail
    }
}

impl IntoResponse for HitlApiError {
    fn into_response(self) -> Response {
        (self.status, Json(json!({ "detail": self.detail }))).into_response()
    }
}

pub(crate) struct PgHitlResponseService {
    repo: PgHitlRequestRepository,
    events: Arc<dyn EventStream>,
    encryption_key: Option<Arc<str>>,
}

impl PgHitlResponseService {
    pub(crate) fn new(
        repo: PgHitlRequestRepository,
        events: Arc<dyn EventStream>,
        encryption_key: Option<Arc<str>>,
    ) -> Self {
        Self {
            repo,
            events,
            encryption_key,
        }
    }
}

#[async_trait]
impl HitlResponseService for PgHitlResponseService {
    async fn respond(
        &self,
        user_id: &str,
        request: HitlResponsePayload,
    ) -> Result<HitlResponseOutcome, HitlApiError> {
        let now = Utc::now();
        let record = self
            .repo
            .get_by_id(&request.request_id)
            .await
            .map_err(HitlApiError::internal)?
            .ok_or_else(|| HitlApiError::not_found("HITL request not found"))?;

        authorize_hitl_request(&self.repo, user_id, &record).await?;
        if record.is_expired_at(now) {
            let _ = self.repo.mark_timeout(&record.id).await;
            return Err(HitlApiError::bad_request("HITL request has expired"));
        }
        if record.status != "pending" {
            return Err(HitlApiError::bad_request(
                "HITL request is no longer pending",
            ));
        }

        let prepared = prepare_response(&record, request, now, self.encryption_key.as_deref())?;
        let updated = self
            .repo
            .update_response(
                &record.id,
                &prepared.response_summary,
                prepared.response_metadata.as_ref(),
                now,
            )
            .await
            .map_err(HitlApiError::internal)?;
        if !updated {
            return Err(HitlApiError::new(
                StatusCode::CONFLICT,
                "HITL request could not be updated",
            ));
        }

        let delivery_pending = publish_hitl_response(
            Arc::clone(&self.events),
            &record,
            user_id,
            &prepared.hitl_type,
            prepared.stream_response,
            now,
        )
        .await
        .is_err();

        Ok(HitlResponseOutcome {
            request_id: record.id,
            hitl_type: prepared.hitl_type,
            conversation_id: record.conversation_id,
            delivery_pending,
        })
    }
}

pub(crate) struct DevHitlResponseService {
    records: Mutex<HashMap<String, HitlRequestRecord>>,
    events: Arc<dyn EventStream>,
    encryption_key: Option<Arc<str>>,
}

impl DevHitlResponseService {
    pub(crate) fn new(events: Arc<dyn EventStream>) -> Self {
        Self {
            records: Mutex::new(HashMap::new()),
            events,
            encryption_key: None,
        }
    }

    pub(crate) fn with_encryption_key(
        events: Arc<dyn EventStream>,
        encryption_key: impl Into<Arc<str>>,
    ) -> Self {
        Self {
            records: Mutex::new(HashMap::new()),
            events,
            encryption_key: Some(encryption_key.into()),
        }
    }

    #[cfg(test)]
    pub(crate) fn insert_request(&self, record: HitlRequestRecord) -> Result<(), HitlApiError> {
        let mut records = self
            .records
            .lock()
            .map_err(|_| HitlApiError::internal("hitl request store mutex poisoned"))?;
        records.insert(record.id.clone(), record);
        Ok(())
    }

    #[cfg(test)]
    pub(crate) fn get_request(
        &self,
        request_id: &str,
    ) -> Result<Option<HitlRequestRecord>, HitlApiError> {
        let records = self
            .records
            .lock()
            .map_err(|_| HitlApiError::internal("hitl request store mutex poisoned"))?;
        Ok(records.get(request_id).cloned())
    }
}

#[async_trait]
impl HitlResponseService for DevHitlResponseService {
    async fn respond(
        &self,
        user_id: &str,
        request: HitlResponsePayload,
    ) -> Result<HitlResponseOutcome, HitlApiError> {
        let now = Utc::now();
        let record = {
            let records = self
                .records
                .lock()
                .map_err(|_| HitlApiError::internal("hitl request store mutex poisoned"))?;
            records
                .get(&request.request_id)
                .cloned()
                .ok_or_else(|| HitlApiError::not_found("HITL request not found"))?
        };

        if let Some(expected_user) = record.user_id.as_deref() {
            if expected_user != user_id {
                return Err(HitlApiError::forbidden(
                    "Access denied to this HITL request",
                ));
            }
        }
        if record.is_expired_at(now) {
            mark_dev_status(&self.records, &record.id, "timeout")?;
            return Err(HitlApiError::bad_request("HITL request has expired"));
        }
        if record.status != "pending" {
            return Err(HitlApiError::bad_request(
                "HITL request is no longer pending",
            ));
        }

        let prepared = prepare_response(&record, request, now, self.encryption_key.as_deref())?;
        {
            let mut records = self
                .records
                .lock()
                .map_err(|_| HitlApiError::internal("hitl request store mutex poisoned"))?;
            let Some(stored) = records.get_mut(&record.id) else {
                return Err(HitlApiError::new(
                    StatusCode::CONFLICT,
                    "HITL request could not be updated",
                ));
            };
            stored.status = "answered".to_string();
            stored.response = Some(prepared.response_summary.clone());
            stored.response_metadata = prepared.response_metadata.clone();
        }

        let delivery_pending = publish_hitl_response(
            Arc::clone(&self.events),
            &record,
            user_id,
            &prepared.hitl_type,
            prepared.stream_response,
            now,
        )
        .await
        .is_err();

        Ok(HitlResponseOutcome {
            request_id: record.id,
            hitl_type: prepared.hitl_type,
            conversation_id: record.conversation_id,
            delivery_pending,
        })
    }
}

pub(crate) fn build_hitl_response_service(
    pool: Option<PgPool>,
    events: Arc<dyn EventStream>,
) -> SharedHitlResponses {
    let encryption_key = std::env::var("LLM_ENCRYPTION_KEY")
        .ok()
        .filter(|key| !key.trim().is_empty())
        .map(Arc::<str>::from);
    match pool {
        Some(pool) => Arc::new(PgHitlResponseService::new(
            PgHitlRequestRepository::new(pool),
            events,
            encryption_key,
        )),
        None => match encryption_key {
            Some(encryption_key) => Arc::new(DevHitlResponseService::with_encryption_key(
                events,
                encryption_key,
            )),
            None => Arc::new(DevHitlResponseService::new(events)),
        },
    }
}

pub(crate) fn router() -> Router<AppState> {
    Router::new().route("/api/v1/agent/hitl/respond", post(respond_to_hitl))
}

pub(crate) async fn respond_to_hitl(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Json(request): Json<HitlResponsePayload>,
) -> Result<Json<HumanInteractionResponse>, HitlApiError> {
    let outcome = app.hitl.respond(&identity.user_id, request).await?;
    Ok(Json(HumanInteractionResponse {
        success: true,
        message: response_message(&outcome),
    }))
}

pub(crate) fn response_message(outcome: &HitlResponseOutcome) -> String {
    let label = title_case_hitl_type(&outcome.hitl_type);
    if outcome.delivery_pending {
        format!("{label} response saved. Delivery is pending.")
    } else {
        format!("{label} response received")
    }
}

pub(crate) fn hitl_stream_topic(tenant_id: &str, project_id: &str) -> String {
    format!("hitl:response:{tenant_id}:{project_id}")
}

pub(crate) fn ws_ack_message(ack_type: &str, outcome: &HitlResponseOutcome) -> Value {
    let mut message = json!({
        "type": ack_type,
        "request_id": outcome.request_id,
        "success": true,
        "conversation_id": outcome.conversation_id,
    });
    if outcome.delivery_pending {
        message["delivery_pending"] = Value::Bool(true);
    }
    message
}

#[derive(Debug)]
struct PreparedHitlResponse {
    hitl_type: String,
    stream_response: PreparedStreamResponse,
    response_summary: String,
    response_metadata: Option<Value>,
}

#[derive(Debug)]
enum PreparedStreamResponse {
    Plain(Value),
    Encrypted(String),
}

async fn authorize_hitl_request(
    repo: &PgHitlRequestRepository,
    user_id: &str,
    record: &HitlRequestRecord,
) -> Result<(), HitlApiError> {
    let has_tenant_access = repo
        .user_has_tenant_access(user_id, &record.tenant_id)
        .await
        .map_err(HitlApiError::internal)?;
    if !has_tenant_access {
        return Err(HitlApiError::forbidden(
            "Access denied to this HITL request",
        ));
    }

    let has_access = if let Some(expected_user) = record.user_id.as_deref() {
        expected_user == user_id
            && repo
                .user_has_project_access(user_id, &record.project_id)
                .await
                .map_err(HitlApiError::internal)?
    } else {
        repo.user_has_conversation_access(user_id, &record.tenant_id, &record.conversation_id)
            .await
            .map_err(HitlApiError::internal)?
    };

    if has_access {
        Ok(())
    } else {
        Err(HitlApiError::forbidden(
            "Access denied to this HITL request",
        ))
    }
}

fn mark_dev_status(
    records: &Mutex<HashMap<String, HitlRequestRecord>>,
    request_id: &str,
    status: &str,
) -> Result<(), HitlApiError> {
    let mut records = records
        .lock()
        .map_err(|_| HitlApiError::internal("hitl request store mutex poisoned"))?;
    if let Some(record) = records.get_mut(request_id) {
        record.status = status.to_string();
    }
    Ok(())
}

fn prepare_response(
    record: &HitlRequestRecord,
    request: HitlResponsePayload,
    _now: DateTime<Utc>,
    encryption_key: Option<&str>,
) -> Result<PreparedHitlResponse, HitlApiError> {
    let stored_hitl_type = stored_hitl_type(record)
        .ok_or_else(|| HitlApiError::bad_request("HITL request has an invalid stored type"))?;
    if request.hitl_type != stored_hitl_type {
        return Err(HitlApiError::bad_request(
            "HITL type does not match request",
        ));
    }
    if stored_hitl_type == "env_var" {
        return Err(HitlApiError::bad_request(
            "env_var HITL is not supported by the Rust endpoint yet",
        ));
    }

    let response = response_object(&request.response_data)?;
    validate_response_shape(&stored_hitl_type, response)?;
    if stored_hitl_type == "a2ui_action" {
        validate_allowed_a2ui_action(record, response)?;
        return prepare_a2ui_response(stored_hitl_type, request.response_data, encryption_key);
    }
    let response_summary = summarize_response(&stored_hitl_type, response);

    Ok(PreparedHitlResponse {
        hitl_type: stored_hitl_type,
        stream_response: PreparedStreamResponse::Plain(request.response_data),
        response_summary,
        response_metadata: None,
    })
}

fn prepare_a2ui_response(
    hitl_type: String,
    response_data: Value,
    encryption_key: Option<&str>,
) -> Result<PreparedHitlResponse, HitlApiError> {
    let encryption_key = encryption_key
        .ok_or_else(|| HitlApiError::internal("HITL response encryption is unavailable"))?;
    let response = response_object(&response_data)?;
    let response_summary = summarize_response(&hitl_type, response);
    let source_component_id = response
        .get("source_component_id")
        .and_then(Value::as_str)
        .map(sanitize_hitl_text)
        .unwrap_or_default();
    let plaintext = serde_json::to_string(&response_data)
        .map_err(|_| HitlApiError::internal("HITL response serialization failed"))?;
    let sealed_response = encrypt_hitl_response(&plaintext, encryption_key)?;
    let stream_response = encrypt_hitl_response(&plaintext, encryption_key)?;

    Ok(PreparedHitlResponse {
        hitl_type,
        stream_response: PreparedStreamResponse::Encrypted(stream_response),
        response_summary,
        response_metadata: Some(json!({
            "source_component_id": source_component_id,
            "context": {},
            "sealed_response": sealed_response,
            "sealed_response_encoding": HITL_RESPONSE_ENCODING,
        })),
    })
}

fn encrypt_hitl_response(plaintext: &str, encryption_key: &str) -> Result<String, HitlApiError> {
    try_encrypt_python_aes256_gcm(plaintext, encryption_key)
        .map_err(|_| HitlApiError::internal("HITL response encryption is unavailable"))
}

fn stored_hitl_type(record: &HitlRequestRecord) -> Option<String> {
    record
        .request_metadata
        .as_ref()
        .and_then(Value::as_object)
        .and_then(|metadata| metadata.get("hitl_type"))
        .and_then(Value::as_str)
        .filter(|hitl_type| !hitl_type.is_empty())
        .map(ToString::to_string)
        .or_else(|| (!record.request_type.is_empty()).then(|| record.request_type.clone()))
}

fn response_object(response_data: &Value) -> Result<&Map<String, Value>, HitlApiError> {
    response_data
        .as_object()
        .ok_or_else(|| HitlApiError::bad_request("Invalid HITL response"))
}

fn validate_response_shape(
    hitl_type: &str,
    response_data: &Map<String, Value>,
) -> Result<(), HitlApiError> {
    let has_cancelled = response_data
        .get("cancelled")
        .is_some_and(|value| value == true);
    let has_timeout = response_data
        .get("timeout")
        .is_some_and(|value| value == true);
    if hitl_type != "env_var" && (has_cancelled || has_timeout) {
        return Err(HitlApiError::bad_request(
            "cancelled/timeout responses are only supported for env_var HITL",
        ));
    }

    match hitl_type {
        "clarification" => require_present(response_data, "answer"),
        "decision" => require_present(response_data, "decision"),
        "permission" => validate_permission_response(response_data),
        "a2ui_action" => validate_a2ui_response_shape(response_data),
        _ => Err(HitlApiError::bad_request("Invalid HITL type")),
    }
}

fn validate_a2ui_response_shape(response_data: &Map<String, Value>) -> Result<(), HitlApiError> {
    let action_name_is_valid = response_data
        .get("action_name")
        .and_then(Value::as_str)
        .is_some_and(|value| !value.trim().is_empty());
    let source_component_id_is_valid = response_data
        .get("source_component_id")
        .and_then(Value::as_str)
        .is_some_and(|value| !value.trim().is_empty());
    let context_is_stateless = response_data
        .get("context")
        .and_then(Value::as_object)
        .is_some_and(Map::is_empty);
    if action_name_is_valid && source_component_id_is_valid && context_is_stateless {
        Ok(())
    } else {
        Err(HitlApiError::bad_request(
            "Invalid stateless A2UI action response",
        ))
    }
}

fn validate_allowed_a2ui_action(
    record: &HitlRequestRecord,
    response_data: &Map<String, Value>,
) -> Result<(), HitlApiError> {
    let action_name = response_data
        .get("action_name")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let source_component_id = response_data
        .get("source_component_id")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let is_allowed = record
        .request_metadata
        .as_ref()
        .and_then(Value::as_object)
        .and_then(|metadata| metadata.get("allowed_actions"))
        .and_then(Value::as_array)
        .is_some_and(|allowed_actions| {
            allowed_actions.iter().any(|allowed_action| {
                let Some(allowed_action) = allowed_action.as_object() else {
                    return false;
                };
                allowed_action.get("action_name").and_then(Value::as_str) == Some(action_name)
                    && allowed_action
                        .get("source_component_id")
                        .and_then(Value::as_str)
                        == Some(source_component_id)
            })
        });
    if is_allowed {
        Ok(())
    } else {
        Err(HitlApiError::forbidden("A2UI action is not allowed"))
    }
}

fn require_present(response_data: &Map<String, Value>, key: &str) -> Result<(), HitlApiError> {
    match response_data.get(key) {
        Some(Value::Null) | None => Err(HitlApiError::bad_request("Invalid HITL response")),
        Some(_) => Ok(()),
    }
}

fn validate_permission_response(response_data: &Map<String, Value>) -> Result<(), HitlApiError> {
    let has_granted = response_data.get("granted").is_some_and(Value::is_boolean);
    let has_action = response_data
        .get("action")
        .and_then(Value::as_str)
        .is_some_and(|action| matches!(action, "allow" | "deny"));
    if has_granted || has_action {
        Ok(())
    } else {
        Err(HitlApiError::bad_request("Invalid HITL response"))
    }
}

fn summarize_response(hitl_type: &str, response_data: &Map<String, Value>) -> String {
    match hitl_type {
        "clarification" => choice_like_summary(response_data.get("answer")),
        "decision" => choice_like_summary(response_data.get("decision")),
        "permission" => permission_summary(response_data),
        "a2ui_action" => response_data
            .get("action_name")
            .and_then(Value::as_str)
            .map(sanitize_hitl_text)
            .unwrap_or_default(),
        _ => String::new(),
    }
}

fn sanitize_hitl_text(raw: &str) -> String {
    let stripped = raw
        .chars()
        .filter(|character| {
            !matches!(*character as u32, 0x00..=0x08 | 0x0b | 0x0c | 0x0e..=0x1f | 0x7f)
        })
        .collect::<String>();
    let trimmed = stripped.trim();
    let mut escaped = String::with_capacity(trimmed.len());
    for character in trimmed.chars() {
        match character {
            '&' => escaped.push_str("&amp;"),
            '<' => escaped.push_str("&lt;"),
            '>' => escaped.push_str("&gt;"),
            '"' => escaped.push_str("&quot;"),
            '\'' => escaped.push_str("&#x27;"),
            _ => escaped.push(character),
        }
    }
    escaped
}

fn choice_like_summary(value: Option<&Value>) -> String {
    match value {
        Some(Value::String(raw)) => raw.clone(),
        Some(Value::Array(items)) => serde_json::to_string(items).unwrap_or_default(),
        Some(Value::Bool(raw)) => raw.to_string(),
        Some(Value::Number(raw)) => raw.to_string(),
        _ => String::new(),
    }
}

fn permission_summary(response_data: &Map<String, Value>) -> String {
    response_data
        .get("action")
        .and_then(Value::as_str)
        .map(ToString::to_string)
        .or_else(|| {
            response_data
                .get("granted")
                .and_then(Value::as_bool)
                .map(|v| v.to_string())
        })
        .unwrap_or_default()
}

async fn publish_hitl_response(
    events: Arc<dyn EventStream>,
    record: &HitlRequestRecord,
    user_id: &str,
    hitl_type: &str,
    stream_response: PreparedStreamResponse,
    now: DateTime<Utc>,
) -> Result<(), String> {
    let agent_mode = record
        .request_metadata
        .as_ref()
        .and_then(Value::as_object)
        .and_then(|metadata| metadata.get("agent_mode"))
        .and_then(Value::as_str)
        .unwrap_or("default");
    let mut payload = json!({
        "request_id": record.id,
        "hitl_type": hitl_type,
        "user_id": user_id,
        "conversation_id": record.conversation_id,
        "message_id": record.message_id,
        "tenant_id": record.tenant_id,
        "project_id": record.project_id,
        "agent_mode": agent_mode,
        "timestamp": now.to_rfc3339_opts(SecondsFormat::Micros, true),
    });
    let payload_object = payload
        .as_object_mut()
        .ok_or_else(|| "failed to build HITL response payload".to_string())?;
    match stream_response {
        PreparedStreamResponse::Plain(response_data) => {
            payload_object.insert("response_data".to_string(), response_data);
        }
        PreparedStreamResponse::Encrypted(response_data_encrypted) => {
            payload_object.insert(
                "response_data_encrypted".to_string(),
                Value::String(response_data_encrypted),
            );
            payload_object.insert(
                "response_data_encoding".to_string(),
                Value::String(HITL_RESPONSE_ENCODING.to_string()),
            );
        }
    }
    events
        .append(
            &hitl_stream_topic(&record.tenant_id, &record.project_id),
            &payload.to_string(),
            HITL_RESPONSE_STREAM_MAX_LEN,
        )
        .await
        .map(|_| ())
        .map_err(|err| err.to_string())
}

fn title_case_hitl_type(hitl_type: &str) -> String {
    hitl_type
        .split('_')
        .filter(|part| !part.is_empty())
        .map(|part| {
            let mut chars = part.chars();
            match chars.next() {
                Some(first) => first.to_uppercase().chain(chars).collect::<String>(),
                None => String::new(),
            }
        })
        .collect::<Vec<_>>()
        .join(" ")
}

#[cfg(test)]
mod tests {
    use super::*;
    use agistack_adapters_mem::InMemoryEventStream;
    use agistack_adapters_secrets::try_decrypt_python_aes256_gcm;

    const TEST_ENCRYPTION_KEY: &str =
        "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f";

    fn pending_request(request_id: &str, hitl_type: &str) -> HitlRequestRecord {
        HitlRequestRecord {
            id: request_id.to_string(),
            request_type: hitl_type.to_string(),
            conversation_id: "conv1".to_string(),
            message_id: Some("msg1".to_string()),
            tenant_id: "tenant1".to_string(),
            project_id: "project1".to_string(),
            user_id: Some("user1".to_string()),
            question: "continue?".to_string(),
            options: None,
            context: None,
            request_metadata: Some(json!({"agent_mode": "default"})),
            status: "pending".to_string(),
            response: None,
            response_metadata: None,
            expires_at: None,
        }
    }

    fn a2ui_request(request_id: &str) -> HitlRequestRecord {
        let mut record = pending_request(request_id, "a2ui_action");
        record.request_metadata = Some(json!({
            "agent_mode": "default",
            "hitl_type": "a2ui_action",
            "allowed_actions": [{
                "source_component_id": "approve-button",
                "action_name": "approve",
            }],
        }));
        record
    }

    #[tokio::test]
    async fn dev_service_persists_and_publishes_clarification_response() {
        let events = Arc::new(InMemoryEventStream::new());
        let service = DevHitlResponseService::new(events.clone());
        service
            .insert_request(pending_request("req1", "clarification"))
            .unwrap();

        let outcome = service
            .respond(
                "user1",
                HitlResponsePayload {
                    request_id: "req1".to_string(),
                    hitl_type: "clarification".to_string(),
                    response_data: json!({"answer": "yes"}),
                },
            )
            .await
            .unwrap();

        assert_eq!(outcome.conversation_id, "conv1");
        assert!(!outcome.delivery_pending);
        let entries = events
            .read_after(&hitl_stream_topic("tenant1", "project1"), "", 10)
            .await
            .unwrap();
        assert_eq!(entries.len(), 1);
        let payload: Value = serde_json::from_str(&entries[0].payload).unwrap();
        assert_eq!(payload["request_id"], "req1");
        assert_eq!(payload["hitl_type"], "clarification");
        assert_eq!(payload["response_data"]["answer"], "yes");
    }

    #[test]
    fn ws_ack_message_matches_python_shape() {
        let message = ws_ack_message(
            "decision_response_ack",
            &HitlResponseOutcome {
                request_id: "req1".to_string(),
                hitl_type: "decision".to_string(),
                conversation_id: "conv1".to_string(),
                delivery_pending: false,
            },
        );

        assert_eq!(message["type"], "decision_response_ack");
        assert_eq!(message["request_id"], "req1");
        assert_eq!(message["success"], true);
        assert_eq!(message["conversation_id"], "conv1");
        assert!(message.get("delivery_pending").is_none());
    }

    #[test]
    fn human_interaction_response_matches_golden() {
        let actual = serde_json::to_value(HumanInteractionResponse {
            success: true,
            message: "Clarification response received".to_string(),
        })
        .unwrap();
        let golden: Value =
            serde_json::from_str(include_str!("../tests/golden/hitl_response.json")).unwrap();

        agistack_parity::assert_parity(&golden, &actual);
    }

    #[test]
    fn rejects_env_var_until_secret_storage_is_supported() {
        let err = prepare_response(
            &pending_request("req1", "env_var"),
            HitlResponsePayload {
                request_id: "req1".to_string(),
                hitl_type: "env_var".to_string(),
                response_data: json!({"values": {"TOKEN": "secret"}}),
            },
            Utc::now(),
            None,
        )
        .unwrap_err();

        assert_eq!(err.status, StatusCode::BAD_REQUEST);
        assert_eq!(
            err.detail(),
            "env_var HITL is not supported by the Rust endpoint yet"
        );
    }

    #[test]
    fn accepts_allowlisted_stateless_a2ui_action() {
        let prepared = prepare_response(
            &a2ui_request("req-a2ui"),
            HitlResponsePayload {
                request_id: "req-a2ui".to_string(),
                hitl_type: "a2ui_action".to_string(),
                response_data: json!({
                    "action_name": "approve",
                    "source_component_id": "approve-button",
                    "context": {},
                }),
            },
            Utc::now(),
            Some(TEST_ENCRYPTION_KEY),
        )
        .unwrap();

        assert_eq!(prepared.hitl_type, "a2ui_action");
        assert_eq!(prepared.response_summary, "approve");
        let response_metadata = prepared.response_metadata.unwrap();
        assert_eq!(response_metadata["source_component_id"], "approve-button");
        assert_eq!(response_metadata["context"], json!({}));
        let sealed_response = response_metadata["sealed_response"].as_str().unwrap();
        assert_eq!(
            response_metadata["sealed_response_encoding"],
            HITL_RESPONSE_ENCODING
        );
        let decrypted_sealed =
            try_decrypt_python_aes256_gcm(sealed_response, TEST_ENCRYPTION_KEY).unwrap();
        assert_eq!(
            serde_json::from_str::<Value>(&decrypted_sealed).unwrap(),
            json!({
                "action_name": "approve",
                "source_component_id": "approve-button",
                "context": {},
            })
        );
        let PreparedStreamResponse::Encrypted(stream_response) = prepared.stream_response else {
            panic!("A2UI stream response must be encrypted");
        };
        assert_ne!(stream_response, sealed_response);
        let decrypted_stream =
            try_decrypt_python_aes256_gcm(&stream_response, TEST_ENCRYPTION_KEY).unwrap();
        assert_eq!(decrypted_stream, decrypted_sealed);
    }

    #[test]
    fn rejects_a2ui_without_key_or_exact_allowlist_match() {
        let request = HitlResponsePayload {
            request_id: "req-a2ui".to_string(),
            hitl_type: "a2ui_action".to_string(),
            response_data: json!({
                "action_name": "approve",
                "source_component_id": "approve-button",
                "context": {},
            }),
        };
        let missing_key =
            prepare_response(&a2ui_request("req-a2ui"), request.clone(), Utc::now(), None)
                .unwrap_err();
        assert_eq!(missing_key.status, StatusCode::INTERNAL_SERVER_ERROR);

        let mut no_allowlist = a2ui_request("req-a2ui");
        no_allowlist.request_metadata = Some(json!({
            "agent_mode": "default",
            "hitl_type": "a2ui_action",
            "allowed_actions": [],
        }));
        let forbidden = prepare_response(
            &no_allowlist,
            request,
            Utc::now(),
            Some(TEST_ENCRYPTION_KEY),
        )
        .unwrap_err();
        assert_eq!(forbidden.status, StatusCode::FORBIDDEN);
    }

    #[test]
    fn rejects_dynamic_a2ui_context_on_stateless_rust_boundary() {
        let err = prepare_response(
            &a2ui_request("req-a2ui"),
            HitlResponsePayload {
                request_id: "req-a2ui".to_string(),
                hitl_type: "a2ui_action".to_string(),
                response_data: json!({
                    "action_name": "approve",
                    "source_component_id": "approve-button",
                    "context": {"secret": "must-not-cross-stateless-boundary"},
                }),
            },
            Utc::now(),
            Some(TEST_ENCRYPTION_KEY),
        )
        .unwrap_err();

        assert_eq!(err.status, StatusCode::BAD_REQUEST);
        assert_eq!(err.detail(), "Invalid stateless A2UI action response");
    }

    #[tokio::test]
    async fn dev_service_persists_and_publishes_encrypted_a2ui_response() {
        let events = Arc::new(InMemoryEventStream::new());
        let service =
            DevHitlResponseService::with_encryption_key(events.clone(), TEST_ENCRYPTION_KEY);
        service.insert_request(a2ui_request("req-a2ui")).unwrap();

        let outcome = service
            .respond(
                "user1",
                HitlResponsePayload {
                    request_id: "req-a2ui".to_string(),
                    hitl_type: "a2ui_action".to_string(),
                    response_data: json!({
                        "action_name": "approve",
                        "source_component_id": "approve-button",
                        "context": {},
                    }),
                },
            )
            .await
            .unwrap();

        assert!(!outcome.delivery_pending);
        let stored = service.get_request("req-a2ui").unwrap().unwrap();
        assert_eq!(stored.status, "answered");
        assert_eq!(stored.response.as_deref(), Some("approve"));
        assert_eq!(
            stored.response_metadata.as_ref().unwrap()["sealed_response_encoding"],
            HITL_RESPONSE_ENCODING
        );

        let entries = events
            .read_after(&hitl_stream_topic("tenant1", "project1"), "", 10)
            .await
            .unwrap();
        assert_eq!(entries.len(), 1);
        let payload: Value = serde_json::from_str(&entries[0].payload).unwrap();
        assert!(payload.get("response_data").is_none());
        assert_eq!(payload["response_data_encoding"], HITL_RESPONSE_ENCODING);
        let decrypted = try_decrypt_python_aes256_gcm(
            payload["response_data_encrypted"].as_str().unwrap(),
            TEST_ENCRYPTION_KEY,
        )
        .unwrap();
        assert_eq!(
            serde_json::from_str::<Value>(&decrypted).unwrap(),
            json!({
                "action_name": "approve",
                "source_component_id": "approve-button",
                "context": {},
            })
        );
    }

    #[tokio::test]
    async fn dev_service_bad_key_fails_before_claim_or_publish() {
        let events = Arc::new(InMemoryEventStream::new());
        let service = DevHitlResponseService::with_encryption_key(events.clone(), "invalid-key");
        service.insert_request(a2ui_request("req-a2ui")).unwrap();

        let err = service
            .respond(
                "user1",
                HitlResponsePayload {
                    request_id: "req-a2ui".to_string(),
                    hitl_type: "a2ui_action".to_string(),
                    response_data: json!({
                        "action_name": "approve",
                        "source_component_id": "approve-button",
                        "context": {},
                    }),
                },
            )
            .await
            .unwrap_err();

        assert_eq!(err.status, StatusCode::INTERNAL_SERVER_ERROR);
        assert_eq!(err.detail(), "HITL response encryption is unavailable");
        let stored = service.get_request("req-a2ui").unwrap().unwrap();
        assert_eq!(stored.status, "pending");
        assert!(stored.response.is_none());
        assert!(stored.response_metadata.is_none());
        let entries = events
            .read_after(&hitl_stream_topic("tenant1", "project1"), "", 10)
            .await
            .unwrap();
        assert!(entries.is_empty());
    }
}
