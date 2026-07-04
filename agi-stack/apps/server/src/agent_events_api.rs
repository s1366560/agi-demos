//! Agent event replay HTTP surface for the strangled F7/P3 path.
//!
//! Production reads Python-owned `agent_execution_events` after checking the
//! Python-owned conversation access rules. Offline/dev keeps a small in-process
//! `EventStream` replay path so the server remains runnable without Postgres.

use std::sync::Arc;

use async_trait::async_trait;
use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::get,
    Extension, Json, Router,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use agistack_adapters_postgres::{
    AgentExecutionEventListQuery, AgentExecutionEventRecord, ConversationReplayAccess,
    PgAgentExecutionEventRepository,
};
use agistack_core::ports::EventStream;

use crate::auth::Identity;
use crate::AppState;

const DEFAULT_REPLAY_LIMIT: i64 = 1000;
const MAX_REPLAY_LIMIT: i64 = 10_000;

pub(crate) type SharedAgentEvents = Arc<dyn AgentEventReplayService>;

#[async_trait]
pub(crate) trait AgentEventReplayService: Send + Sync {
    async fn replay_events(
        &self,
        user_id: &str,
        conversation_id: &str,
        cursor: ValidatedEventReplayQuery,
    ) -> Result<EventReplayResponse, AgentEventsApiError>;
}

pub(crate) struct PgAgentEventReplayService {
    repo: PgAgentExecutionEventRepository,
}

impl PgAgentEventReplayService {
    pub(crate) fn new(repo: PgAgentExecutionEventRepository) -> Self {
        Self { repo }
    }
}

#[async_trait]
impl AgentEventReplayService for PgAgentEventReplayService {
    async fn replay_events(
        &self,
        user_id: &str,
        conversation_id: &str,
        cursor: ValidatedEventReplayQuery,
    ) -> Result<EventReplayResponse, AgentEventsApiError> {
        match self
            .repo
            .replay_access(user_id, conversation_id)
            .await
            .map_err(AgentEventsApiError::internal)?
        {
            ConversationReplayAccess::Allowed => {}
            ConversationReplayAccess::Denied => {
                return Err(AgentEventsApiError::forbidden(
                    "Access denied to this conversation",
                ));
            }
            ConversationReplayAccess::NotFound => {
                return Err(AgentEventsApiError::not_found("Conversation not found"));
            }
        }

        let events = self
            .repo
            .list_events(AgentExecutionEventListQuery {
                conversation_id,
                from_time_us: cursor.from_time_us,
                from_counter: cursor.from_counter,
                limit: cursor.limit,
            })
            .await
            .map_err(AgentEventsApiError::internal)?;
        Ok(EventReplayResponse::from_records(events, cursor.limit))
    }
}

pub(crate) struct DevAgentEventReplayService {
    events: Arc<dyn EventStream>,
}

impl DevAgentEventReplayService {
    pub(crate) fn new(events: Arc<dyn EventStream>) -> Self {
        Self { events }
    }
}

#[async_trait]
impl AgentEventReplayService for DevAgentEventReplayService {
    async fn replay_events(
        &self,
        _user_id: &str,
        conversation_id: &str,
        cursor: ValidatedEventReplayQuery,
    ) -> Result<EventReplayResponse, AgentEventsApiError> {
        let entries = self
            .events
            .read_after(
                &agent_stream_topic(conversation_id),
                "",
                cursor.limit as usize,
            )
            .await
            .map_err(AgentEventsApiError::internal)?;
        let events: Vec<EventReplayItem> = entries
            .into_iter()
            .filter_map(|entry| stream_payload_to_replay_item(&entry.payload))
            .filter(|event| event.is_after(cursor.from_time_us, cursor.from_counter))
            .take(cursor.limit as usize)
            .collect();
        Ok(EventReplayResponse {
            has_more: events.len() == cursor.limit as usize,
            events,
        })
    }
}

pub(crate) fn router() -> Router<AppState> {
    Router::new().route(
        "/api/v1/agent/conversations/:conversation_id/events",
        get(get_conversation_events),
    )
}

async fn get_conversation_events(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(conversation_id): Path<String>,
    Query(query): Query<EventReplayQuery>,
) -> Result<Json<EventReplayResponse>, AgentEventsApiError> {
    let cursor = query.validated()?;
    let response = app
        .agent_events
        .replay_events(&identity.user_id, &conversation_id, cursor)
        .await?;
    Ok(Json(response))
}

#[derive(Debug, Clone, Copy, Deserialize)]
pub(crate) struct EventReplayQuery {
    pub(crate) from_time_us: Option<i64>,
    pub(crate) from_counter: Option<i64>,
    pub(crate) limit: Option<i64>,
}

impl EventReplayQuery {
    fn validated(&self) -> Result<ValidatedEventReplayQuery, AgentEventsApiError> {
        let from_time_us = self.from_time_us.unwrap_or_default();
        if from_time_us < 0 {
            return Err(AgentEventsApiError::unprocessable(
                "from_time_us must be greater than or equal to 0",
            ));
        }
        let from_counter = self.from_counter.unwrap_or_default();
        if from_counter < 0 {
            return Err(AgentEventsApiError::unprocessable(
                "from_counter must be greater than or equal to 0",
            ));
        }
        let limit = self.limit.unwrap_or(DEFAULT_REPLAY_LIMIT);
        if !(1..=MAX_REPLAY_LIMIT).contains(&limit) {
            return Err(AgentEventsApiError::unprocessable(
                "limit must be greater than or equal to 1 and less than or equal to 10000",
            ));
        }
        Ok(ValidatedEventReplayQuery {
            from_time_us,
            from_counter,
            limit,
        })
    }
}

#[derive(Debug, Clone, Copy)]
pub(crate) struct ValidatedEventReplayQuery {
    from_time_us: i64,
    from_counter: i64,
    limit: i64,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct EventReplayResponse {
    events: Vec<EventReplayItem>,
    has_more: bool,
}

impl EventReplayResponse {
    fn from_records(records: Vec<AgentExecutionEventRecord>, limit: i64) -> Self {
        Self {
            has_more: records.len() == limit as usize,
            events: records.into_iter().map(EventReplayItem::from).collect(),
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct EventReplayItem {
    #[serde(rename = "type")]
    event_type: String,
    data: Value,
    event_time_us: i64,
    event_counter: i64,
    timestamp: Option<String>,
}

impl EventReplayItem {
    fn is_after(&self, from_time_us: i64, from_counter: i64) -> bool {
        self.event_time_us > from_time_us
            || (self.event_time_us == from_time_us && self.event_counter > from_counter)
    }
}

impl From<AgentExecutionEventRecord> for EventReplayItem {
    fn from(record: AgentExecutionEventRecord) -> Self {
        Self {
            event_type: record.event_type,
            data: record.event_data,
            event_time_us: record.event_time_us,
            event_counter: i64::from(record.event_counter),
            timestamp: record.created_at.map(|created_at| created_at.to_rfc3339()),
        }
    }
}

#[derive(Debug)]
pub(crate) struct AgentEventsApiError {
    status: StatusCode,
    detail: String,
}

impl AgentEventsApiError {
    fn new(status: StatusCode, detail: impl Into<String>) -> Self {
        Self {
            status,
            detail: detail.into(),
        }
    }

    fn forbidden(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::FORBIDDEN, detail)
    }

    fn not_found(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::NOT_FOUND, detail)
    }

    fn unprocessable(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::UNPROCESSABLE_ENTITY, detail)
    }

    fn internal(detail: impl std::fmt::Display) -> Self {
        Self::new(StatusCode::INTERNAL_SERVER_ERROR, detail.to_string())
    }
}

impl IntoResponse for AgentEventsApiError {
    fn into_response(self) -> Response {
        (self.status, Json(json!({ "detail": self.detail }))).into_response()
    }
}

fn stream_payload_to_replay_item(payload: &str) -> Option<EventReplayItem> {
    let parsed: Value = serde_json::from_str(payload).ok()?;
    let event_type = parsed
        .get("type")
        .or_else(|| parsed.get("event_type"))
        .and_then(Value::as_str)?
        .to_string();
    let data = parsed
        .get("data")
        .or_else(|| parsed.get("payload"))
        .cloned()
        .unwrap_or(Value::Null);
    let event_time_us = parsed
        .get("event_time_us")
        .or_else(|| parsed.get("time_us"))
        .and_then(Value::as_i64)?;
    let event_counter = parsed
        .get("event_counter")
        .or_else(|| parsed.get("counter"))
        .and_then(Value::as_i64)
        .unwrap_or_default();
    let timestamp = parsed
        .get("timestamp")
        .and_then(Value::as_str)
        .map(ToString::to_string)
        .or_else(|| {
            parsed
                .pointer("/envelope/timestamp")
                .and_then(Value::as_str)
                .map(ToString::to_string)
        });
    Some(EventReplayItem {
        event_type,
        data,
        event_time_us,
        event_counter,
        timestamp,
    })
}

fn agent_stream_topic(conversation_id: &str) -> String {
    format!("agent:events:{conversation_id}")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn replay_query_defaults_match_python_contract() {
        let query = EventReplayQuery {
            from_time_us: None,
            from_counter: None,
            limit: None,
        };

        let validated = query.validated().expect("default query is valid");

        assert_eq!(validated.from_time_us, 0);
        assert_eq!(validated.from_counter, 0);
        assert_eq!(validated.limit, DEFAULT_REPLAY_LIMIT);
    }

    #[test]
    fn replay_query_rejects_out_of_range_values() {
        assert_eq!(
            EventReplayQuery {
                from_time_us: Some(-1),
                from_counter: Some(0),
                limit: Some(1),
            }
            .validated()
            .expect_err("negative from_time_us rejected")
            .status,
            StatusCode::UNPROCESSABLE_ENTITY
        );
        assert_eq!(
            EventReplayQuery {
                from_time_us: Some(0),
                from_counter: Some(-1),
                limit: Some(1),
            }
            .validated()
            .expect_err("negative from_counter rejected")
            .status,
            StatusCode::UNPROCESSABLE_ENTITY
        );
        assert_eq!(
            EventReplayQuery {
                from_time_us: Some(0),
                from_counter: Some(0),
                limit: Some(MAX_REPLAY_LIMIT + 1),
            }
            .validated()
            .expect_err("limit above max rejected")
            .status,
            StatusCode::UNPROCESSABLE_ENTITY
        );
    }

    #[test]
    fn postgres_record_renders_python_sse_format() {
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/agent_event_replay_response.json"
        ))
        .expect("agent event replay golden must be valid JSON");
        let record = AgentExecutionEventRecord {
            event_type: "thought".to_string(),
            event_data: json!({"text": "hello"}),
            event_time_us: 42,
            event_counter: 3,
            created_at: None,
        };

        let response = EventReplayResponse::from_records(vec![record], 100);
        let value = serde_json::to_value(response).expect("response serializes");

        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn stream_payload_renders_python_sse_format() {
        let payload = json!({
            "type": "complete",
            "data": {"answer": "ok"},
            "event_time_us": 100,
            "event_counter": 2,
            "envelope": {"timestamp": "2026-01-01T00:00:00Z"}
        });

        let event = stream_payload_to_replay_item(&payload.to_string())
            .expect("valid Rust stream payload converts");

        assert_eq!(event.event_type, "complete");
        assert_eq!(event.data, json!({"answer": "ok"}));
        assert_eq!(event.event_time_us, 100);
        assert_eq!(event.event_counter, 2);
        assert_eq!(event.timestamp.as_deref(), Some("2026-01-01T00:00:00Z"));
    }
}
