//! Rust WebSocket bridge for the strangled agent surface (F7/P3 foundation).
//!
//! This is intentionally a foundation slice, not the full Python
//! `SessionProcessor` port. It proves the stable transport contract first:
//! browser-compatible auth subprotocols, heartbeat/ack/error messages,
//! conversation subscription with stream replay, and Rust-produced agent events
//! written to the shared `EventStream` (`agent:events:{conversation_id}`).
//! Workspace runtime slices can also subscribe to `workspace:events:{workspace_id}`
//! after project access is checked, which lets P6 mention token chunks replay over
//! the same WebSocket transport without broad workspace endpoint takeover.

mod subscriptions;

use std::sync::Arc;

use async_trait::async_trait;
use axum::{
    extract::{
        ws::{Message, WebSocket, WebSocketUpgrade},
        Query, State,
    },
    http::{HeaderMap, StatusCode},
    response::{IntoResponse, Response},
};
use serde::Deserialize;
use serde_json::{json, Map, Value};
use tokio::time::{self, Duration};

use agistack_adapters_postgres::AgentExecutionEventInsertRecord;
use agistack_core::agent::{HitlRequest, ReActObserver};
use agistack_core::ports::CoreResult;

use crate::auth::{AuthRejection, Identity};
use crate::hitl_api::{ws_ack_message, HitlResponsePayload};
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
    SubscribeWorkspace {
        workspace_id: String,
        project_id: String,
        #[serde(default)]
        tenant_id: Option<String>,
        #[serde(default)]
        last_event_id: Option<String>,
    },
    UnsubscribeWorkspace {
        workspace_id: String,
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
    ClarificationRespond {
        request_id: String,
        answer: Value,
    },
    DecisionRespond {
        request_id: String,
        decision: Value,
    },
    EnvVarRespond {
        request_id: String,
        #[serde(default)]
        values: Option<Value>,
        #[serde(default)]
        cancelled: bool,
        #[serde(default)]
        timeout: bool,
    },
    PermissionRespond {
        request_id: String,
        granted: bool,
    },
    A2uiActionRespond {
        request_id: String,
        action_name: Value,
        #[serde(default)]
        source_component_id: Option<String>,
        #[serde(default)]
        context: Option<Value>,
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
        ClientMessage::SubscribeWorkspace {
            workspace_id,
            project_id,
            tenant_id,
            last_event_id,
        } => {
            let resolved_tenant_id = match app
                .workspaces
                .authorize_workspace_event_subscription(
                    &identity.user_id,
                    &workspace_id,
                    &project_id,
                    tenant_id.as_deref(),
                )
                .await
            {
                Ok(resolved_tenant_id) => resolved_tenant_id,
                Err(_) => {
                    let _ = send_error(socket, "Access denied").await;
                    return true;
                }
            };
            let requested_tenant_id = tenant_id.as_deref();
            if requested_tenant_id
                .map(|value| value != resolved_tenant_id)
                .unwrap_or(false)
            {
                let _ = send_error(socket, "Access denied").await;
                return true;
            }
            if !subscriptions.subscribe_workspace(workspace_id.clone(), last_event_id) {
                let _ = send_subscription_limit_error(
                    socket,
                    json!({"workspace_id": workspace_id, "project_id": project_id}),
                )
                .await;
                return true;
            }
            let _ = send_ack(
                socket,
                "subscribe_workspace",
                json!({
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "tenant_id": resolved_tenant_id
                }),
            )
            .await;
        }
        ClientMessage::UnsubscribeWorkspace { workspace_id } => {
            subscriptions.unsubscribe_workspace(&workspace_id);
            let _ = send_ack(
                socket,
                "unsubscribe_workspace",
                json!({"workspace_id": workspace_id}),
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
            let run_app = app.clone();
            let run_identity = identity.clone();
            let run_conversation_id = conversation_id.clone();
            let run_project_id = project_id.clone();
            let run_message_id = message_id.clone();
            tokio::spawn(async move {
                if let Err(err) = run_agent_message(
                    &run_app,
                    &run_identity,
                    &run_conversation_id,
                    &run_project_id,
                    run_message_id.as_deref(),
                    &message,
                )
                .await
                {
                    let data = agent_error_event_data(
                        &run_conversation_id,
                        &run_project_id,
                        run_message_id.as_deref(),
                        &err,
                    );
                    let _ =
                        append_event(&run_app, &run_conversation_id, AgentEventType::Error, data)
                            .await;
                }
            });
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
        ClientMessage::ClarificationRespond { request_id, answer } => {
            let request = HitlResponsePayload {
                request_id,
                hitl_type: "clarification".to_string(),
                response_data: json!({"answer": answer}),
            };
            let _ =
                handle_hitl_response(app, identity, socket, request, "clarification_response_ack")
                    .await;
        }
        ClientMessage::DecisionRespond {
            request_id,
            decision,
        } => {
            let request = HitlResponsePayload {
                request_id,
                hitl_type: "decision".to_string(),
                response_data: json!({"decision": decision}),
            };
            let _ =
                handle_hitl_response(app, identity, socket, request, "decision_response_ack").await;
        }
        ClientMessage::EnvVarRespond {
            request_id,
            values,
            cancelled,
            timeout,
        } => {
            let response_data = match (values, cancelled, timeout) {
                (Some(values), false, false) => json!({"values": values}),
                (None, true, false) => json!({"cancelled": true}),
                (None, false, true) => json!({"timeout": true}),
                _ => {
                    let _ = send_error(
                        socket,
                        "Missing required fields: request_id and exactly one of values/cancelled/timeout",
                    )
                    .await;
                    return true;
                }
            };
            let request = HitlResponsePayload {
                request_id,
                hitl_type: "env_var".to_string(),
                response_data,
            };
            let _ =
                handle_hitl_response(app, identity, socket, request, "env_var_response_ack").await;
        }
        ClientMessage::PermissionRespond {
            request_id,
            granted,
        } => {
            let action = if granted { "allow" } else { "deny" };
            let request = HitlResponsePayload {
                request_id,
                hitl_type: "permission".to_string(),
                response_data: json!({"granted": granted, "action": action}),
            };
            let _ = handle_hitl_response(app, identity, socket, request, "permission_response_ack")
                .await;
        }
        ClientMessage::A2uiActionRespond {
            request_id,
            action_name,
            source_component_id,
            context,
        } => {
            let request = HitlResponsePayload {
                request_id,
                hitl_type: "a2ui_action".to_string(),
                response_data: json!({
                    "action_name": action_name,
                    "source_component_id": source_component_id.unwrap_or_default(),
                    "context": context.unwrap_or_else(|| json!({})),
                }),
            };
            let _ =
                handle_hitl_response(app, identity, socket, request, "a2ui_action_response_ack")
                    .await;
        }
    }
    true
}

async fn handle_hitl_response(
    app: &AppState,
    identity: &Identity,
    socket: &mut WebSocket,
    request: HitlResponsePayload,
    ack_type: &str,
) -> Result<(), axum::Error> {
    match app.hitl.respond(&identity.user_id, request).await {
        Ok(outcome) => send_json(socket, ws_ack_message(ack_type, &outcome)).await,
        Err(err) => send_error(socket, err.detail()).await,
    }
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
        AgentEventType::UserMessage,
        json!({
            "conversation_id": conversation_id,
            "message_id": message_id,
            "project_id": project_id,
            "role": "user",
            "content": message,
        }),
    )
    .await?;

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

    let observer = Arc::new(AgentWsRunObserver {
        app: app.clone(),
        conversation_id: conversation_id.to_string(),
        project_id: project_id.to_string(),
        message_id: message_id.map(ToString::to_string),
    });
    let run_session_id = agent_run_session_id(conversation_id, message_id);
    let state = app
        .engine
        .run_observed(&run_session_id, message, Some(project_id), observer)
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

#[derive(Clone)]
struct AgentWsRunObserver {
    app: AppState,
    conversation_id: String,
    project_id: String,
    message_id: Option<String>,
}

#[async_trait]
impl ReActObserver for AgentWsRunObserver {
    async fn on_tool_call(
        &self,
        _session_id: &str,
        round: u64,
        tool: &str,
        input_json: &str,
    ) -> CoreResult<()> {
        let input = json_or_string(input_json);
        let mut data = tool_event_base(
            &self.conversation_id,
            &self.project_id,
            self.message_id.as_deref(),
            round,
            tool,
        );
        data.insert("tool_input".to_string(), input.clone());
        data.insert(
            "input_json".to_string(),
            Value::String(input_json.to_string()),
        );
        copy_tool_metadata(&mut data, &input);
        append_event(
            &self.app,
            &self.conversation_id,
            AgentEventType::Act,
            Value::Object(data),
        )
        .await
        .map_err(agistack_core::ports::CoreError::Event)
    }

    async fn on_tool_result(
        &self,
        _session_id: &str,
        round: u64,
        tool: &str,
        input_json: &str,
        output_json: &str,
    ) -> CoreResult<()> {
        let input = json_or_string(input_json);
        let output = json_or_string(output_json);
        let mut data = tool_event_base(
            &self.conversation_id,
            &self.project_id,
            self.message_id.as_deref(),
            round,
            tool,
        );
        data.insert("tool_input".to_string(), input.clone());
        data.insert("tool_output".to_string(), output.clone());
        data.insert(
            "observation".to_string(),
            Value::String(output_json.to_string()),
        );
        data.insert("is_error".to_string(), Value::Bool(false));
        copy_tool_metadata(&mut data, &input);
        copy_tool_metadata(&mut data, &output);
        append_event(
            &self.app,
            &self.conversation_id,
            AgentEventType::Observe,
            Value::Object(data),
        )
        .await
        .map_err(agistack_core::ports::CoreError::Event)
    }

    async fn on_finish(&self, _session_id: &str, _round: u64, answer: &str) -> CoreResult<()> {
        append_event(
            &self.app,
            &self.conversation_id,
            AgentEventType::AssistantMessage,
            json!({
                "conversation_id": self.conversation_id.as_str(),
                "message_id": self.message_id.as_deref(),
                "project_id": self.project_id.as_str(),
                "role": "assistant",
                "content": answer,
            }),
        )
        .await
        .map_err(agistack_core::ports::CoreError::Event)
    }

    async fn on_human_request(
        &self,
        _session_id: &str,
        _round: u64,
        request: &HitlRequest,
    ) -> CoreResult<()> {
        append_event(
            &self.app,
            &self.conversation_id,
            AgentEventType::ClarificationAsked,
            json!({
                "conversation_id": self.conversation_id.as_str(),
                "message_id": self.message_id.as_deref(),
                "project_id": self.project_id.as_str(),
                "request_id": request.id.as_str(),
                "question": request.prompt.as_str(),
                "kind": format!("{:?}", request.kind),
                "answered": false,
            }),
        )
        .await
        .map_err(agistack_core::ports::CoreError::Event)
    }
}

fn agent_run_session_id(conversation_id: &str, message_id: Option<&str>) -> String {
    match message_id.map(str::trim).filter(|value| !value.is_empty()) {
        Some(message_id) => format!("{conversation_id}:{message_id}"),
        None => format!(
            "{conversation_id}:{}",
            chrono::Utc::now().timestamp_micros()
        ),
    }
}

fn tool_event_base(
    conversation_id: &str,
    project_id: &str,
    message_id: Option<&str>,
    round: u64,
    tool: &str,
) -> Map<String, Value> {
    let mut data = Map::new();
    data.insert("conversation_id".to_string(), conversation_id.into());
    data.insert("project_id".to_string(), project_id.into());
    data.insert(
        "message_id".to_string(),
        message_id.map_or(Value::Null, |value| value.into()),
    );
    data.insert("round".to_string(), round.into());
    data.insert("tool_name".to_string(), tool.into());
    data
}

fn json_or_string(raw: &str) -> Value {
    serde_json::from_str(raw).unwrap_or_else(|_| Value::String(raw.to_string()))
}

fn copy_tool_metadata(target: &mut Map<String, Value>, source: &Value) {
    copy_value_path(target, source, &["display"], "display");
    copy_value_path(target, source, &["metadata", "display"], "display");
    copy_value_path(target, source, &["fileMetadata"], "fileMetadata");
    copy_value_path(target, source, &["file_metadata"], "fileMetadata");
    copy_value_path(
        target,
        source,
        &["metadata", "fileMetadata"],
        "fileMetadata",
    );
    copy_value_path(
        target,
        source,
        &["metadata", "file_metadata"],
        "fileMetadata",
    );
}

fn copy_value_path(
    target: &mut Map<String, Value>,
    source: &Value,
    path: &[&str],
    target_key: &str,
) {
    if target.contains_key(target_key) {
        return;
    }
    let mut current = source;
    for segment in path {
        let Some(next) = current.get(*segment) else {
            return;
        };
        current = next;
    }
    if !current.is_null() {
        target.insert(target_key.to_string(), current.clone());
    }
}

fn agent_error_event_data(
    conversation_id: &str,
    project_id: &str,
    message_id: Option<&str>,
    message: &str,
) -> Value {
    json!({
        "conversation_id": conversation_id,
        "message_id": message_id,
        "project_id": project_id,
        "message": message,
        "error": message,
        "is_error": true,
    })
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
    let event_id = derive_event_id(&format!(
        "{conversation_id}:{}:{counter}",
        event_type.as_str()
    ));
    let envelope = EventEnvelope::wrap(event_type, data.clone(), event_id.clone(), now_iso())
        .with_correlation(conversation_id.to_string(), None);
    let payload = json!({
        "type": event_type.as_str(),
        "data": data.clone(),
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
        .map_err(|e| e.to_string())?;

    if let Some(writer) = app.agent_event_writer.as_ref() {
        let message_id = data.get("message_id").and_then(Value::as_str);
        let db_counter = i32::try_from(counter).unwrap_or(i32::MAX);
        writer
            .insert_event(AgentExecutionEventInsertRecord {
                id: &event_id,
                conversation_id,
                message_id,
                event_type: event_type.as_str(),
                event_data: &data,
                event_time_us,
                event_counter: db_counter,
                correlation_id: message_id.or(Some(conversation_id)),
            })
            .await
            .map_err(|e| e.to_string())?;
    }

    Ok(())
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

    #[test]
    fn run_session_id_is_message_scoped_when_available() {
        assert_eq!(
            agent_run_session_id("conversation-1", Some("message-1")),
            "conversation-1:message-1"
        );
        assert!(agent_run_session_id("conversation-1", None).starts_with("conversation-1:"));
    }

    #[test]
    fn copies_structured_tool_display_metadata() {
        let source = json!({
            "display": {"title": "Read file", "summary": "Inspect source"},
            "metadata": {
                "fileMetadata": {
                    "operation": "read",
                    "paths": [{"path": "/tmp/example.rs", "lineCount": 12}]
                }
            }
        });
        let mut target = Map::new();

        copy_tool_metadata(&mut target, &source);

        assert_eq!(target["display"]["title"], "Read file");
        assert_eq!(target["fileMetadata"]["operation"], "read");
        assert_eq!(target["fileMetadata"]["paths"][0]["lineCount"], 12);
    }

    #[test]
    fn error_event_data_keeps_run_scope() {
        let data = agent_error_event_data("c1", "p1", Some("m1"), "boom");

        assert_eq!(data["conversation_id"], "c1");
        assert_eq!(data["project_id"], "p1");
        assert_eq!(data["message_id"], "m1");
        assert_eq!(data["error"], "boom");
        assert_eq!(data["is_error"], true);
    }

    #[test]
    fn parses_python_hitl_response_messages() {
        let clarification: ClientMessage = serde_json::from_value(json!({
            "type": "clarification_respond",
            "request_id": "req1",
            "answer": "yes",
        }))
        .unwrap();
        assert!(matches!(
            clarification,
            ClientMessage::ClarificationRespond { .. }
        ));

        let permission: ClientMessage = serde_json::from_value(json!({
            "type": "permission_respond",
            "request_id": "req2",
            "granted": true,
        }))
        .unwrap();
        assert!(matches!(
            permission,
            ClientMessage::PermissionRespond { .. }
        ));
    }
}
