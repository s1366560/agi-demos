use std::{sync::Arc, time::Duration};

use axum::{extract::State, http::HeaderMap, Json};
use serde_json::{json, Value};
use tokio::sync::broadcast;
use uuid::Uuid;

use super::{
    authorize, bad_request, claim_request, conflict,
    contracts::{PlanDispatchRequest, ProviderMethod, ProviderWebhookRequest},
    ensure_workspace_scope, not_found,
    registry::ensure_agent_available,
    store_error, BridgeResult, RequestClaim, TokenKind, WorkspaceCoreAuthority,
};
use crate::local_runtime::{
    now_iso, session_store::DesktopWorkspaceCoreTerminalCallback, ConversationCapabilityMode,
    ConversationRunMode, LocalConversation, LocalRuntimeState,
};

const WORKSPACE_PROVIDER_ID: &str = "memstack-workspace-agent-runtime";
const PLAN_PROVIDER_ID: &str = "memstack-agent-runtime";
const DEFAULT_AGENT_ID: &str = "builtin:all-access";
const MAX_PROVIDER_TIMEOUT_MS: u64 = 3_600_000;
const MAX_HISTORY_LIMIT: u64 = 200;
const DEFAULT_HISTORY_LIMIT: u64 = 50;

pub(super) async fn webhook(
    State(state): State<Arc<LocalRuntimeState>>,
    headers: HeaderMap,
    Json(request): Json<ProviderWebhookRequest>,
) -> BridgeResult {
    let authority = authorize(&state, &headers, TokenKind::Provider)?;
    validate_provider_request(&request)?;
    ensure_workspace_scope(
        &state,
        &request.extensions.tenant_id,
        &request.extensions.project_id,
        &request.extensions.workspace_id,
    )?;
    match request.method {
        ProviderMethod::Send => send(state, authority, request).await,
        ProviderMethod::Inject => inject(&state, &request),
        ProviderMethod::Abort => abort(&state, &request),
        ProviderMethod::History => history(&state, &request),
    }
}

pub(super) async fn dispatch_plan(
    State(state): State<Arc<LocalRuntimeState>>,
    headers: HeaderMap,
    Json(request): Json<PlanDispatchRequest>,
) -> BridgeResult {
    authorize(&state, &headers, TokenKind::Provider)?;
    validate_plan_dispatch(&request)?;
    ensure_workspace_scope(
        &state,
        &request.tenant_id,
        &request.project_id,
        &request.workspace_id,
    )?;
    let agent_id = request.agent_id.as_deref().unwrap_or(DEFAULT_AGENT_ID);
    ensure_agent_available(&state, &request.project_id, agent_id)?;
    ensure_conversation(
        &state,
        &request.conversation_id,
        &request.tenant_id,
        &request.project_id,
        &request.workspace_id,
    )?;
    let provider_run_id = Uuid::new_v5(
        &Uuid::NAMESPACE_URL,
        format!("memstack-workspace-plan:{}", request.outbox_id).as_bytes(),
    )
    .to_string();
    let response = json!({
        "accepted": true,
        "provider_id": PLAN_PROVIDER_ID,
        "provider_bot_ref": agent_id,
        "provider_run_id": provider_run_id
    });
    if let RequestClaim::Duplicate(response) = claim_request(
        &state,
        &request.outbox_id,
        "plan_dispatch",
        &request,
        &response,
    )? {
        return Ok(Json(response));
    }
    let message = format!(
        "Execute the structured Workspace Plan runtime action.\n\nAction: {}\nPlan: {}\n\
         Node: {}\nTask: {}\nAttempt: {}\nCorrelation: {}\nPayload: {}",
        request.action.as_str(),
        request.plan_id,
        request.plan_node_id.as_deref().unwrap_or("none"),
        request.task_id.as_deref().unwrap_or("none"),
        request.attempt_id.as_deref().unwrap_or("none"),
        request.correlation_id,
        request.payload
    );
    let runtime = Arc::clone(&state);
    let conversation_id = request.conversation_id;
    let project_id = request.project_id;
    let message_id = provider_run_id;
    tokio::spawn(async move {
        runtime
            .run_agent_message_for_role(
                conversation_id,
                project_id,
                message,
                message_id,
                None,
                None,
                None,
            )
            .await;
    });
    Ok(Json(response))
}

async fn send(
    state: Arc<LocalRuntimeState>,
    authority: Arc<WorkspaceCoreAuthority>,
    request: ProviderWebhookRequest,
) -> BridgeResult {
    ensure_agent_available(
        &state,
        &request.extensions.project_id,
        &request.to_bot.provider_bot_ref,
    )?;
    ensure_conversation(
        &state,
        &request.extensions.conversation_id,
        &request.extensions.tenant_id,
        &request.extensions.project_id,
        &request.extensions.workspace_id,
    )?;
    let message = message_text(request.message.as_ref())?;
    let response = json!({ "ok": true });
    if let RequestClaim::Duplicate(response) =
        claim_request(&state, &request.id, "provider_send", &request, &response)?
    {
        return Ok(Json(response));
    }
    let mut events = state.events.subscribe();
    tokio::spawn(async move {
        drive_send(state, authority, request, message, &mut events).await;
    });
    Ok(Json(response))
}

fn inject(state: &LocalRuntimeState, request: &ProviderWebhookRequest) -> BridgeResult {
    let conversation = scoped_conversation(state, request)?;
    let content = message_text(request.message.as_ref())?;
    let response = json!({ "ok": true });
    if let RequestClaim::Duplicate(response) =
        claim_request(state, &request.id, "provider_inject", request, &response)?
    {
        return Ok(Json(response));
    }
    let item = state.timeline_item(
        "avernet_context_injection",
        conversation.id.clone(),
        Some(request.id.clone()),
        Some("system"),
        Some(content),
        json!({ "provider_request_id": request.id }),
    );
    state.append_timeline(&conversation.id, item);
    Ok(Json(response))
}

fn abort(state: &LocalRuntimeState, request: &ProviderWebhookRequest) -> BridgeResult {
    let conversation = scoped_conversation(state, request)?;
    let control = state
        .agent_runs
        .lock()
        .expect("local agent runs")
        .get(&conversation.id)
        .map(|active| Arc::clone(&active.control));
    let local_worker_cancelled = control.is_some();
    let response = json!({
        "ok": true,
        "aborted": local_worker_cancelled,
        "ray_cancelled": false,
        "local_worker_cancelled": local_worker_cancelled
    });
    if let RequestClaim::Duplicate(response) =
        claim_request(state, &request.id, "provider_abort", request, &response)?
    {
        return Ok(Json(response));
    }
    if let Some(control) = control {
        control.request_cancel();
        let item = state.timeline_item(
            "provider_aborted",
            conversation.id.clone(),
            Some(request.id.clone()),
            None,
            Some("Workspace Core requested cancellation".to_string()),
            json!({ "provider_request_id": request.id }),
        );
        state.append_timeline(&conversation.id, item);
    }
    Ok(Json(response))
}

fn history(state: &LocalRuntimeState, request: &ProviderWebhookRequest) -> BridgeResult {
    let conversation = scoped_conversation(state, request)?;
    let limit = request.limit.unwrap_or(DEFAULT_HISTORY_LIMIT);
    if !(1..=MAX_HISTORY_LIMIT).contains(&limit)
        || request.before.is_some() && request.after.is_some()
    {
        return Err(bad_request("Provider history cursor is invalid"));
    }
    let mut messages = state
        .session_store
        .timeline(&conversation.id, 500)
        .map_err(store_error)?
        .into_iter()
        .filter(|item| {
            matches!(
                item.get("type").and_then(Value::as_str),
                Some("user_message" | "assistant_message" | "avernet_context_injection")
            )
        })
        .filter(|item| {
            let cursor = item
                .get("eventCounter")
                .and_then(Value::as_u64)
                .or_else(|| item.get("event_counter").and_then(Value::as_u64))
                .unwrap_or(0);
            request.before.map_or(true, |before| cursor < before)
                && request.after.map_or(true, |after| cursor > after)
        })
        .collect::<Vec<_>>();
    let limit =
        usize::try_from(limit).map_err(|_| bad_request("Provider history limit is invalid"))?;
    let has_more = messages.len() > limit;
    messages.truncate(limit);
    let next_before = messages.first().and_then(event_cursor);
    let next_after = messages.last().and_then(event_cursor);
    Ok(Json(json!({
        "ok": true,
        "session_id": request.session_id,
        "messages": messages,
        "has_more": has_more,
        "next_before": next_before,
        "next_after": next_after
    })))
}

async fn drive_send(
    state: Arc<LocalRuntimeState>,
    authority: Arc<WorkspaceCoreAuthority>,
    request: ProviderWebhookRequest,
    message: String,
    events: &mut broadcast::Receiver<Value>,
) {
    let conversation_id = request.extensions.conversation_id.clone();
    let runtime = Arc::clone(&state);
    let run_conversation_id = conversation_id.clone();
    let project_id = request.extensions.project_id.clone();
    let message_id = request
        .extensions
        .bcs_message_id
        .clone()
        .unwrap_or_else(|| request.id.clone());
    let mut execution = tokio::spawn(async move {
        runtime
            .run_agent_message_for_role(
                run_conversation_id,
                project_id,
                message,
                message_id,
                None,
                None,
                None,
            )
            .await;
    });
    let deadline = tokio::time::sleep(Duration::from_millis(request.timeout_ms));
    tokio::pin!(deadline);
    let mut sequence = 0_u64;
    loop {
        tokio::select! {
            received = events.recv() => match received {
                Ok(item) if item["conversation_id"] == conversation_id => {
                    if let Some((state_name, terminal)) = callback_state(&item) {
                        sequence = sequence.saturating_add(1);
                        if let Err(error) = publish_event(
                            &state,
                            &authority,
                            &request,
                            &item,
                            state_name,
                            sequence,
                            terminal,
                        ).await {
                            tracing::error!(
                                run_id = %request.id,
                                error = %error,
                                "Workspace Core provider callback failed"
                            );
                        }
                        if terminal {
                            return;
                        }
                    }
                }
                Ok(_) => {}
                Err(broadcast::error::RecvError::Lagged(_)) => {}
                Err(broadcast::error::RecvError::Closed) => {
                    persist_bridge_error(&state, &conversation_id, "Local event stream closed");
                    return;
                }
            },
            _ = &mut execution => {
                while let Ok(item) = events.try_recv() {
                    if item["conversation_id"] == conversation_id {
                        if let Some((state_name, terminal)) = callback_state(&item) {
                            sequence = sequence.saturating_add(1);
                            let _ = publish_event(
                                &state,
                                &authority,
                                &request,
                                &item,
                                state_name,
                                sequence,
                                terminal
                            ).await;
                            if terminal {
                                return;
                            }
                        }
                    }
                }
                let item = persist_bridge_error(
                    &state,
                    &conversation_id,
                    "Local Agent ended without a terminal timeline event",
                );
                let _ = publish_event(
                    &state,
                    &authority,
                    &request,
                    &item,
                    "error",
                    sequence.saturating_add(1),
                    true
                ).await;
                return;
            },
            () = &mut deadline => {
                if let Some(control) = state
                    .agent_runs
                    .lock()
                    .expect("local agent runs")
                    .get(&conversation_id)
                    .map(|active| Arc::clone(&active.control))
                {
                    control.request_cancel();
                }
                let item = persist_bridge_error(
                    &state,
                    &conversation_id,
                    "Workspace Core provider request timed out",
                );
                let _ = publish_event(
                    &state,
                    &authority,
                    &request,
                    &item,
                    "error",
                    sequence.saturating_add(1),
                    true
                ).await;
                return;
            }
        }
    }
}

async fn publish_event(
    runtime: &LocalRuntimeState,
    authority: &WorkspaceCoreAuthority,
    request: &ProviderWebhookRequest,
    item: &Value,
    state: &str,
    sequence: u64,
    terminal: bool,
) -> Result<(), String> {
    let text = event_text(item, state);
    let message = (!text.is_empty()).then(|| {
        json!({
            "content": [{ "type": "text", "text": text }]
        })
    });
    let payload = json!({
        "run_id": request.id,
        "seq": sequence,
        "event": "chat",
        "message": { "text": text },
        "payload": {
            "run_id": request.id,
            "bcs_group_id": request.bcn_group_id,
            "state": state,
            "message": message,
            "delta_text": (state == "delta").then_some(text.clone()),
            "errorMessage": (state == "error").then_some(text.clone()),
            "extensions": request.extensions.callback_value()
        }
    });
    if !terminal {
        let status =
            send_callback_once(authority, &payload, &request.to_bot.provider_bot_ref).await?;
        return if (200..300).contains(&status) {
            Ok(())
        } else {
            Err(format!("Workspace Core callback returned status {status}"))
        };
    }
    let callback = DesktopWorkspaceCoreTerminalCallback {
        id: Uuid::new_v5(
            &Uuid::NAMESPACE_URL,
            format!("memstack-workspace-terminal:{}:{sequence}", request.id).as_bytes(),
        )
        .to_string(),
        run_id: request.id.clone(),
        sequence,
        provider_bot_ref: request.to_bot.provider_bot_ref.clone(),
        payload,
        created_at: now_iso(),
        attempt_count: 0,
        last_attempt_at: None,
        last_error: None,
    };
    runtime
        .session_store
        .enqueue_workspace_core_terminal_callback(&callback)?;
    deliver_terminal_callback(runtime, authority, &callback).await
}

pub(super) async fn replay_pending_terminal_callbacks(
    state: Arc<LocalRuntimeState>,
) -> Result<usize, String> {
    let authority = state
        .workspace_core_authority
        .lock()
        .map_err(|_| "Workspace Core authority lock is unavailable".to_string())?
        .clone()
        .ok_or_else(|| "Workspace Core authority is unavailable".to_string())?;
    let callbacks = state
        .session_store
        .pending_workspace_core_terminal_callbacks(1_000)?;
    let mut delivered = 0_usize;
    let mut last_error = None;
    for callback in callbacks {
        match deliver_terminal_callback(&state, &authority, &callback).await {
            Ok(()) => delivered = delivered.saturating_add(1),
            Err(error) => {
                tracing::error!(
                    callback_id = %callback.id,
                    run_id = %callback.run_id,
                    error = %error,
                    "Workspace Core terminal callback replay failed"
                );
                last_error = Some(error);
            }
        }
    }
    match last_error {
        Some(error) => Err(error),
        None => Ok(delivered),
    }
}

async fn deliver_terminal_callback(
    runtime: &LocalRuntimeState,
    authority: &WorkspaceCoreAuthority,
    callback: &DesktopWorkspaceCoreTerminalCallback,
) -> Result<(), String> {
    const ATTEMPTS: usize = 3;
    for attempt in 0..ATTEMPTS {
        let result =
            send_callback_once(authority, &callback.payload, &callback.provider_bot_ref).await;
        match result {
            Ok(status) if (200..300).contains(&status) || status == 410 => {
                return runtime
                    .session_store
                    .mark_workspace_core_terminal_callback_delivered(&callback.id, &now_iso());
            }
            Ok(status) => {
                let error = format!("Workspace Core callback returned status {status}");
                runtime
                    .session_store
                    .record_workspace_core_terminal_callback_failure(
                        &callback.id,
                        &now_iso(),
                        &error,
                    )?;
                if attempt + 1 == ATTEMPTS {
                    return Err(error);
                }
            }
            Err(error) => {
                runtime
                    .session_store
                    .record_workspace_core_terminal_callback_failure(
                        &callback.id,
                        &now_iso(),
                        &error,
                    )?;
                if attempt + 1 == ATTEMPTS {
                    return Err(error);
                }
            }
        }
        let multiplier = 1_u64 << attempt;
        tokio::time::sleep(Duration::from_millis(250_u64.saturating_mul(multiplier))).await;
    }
    Err("Workspace Core callback retry budget exhausted".to_string())
}

async fn send_callback_once(
    authority: &WorkspaceCoreAuthority,
    payload: &Value,
    provider_bot_ref: &str,
) -> Result<u16, String> {
    let mut request_builder = authority
        .client
        .post(format!("{}/bot/events", authority.core_api_base_url))
        .bearer_auth(authority.provider_event_token.as_str())
        .header("bcn-provider-id", WORKSPACE_PROVIDER_ID)
        .json(payload);
    if !provider_bot_ref.is_empty() {
        request_builder = request_builder.header("bcn-provider-bot-ref", provider_bot_ref);
    }
    request_builder
        .send()
        .await
        .map(|response| response.status().as_u16())
        .map_err(|error| format!("Workspace Core callback failed: {error}"))
}

fn validate_provider_request(request: &ProviderWebhookRequest) -> Result<(), super::BridgeError> {
    if request.frame_type != "req"
        || !identifier(&request.id, 512)
        || !identifier(&request.session_id, 512)
        || !identifier(&request.bcn_group_id, 512)
        || request.to_bot.provider_id != WORKSPACE_PROVIDER_ID
        || !identifier(&request.to_bot.provider_bot_ref, 128)
        || !(1..=MAX_PROVIDER_TIMEOUT_MS).contains(&request.timeout_ms)
        || !request.attachments.is_empty()
    {
        return Err(bad_request("Provider request is invalid or unsupported"));
    }
    for value in [
        &request.extensions.tenant_id,
        &request.extensions.project_id,
        &request.extensions.workspace_id,
        &request.extensions.user_id,
        &request.extensions.conversation_id,
    ] {
        if !identifier(value, 512) {
            return Err(bad_request("Provider scope is invalid"));
        }
    }
    Ok(())
}

fn validate_plan_dispatch(request: &PlanDispatchRequest) -> Result<(), super::BridgeError> {
    for value in [
        &request.tenant_id,
        &request.project_id,
        &request.workspace_id,
        &request.plan_id,
        &request.outbox_id,
        &request.correlation_id,
        &request.conversation_id,
    ] {
        if !identifier(value, 512) {
            return Err(bad_request("Workspace Plan dispatch identifier is invalid"));
        }
    }
    for value in [
        request.plan_node_id.as_deref(),
        request.task_id.as_deref(),
        request.attempt_id.as_deref(),
        request.agent_id.as_deref(),
    ] {
        if value.is_some_and(|value| !identifier(value, 512)) {
            return Err(bad_request(
                "Workspace Plan dispatch association is invalid",
            ));
        }
    }
    if !request.payload.is_object() {
        return Err(bad_request(
            "Workspace Plan dispatch payload must be an object",
        ));
    }
    Ok(())
}

fn ensure_conversation(
    state: &LocalRuntimeState,
    conversation_id: &str,
    tenant_id: &str,
    project_id: &str,
    workspace_id: &str,
) -> Result<LocalConversation, super::BridgeError> {
    if let Some(conversation) = state
        .session_store
        .conversation(conversation_id)
        .map_err(store_error)?
    {
        if conversation.tenant_id != tenant_id
            || conversation.project_id != project_id
            || conversation.workspace_id.as_deref() != Some(workspace_id)
        {
            return Err(conflict("Conversation scope conflicts with Workspace Core"));
        }
        return Ok(conversation);
    }
    let conversation = LocalConversation {
        id: conversation_id.to_string(),
        project_id: project_id.to_string(),
        tenant_id: tenant_id.to_string(),
        title: format!("Workspace Agent {conversation_id}"),
        workspace_id: Some(workspace_id.to_string()),
        capability_mode: ConversationCapabilityMode::Code,
        current_mode: ConversationRunMode::Plan,
        created_at: now_iso(),
        updated_at: now_iso(),
    };
    state
        .session_store
        .insert_conversation(&conversation)
        .map_err(store_error)?;
    Ok(conversation)
}

fn scoped_conversation(
    state: &LocalRuntimeState,
    request: &ProviderWebhookRequest,
) -> Result<LocalConversation, super::BridgeError> {
    let conversation = state
        .session_store
        .conversation(&request.extensions.conversation_id)
        .map_err(store_error)?
        .ok_or_else(|| not_found("Conversation not found"))?;
    if conversation.tenant_id != request.extensions.tenant_id
        || conversation.project_id != request.extensions.project_id
        || conversation.workspace_id.as_deref() != Some(&request.extensions.workspace_id)
    {
        return Err(super::forbidden(
            "Conversation is outside the trusted Workspace Core scope",
        ));
    }
    Ok(conversation)
}

fn message_text(message: Option<&Value>) -> Result<String, super::BridgeError> {
    let text = match message {
        Some(Value::String(value)) => value.clone(),
        Some(Value::Object(value)) => value
            .get("content")
            .and_then(Value::as_str)
            .or_else(|| value.get("text").and_then(Value::as_str))
            .map(ToString::to_string)
            .or_else(|| {
                value
                    .get("content")
                    .and_then(Value::as_array)
                    .map(|blocks| {
                        blocks
                            .iter()
                            .filter_map(|block| block.get("text").and_then(Value::as_str))
                            .collect::<Vec<_>>()
                            .join("\n")
                    })
            })
            .unwrap_or_default(),
        _ => String::new(),
    };
    if text.trim().is_empty() || text.len() > 1_000_000 {
        Err(bad_request("Provider message must contain bounded text"))
    } else {
        Ok(text)
    }
}

fn callback_state(item: &Value) -> Option<(&'static str, bool)> {
    match item.get("type").and_then(Value::as_str) {
        Some("act") => Some(("tool_call_start", false)),
        Some("observe") => Some(("tool_call_end", false)),
        Some("assistant_message") => Some(("final", true)),
        Some("error") => Some(("error", true)),
        Some("provider_aborted") => Some(("aborted", true)),
        _ => None,
    }
}

fn event_text(item: &Value, state: &str) -> String {
    let text = item
        .get("content")
        .and_then(Value::as_str)
        .or_else(|| item.pointer("/data/content").and_then(Value::as_str))
        .or_else(|| item.pointer("/payload/error").and_then(Value::as_str))
        .unwrap_or_default();
    if state == "final" && text.trim().is_empty() {
        "Agent completed without a textual response".to_string()
    } else {
        text.to_string()
    }
}

fn persist_bridge_error(state: &LocalRuntimeState, conversation_id: &str, message: &str) -> Value {
    let item = state.timeline_item(
        "error",
        conversation_id.to_string(),
        None,
        None,
        Some(message.to_string()),
        json!({ "error": message }),
    );
    state.append_timeline(conversation_id, item.clone());
    item
}

fn event_cursor(item: &Value) -> Option<u64> {
    item.get("eventCounter")
        .and_then(Value::as_u64)
        .or_else(|| item.get("event_counter").and_then(Value::as_u64))
}

fn identifier(value: &str, maximum: usize) -> bool {
    !value.is_empty() && value == value.trim() && value.len() <= maximum
}
