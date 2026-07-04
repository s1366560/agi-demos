//! Rust WebSocket bridge for the strangled agent surface (F7/P3 foundation).
//!
//! This is intentionally a foundation slice, not the full Python
//! `SessionProcessor` port. It proves the stable transport contract first:
//! browser-compatible auth subprotocols, heartbeat/ack/error messages,
//! conversation subscription with stream replay, and Rust-produced agent events
//! written to the shared `EventStream` (`agent:events:{conversation_id}`).

mod subscriptions;

use axum::{
    extract::{
        ws::{Message, WebSocket, WebSocketUpgrade},
        Query, State,
    },
    http::{HeaderMap, StatusCode},
    response::{IntoResponse, Response},
};
use serde::Deserialize;
use serde_json::{json, Value};
use tokio::time::{self, Duration};

use crate::auth::{AuthRejection, Identity};
use crate::AppState;
use agistack_core::agent::events::{derive_event_id, AgentEventType, EventEnvelope};
use subscriptions::{flush_event_subscriptions, ConnectionSubscriptions};

const WEBSOCKET_AUTH_SUBPROTOCOL: &str = "memstack.auth";
const EVENT_STREAM_MAX_LEN: usize = 1000;

#[derive(Debug, Deserialize)]
pub(crate) struct AgentWsQuery {
    token: Option<String>,
    session_id: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
enum ClientMessage {
    Heartbeat,
    Subscribe {
        conversation_id: String,
        #[serde(default)]
        last_event_id: Option<String>,
        #[serde(default)]
        message_id: Option<String>,
        #[serde(default)]
        from_time_us: Option<i64>,
        #[serde(default)]
        from_counter: Option<u64>,
    },
    Unsubscribe {
        conversation_id: String,
    },
    SendMessage {
        conversation_id: String,
        message: String,
        project_id: String,
        #[serde(default)]
        message_id: Option<String>,
    },
    StopSession {
        conversation_id: String,
    },
    SubscribeStatus {
        project_id: String,
    },
    UnsubscribeStatus {
        project_id: String,
    },
    SubscribeLifecycleState {
        project_id: String,
        #[serde(default)]
        tenant_id: Option<String>,
    },
    UnsubscribeLifecycleState {
        project_id: String,
        #[serde(default)]
        tenant_id: Option<String>,
    },
    SubscribeSandbox {
        project_id: String,
        #[serde(default)]
        tenant_id: Option<String>,
    },
    UnsubscribeSandbox {
        project_id: String,
        #[serde(default)]
        tenant_id: Option<String>,
    },
}

/// `GET /api/v1/agent/ws` — WebSocket bridge compatible with the existing
/// browser client. Authentication happens before the upgrade; accepted sockets
/// echo the `memstack.auth` subprotocol when offered.
pub(crate) async fn agent_ws(
    State(app): State<AppState>,
    Query(query): Query<AgentWsQuery>,
    headers: HeaderMap,
    ws: WebSocketUpgrade,
) -> Response {
    let raw_key = match extract_ws_api_key(&headers, query.token.as_deref()) {
        Some(key) => key,
        None => {
            return AuthRejection {
                status: StatusCode::UNAUTHORIZED,
                detail: "Missing API key. Please provide an API key in the WebSocket protocol or token query parameter.".to_string(),
            }
            .into_response();
        }
    };

    let identity = match app
        .auth
        .authenticate(&raw_key, chrono::Utc::now().timestamp_millis())
        .await
    {
        Ok(identity) => identity,
        Err(rejection) => return rejection.into_response(),
    };

    let session_id = query.session_id.unwrap_or_else(|| "ws-session".to_string());
    ws.protocols([WEBSOCKET_AUTH_SUBPROTOCOL])
        .on_upgrade(move |socket| handle_socket(app, identity, session_id, socket))
}

fn extract_ws_api_key(headers: &HeaderMap, token: Option<&str>) -> Option<String> {
    if let Some(raw) = headers
        .get(axum::http::header::AUTHORIZATION)
        .and_then(|v| v.to_str().ok())
        .and_then(extract_authorization_key)
    {
        return Some(raw.to_string());
    }

    if let Some(raw) = headers
        .get(axum::http::header::SEC_WEBSOCKET_PROTOCOL)
        .and_then(|v| v.to_str().ok())
        .and_then(extract_protocol_key)
    {
        return Some(raw.to_string());
    }

    token
        .filter(|value| value.starts_with("ms_sk_"))
        .map(ToString::to_string)
}

fn extract_authorization_key(value: &str) -> Option<&str> {
    value
        .strip_prefix("Bearer ")
        .or_else(|| value.strip_prefix("Token "))
        .or(Some(value))
        .filter(|raw| raw.starts_with("ms_sk_"))
}

fn extract_protocol_key(value: &str) -> Option<&str> {
    value
        .split(',')
        .map(str::trim)
        .find(|part| *part != WEBSOCKET_AUTH_SUBPROTOCOL && part.starts_with("ms_sk_"))
}

async fn handle_socket(
    app: AppState,
    identity: Identity,
    session_id: String,
    mut socket: WebSocket,
) {
    let mut subscriptions = ConnectionSubscriptions::default();
    let mut interval = time::interval(Duration::from_millis(250));
    let _ = send_json(
        &mut socket,
        json!({
            "type": "ack",
            "action": "connect",
            "session_id": session_id,
            "timestamp": now_iso(),
        }),
    )
    .await;

    loop {
        tokio::select! {
            incoming = socket.recv() => {
                let Some(Ok(message)) = incoming else {
                    break;
                };
                if !handle_client_message(&app, &identity, &mut socket, &mut subscriptions, message).await {
                    break;
                }
            }
            _ = interval.tick() => {
                if flush_event_subscriptions(&app, &mut socket, &mut subscriptions).await.is_err() {
                    break;
                }
            }
        }
    }
}

async fn handle_client_message(
    app: &AppState,
    identity: &Identity,
    socket: &mut WebSocket,
    subscriptions: &mut ConnectionSubscriptions,
    message: Message,
) -> bool {
    let Message::Text(text) = message else {
        return true;
    };
    let parsed: Result<ClientMessage, _> = serde_json::from_str(&text);
    let Ok(parsed) = parsed else {
        let _ = send_error(socket, "Invalid WebSocket message").await;
        return true;
    };

    match parsed {
        ClientMessage::Heartbeat => {
            let _ = send_json(socket, json!({"type": "heartbeat", "timestamp": now_iso()})).await;
        }
        ClientMessage::Subscribe {
            conversation_id,
            last_event_id,
            message_id,
            from_time_us,
            from_counter,
        } => {
            if !subscriptions.subscribe_conversation(
                conversation_id.clone(),
                last_event_id,
                message_id,
                from_time_us,
                from_counter,
            ) {
                let _ = send_subscription_limit_error(
                    socket,
                    json!({"conversation_id": conversation_id}),
                )
                .await;
                return true;
            }
            let _ = send_ack(
                socket,
                "subscribe",
                json!({"conversation_id": conversation_id}),
            )
            .await;
        }
        ClientMessage::Unsubscribe { conversation_id } => {
            subscriptions.unsubscribe_conversation(&conversation_id);
            let _ = send_ack(
                socket,
                "unsubscribe",
                json!({"conversation_id": conversation_id}),
            )
            .await;
        }
        ClientMessage::SubscribeStatus { project_id } => {
            let _ = send_ack(
                socket,
                "subscribe_status",
                json!({"project_id": project_id}),
            )
            .await;
            let _ = send_status_update(socket, &project_id).await;
        }
        ClientMessage::UnsubscribeStatus { project_id } => {
            let _ = send_ack(
                socket,
                "unsubscribe_status",
                json!({"project_id": project_id}),
            )
            .await;
        }
        ClientMessage::SubscribeLifecycleState {
            project_id,
            tenant_id,
        } => {
            let _ = send_ack(
                socket,
                "subscribe_lifecycle_state",
                json!({"project_id": project_id, "tenant_id": tenant_id}),
            )
            .await;
            let _ = send_lifecycle_state(socket, &project_id).await;
        }
        ClientMessage::UnsubscribeLifecycleState {
            project_id,
            tenant_id,
        } => {
            let _ = send_ack(
                socket,
                "unsubscribe_lifecycle_state",
                json!({"project_id": project_id, "tenant_id": tenant_id}),
            )
            .await;
        }
        ClientMessage::SubscribeSandbox {
            project_id,
            tenant_id,
        } => {
            if !subscriptions.subscribe_sandbox(project_id.clone()) {
                let _ =
                    send_subscription_limit_error(socket, json!({"project_id": project_id})).await;
                return true;
            }
            let _ = send_ack(
                socket,
                "subscribe_sandbox",
                json!({"project_id": project_id, "tenant_id": tenant_id}),
            )
            .await;
        }
        ClientMessage::UnsubscribeSandbox {
            project_id,
            tenant_id,
        } => {
            subscriptions.unsubscribe_sandbox(&project_id);
            let _ = send_ack(
                socket,
                "unsubscribe_sandbox",
                json!({"project_id": project_id, "tenant_id": tenant_id}),
            )
            .await;
        }
        ClientMessage::SendMessage {
            conversation_id,
            message,
            project_id,
            message_id,
        } => {
            if !subscriptions.ensure_conversation(conversation_id.clone(), message_id.clone()) {
                let _ = send_subscription_limit_error(
                    socket,
                    json!({"conversation_id": conversation_id}),
                )
                .await;
                return true;
            }
            let _ = send_ack(
                socket,
                "send_message",
                json!({"conversation_id": conversation_id}),
            )
            .await;
            if let Err(err) = run_agent_message(
                app,
                identity,
                &conversation_id,
                &project_id,
                message_id.as_deref(),
                &message,
            )
            .await
            {
                let data = json!({"message": err, "conversation_id": conversation_id});
                let _ =
                    append_event(app, &conversation_id, AgentEventType::Error, data.clone()).await;
                let _ = send_json(
                    socket,
                    json!({"type": "error", "conversation_id": conversation_id, "data": data}),
                )
                .await;
            }
        }
        ClientMessage::StopSession { conversation_id } => {
            let data = json!({"conversation_id": conversation_id, "cancelled": true});
            let _ = append_event(app, &conversation_id, AgentEventType::Cancelled, data).await;
            let _ = send_ack(
                socket,
                "stop_session",
                json!({"conversation_id": conversation_id}),
            )
            .await;
        }
    }
    true
}

async fn run_agent_message(
    app: &AppState,
    identity: &Identity,
    conversation_id: &str,
    project_id: &str,
    message_id: Option<&str>,
    message: &str,
) -> Result<(), String> {
    let allowed = app
        .auth
        .can_access_project(&identity.user_id, project_id)
        .await?;
    if !allowed {
        return Err("Access denied".to_string());
    }

    append_event(
        app,
        conversation_id,
        AgentEventType::Start,
        json!({
            "conversation_id": conversation_id,
            "message_id": message_id,
            "project_id": project_id,
        }),
    )
    .await?;

    let state = app
        .engine
        .run(conversation_id, message, Some(project_id))
        .await
        .map_err(|e| e.to_string())?;
    append_event(
        app,
        conversation_id,
        AgentEventType::Complete,
        json!({
            "conversation_id": conversation_id,
            "message_id": message_id,
            "project_id": project_id,
            "answer": state.answer,
            "session": state,
        }),
    )
    .await?;
    Ok(())
}

async fn send_subscription_limit_error(
    socket: &mut WebSocket,
    extra: Value,
) -> Result<(), axum::Error> {
    let mut message = json!({
        "type": "error",
        "data": {"message": "Too many active subscriptions"}
    });
    if let (Some(base), Some(extra)) = (message.as_object_mut(), extra.as_object()) {
        base.extend(extra.clone());
    }
    send_json(socket, message).await
}

async fn append_event(
    app: &AppState,
    conversation_id: &str,
    event_type: AgentEventType,
    data: Value,
) -> Result<(), String> {
    let counter = app
        .event_counter
        .fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        + 1;
    let event_time_us = chrono::Utc::now().timestamp_micros();
    let envelope = EventEnvelope::wrap(
        event_type,
        data.clone(),
        derive_event_id(&format!(
            "{conversation_id}:{}:{counter}",
            event_type.as_str()
        )),
        now_iso(),
    )
    .with_correlation(conversation_id.to_string(), None);
    let payload = json!({
        "type": event_type.as_str(),
        "data": data,
        "event_time_us": event_time_us,
        "event_counter": counter,
        "envelope": envelope.to_value(),
    });
    app.events
        .append(
            &stream_topic(conversation_id),
            &payload.to_string(),
            EVENT_STREAM_MAX_LEN,
        )
        .await
        .map(|_| ())
        .map_err(|e| e.to_string())
}

async fn send_status_update(socket: &mut WebSocket, project_id: &str) -> Result<(), axum::Error> {
    send_json(socket, status_update_message(project_id)).await
}

fn status_update_message(project_id: &str) -> Value {
    json!({
        "type": "status_update",
        "project_id": project_id,
        "data": {
            "is_initialized": false,
            "is_active": false,
            "total_chats": 0,
            "active_chats": 0,
            "tool_count": 0,
            "cached_since": Value::Null,
            "workflow_id": "default",
        },
        "timestamp": now_iso(),
    })
}

async fn send_lifecycle_state(socket: &mut WebSocket, project_id: &str) -> Result<(), axum::Error> {
    send_json(socket, lifecycle_state_message(project_id)).await
}

fn lifecycle_state_message(project_id: &str) -> Value {
    json!({
        "type": "lifecycle_state_change",
        "project_id": project_id,
        "data": {
            "lifecycle_state": "uninitialized",
            "is_active": false,
            "is_initialized": false,
        },
        "timestamp": now_iso(),
    })
}

async fn send_ack(socket: &mut WebSocket, action: &str, extra: Value) -> Result<(), axum::Error> {
    let mut message = json!({
        "type": "ack",
        "action": action,
        "timestamp": now_iso(),
    });
    if let (Some(base), Some(extra)) = (message.as_object_mut(), extra.as_object()) {
        base.extend(extra.clone());
    }
    send_json(socket, message).await
}

async fn send_error(socket: &mut WebSocket, message: &str) -> Result<(), axum::Error> {
    send_json(
        socket,
        json!({"type": "error", "data": {"message": message}}),
    )
    .await
}

async fn send_json(socket: &mut WebSocket, value: Value) -> Result<(), axum::Error> {
    socket.send(Message::Text(value.to_string())).await
}

fn stream_topic(conversation_id: &str) -> String {
    format!("agent:events:{conversation_id}")
}

fn now_iso() -> String {
    chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Micros, true)
}

#[cfg(test)]
mod tests {
    use axum::http::{HeaderMap, HeaderValue};

    use super::*;

    #[test]
    fn extracts_protocol_api_key() {
        let mut headers = HeaderMap::new();
        headers.insert(
            axum::http::header::SEC_WEBSOCKET_PROTOCOL,
            HeaderValue::from_static("memstack.auth, ms_sk_abc123"),
        );
        assert_eq!(
            extract_ws_api_key(&headers, None).as_deref(),
            Some("ms_sk_abc123")
        );
    }

    #[test]
    fn authorization_beats_query_token() {
        let mut headers = HeaderMap::new();
        headers.insert(
            axum::http::header::AUTHORIZATION,
            HeaderValue::from_static("Bearer ms_sk_header"),
        );
        assert_eq!(
            extract_ws_api_key(&headers, Some("ms_sk_query")).as_deref(),
            Some("ms_sk_header")
        );
    }

    #[test]
    fn status_update_matches_python_default_shape() {
        let message = status_update_message("p1");

        assert_eq!(message["type"], "status_update");
        assert_eq!(message["project_id"], "p1");
        assert_eq!(message["data"]["is_initialized"], false);
        assert_eq!(message["data"]["is_active"], false);
        assert_eq!(message["data"]["total_chats"], 0);
        assert_eq!(message["data"]["active_chats"], 0);
        assert_eq!(message["data"]["tool_count"], 0);
        assert_eq!(message["data"]["cached_since"], Value::Null);
        assert_eq!(message["data"]["workflow_id"], "default");
        assert!(message["timestamp"].as_str().is_some());
    }

    #[test]
    fn lifecycle_state_matches_python_uninitialized_shape() {
        let message = lifecycle_state_message("p1");

        assert_eq!(message["type"], "lifecycle_state_change");
        assert_eq!(message["project_id"], "p1");
        assert_eq!(message["data"]["lifecycle_state"], "uninitialized");
        assert_eq!(message["data"]["is_active"], false);
        assert_eq!(message["data"]["is_initialized"], false);
        assert!(message["timestamp"].as_str().is_some());
    }
}
