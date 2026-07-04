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
use agistack_core::ports::EventStream;

use crate::{auth::Identity, AppState};

const HITL_RESPONSE_STREAM_MAX_LEN: usize = 1000;

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
}

impl PgHitlResponseService {
    pub(crate) fn new(repo: PgHitlRequestRepository, events: Arc<dyn EventStream>) -> Self {
        Self { repo, events }
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

        let prepared = prepare_response(&record, request, now)?;
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
            prepared.response_data,
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
}

impl DevHitlResponseService {
    pub(crate) fn new(events: Arc<dyn EventStream>) -> Self {
        Self {
            records: Mutex::new(HashMap::new()),
            events,
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

        let prepared = prepare_response(&record, request, now)?;
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
        }

        let delivery_pending = publish_hitl_response(
            Arc::clone(&self.events),
            &record,
            user_id,
            &prepared.hitl_type,
            prepared.response_data,
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
    match pool {
        Some(pool) => Arc::new(PgHitlResponseService::new(
            PgHitlRequestRepository::new(pool),
            events,
        )),
        None => Arc::new(DevHitlResponseService::new(events)),
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
    response_data: Value,
    response_summary: String,
    response_metadata: Option<Value>,
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
) -> Result<PreparedHitlResponse, HitlApiError> {
    let stored_hitl_type = stored_hitl_type(record)
        .ok_or_else(|| HitlApiError::bad_request("HITL request has an invalid stored type"))?;
    if request.hitl_type != stored_hitl_type {
        return Err(HitlApiError::bad_request(
            "HITL type does not match request",
        ));
    }
    if matches!(stored_hitl_type.as_str(), "env_var" | "a2ui_action") {
        return Err(HitlApiError::bad_request(
            "Sensitive HITL type is not supported by the Rust endpoint yet",
        ));
    }

    let response = response_object(&request.response_data)?;
    validate_response_shape(&stored_hitl_type, response)?;
    let response_summary = summarize_response(&stored_hitl_type, response);

    Ok(PreparedHitlResponse {
        hitl_type: stored_hitl_type,
        response_data: request.response_data,
        response_summary,
        response_metadata: None,
    })
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
        _ => Err(HitlApiError::bad_request("Invalid HITL type")),
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
        _ => String::new(),
    }
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
    response_data: Value,
    now: DateTime<Utc>,
) -> Result<(), String> {
    let agent_mode = record
        .request_metadata
        .as_ref()
        .and_then(Value::as_object)
        .and_then(|metadata| metadata.get("agent_mode"))
        .and_then(Value::as_str)
        .unwrap_or("default");
    let payload = json!({
        "request_id": record.id,
        "hitl_type": hitl_type,
        "user_id": user_id,
        "conversation_id": record.conversation_id,
        "message_id": record.message_id,
        "tenant_id": record.tenant_id,
        "project_id": record.project_id,
        "agent_mode": agent_mode,
        "timestamp": now.to_rfc3339_opts(SecondsFormat::Micros, true),
        "response_data": response_data,
    });
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
            expires_at: None,
        }
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
    fn rejects_sensitive_hitl_types_until_encryption_port_exists() {
        let err = prepare_response(
            &pending_request("req1", "env_var"),
            HitlResponsePayload {
                request_id: "req1".to_string(),
                hitl_type: "env_var".to_string(),
                response_data: json!({"values": {"TOKEN": "secret"}}),
            },
            Utc::now(),
        )
        .unwrap_err();

        assert_eq!(err.status, StatusCode::BAD_REQUEST);
        assert_eq!(
            err.detail(),
            "Sensitive HITL type is not supported by the Rust endpoint yet"
        );
    }
}
