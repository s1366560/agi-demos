use std::{sync::Arc, time::Duration};

use axum::{extract::State, http::HeaderMap, Json};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use tokio::sync::broadcast;
use uuid::Uuid;

use super::{
    authorize, bad_request, claim_request, conflict,
    contracts::{PlanDispatchRequest, ProviderMethod, ProviderWebhookRequest},
    ensure_workspace_scope, not_found,
    registry::ensure_agent_available,
    store_error, unavailable, workspace_policy, BridgeResult, RequestClaim, TokenKind,
    WorkspaceCoreAuthority,
};
use crate::local_runtime::{
    authority_store::{is_recovered_unstarted_run, DesktopRun, DesktopRunStatus},
    now_iso, routing_targets_for_role,
    session_store::DesktopWorkspaceCoreTerminalCallback,
    workspace_task_run::{
        ProjectWorkspaceTaskRunError, ProjectWorkspaceTaskRunInput, ProjectWorkspaceTaskRunOutcome,
    },
    workspace_terminal_recovery::RecoveredWorkspaceTaskTerminal,
    ConversationCapabilityMode, ConversationRunMode, LlmWorkloadRole, LocalConversation,
    LocalRunControl, LocalRuntimeState,
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
    if request.extensions.task_id.is_some() {
        return send_workspace_task(state, authority, request).await;
    }
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
        drive_send(state, authority, request, message, None, None, &mut events).await;
    });
    Ok(Json(response))
}

async fn send_workspace_task(
    state: Arc<LocalRuntimeState>,
    authority: Arc<WorkspaceCoreAuthority>,
    request: ProviderWebhookRequest,
) -> BridgeResult {
    let message = message_text(request.message.as_ref())?;
    let task_id = required_task_extension(request.extensions.task_id.as_deref(), "task_id")?;
    let delivery_request_id = required_task_extension(
        request.extensions.delivery_request_id.as_deref(),
        "delivery_request_id",
    )?;
    // First dispatch arrives without an attempt id (see validation above):
    // derive a deterministic one from the delivery request id so idempotent
    // redelivery replays the same attempt instead of minting a new one.
    let attempt_id = request
        .extensions
        .attempt_id
        .as_deref()
        .map(str::to_string)
        .unwrap_or_else(|| format!("attempt-{delivery_request_id}"));
    let workspace_agent_binding_id = required_task_extension(
        request.extensions.workspace_agent_binding_id.as_deref(),
        "workspace_agent_binding_id",
    )?;
    if delivery_request_id != request.id {
        return Err(bad_request(
            "Workspace Task delivery_request_id must match the Provider request id",
        ));
    }
    let policy = workspace_policy(
        &state,
        &request.extensions.tenant_id,
        &request.extensions.project_id,
        &request.extensions.workspace_id,
    )
    .await?;
    let llm_route = routing_targets_for_role(&policy, LlmWorkloadRole::Coding)
        .map_err(|_| unavailable("Workspace Task LLM routing policy is invalid"))?
        .into_iter()
        .next()
        // A workspace without explicit routing falls back to the tenant-level
        // runtime default (explicit selection, or the sole active binding in
        // local mode), mirroring llm_for_policy's fallback for agent runs.
        .or_else(|| state.selected_provider_route(&request.extensions.tenant_id))
        .ok_or_else(|| unavailable("Workspace Task LLM routing policy is unconfigured"))?;
    #[cfg(test)]
    if state
        .mock_llm_enabled
        .load(std::sync::atomic::Ordering::Acquire)
        == 0
    {
        state
            .validate_conversation_llm_route(&request.extensions.tenant_id, &llm_route)
            .map_err(|_| unavailable("Workspace Task LLM route is unavailable"))?;
    }
    #[cfg(not(test))]
    state
        .validate_conversation_llm_route(&request.extensions.tenant_id, &llm_route)
        .map_err(|_| unavailable("Workspace Task LLM route is unavailable"))?;
    let request_payload = serde_json::to_value(&request)
        .map_err(|_| bad_request("Workspace Task Provider request cannot be encoded"))?;
    let request_hash = provider_request_hash(&request)?;
    // Workspace task runs execute tools under WorkspaceWrite; they need a
    // prepared execution environment just like conversation runs, otherwise
    // every tool call fails with "authorized run has no execution
    // environment" and the agent can only escalate a spurious env_var HITL.
    let environment = state
        .worktree_manager()
        .prepare(
            crate::local_runtime::DesktopExecutionEnvironmentKind::Local,
            &format!("workspace-task-environment-{}", request.id),
            &now_iso(),
        )
        .map_err(|error| {
            unavailable(&format!(
                "Workspace Task execution environment is unavailable: {error}"
            ))
        })?
        .environment;
    let outcome = state
        .session_store
        .project_workspace_task_run(ProjectWorkspaceTaskRunInput {
            request_id: request.id.clone(),
            request_hash,
            request_payload,
            tenant_id: request.extensions.tenant_id.clone(),
            project_id: request.extensions.project_id.clone(),
            workspace_id: request.extensions.workspace_id.clone(),
            user_id: request.extensions.user_id.clone(),
            task_id: task_id.to_string(),
            attempt_id: attempt_id.to_string(),
            plan_id: request.extensions.plan_id.clone(),
            plan_node_id: request.extensions.plan_node_id.clone(),
            workspace_agent_binding_id: workspace_agent_binding_id.to_string(),
            agent_id: request.to_bot.provider_bot_ref.clone(),
            conversation_id: request.extensions.conversation_id.clone(),
            message: message.clone(),
            llm_route,
            environment: Some(environment),
            now: now_iso(),
        })
        .map_err(workspace_task_projection_error)?;
    launch_workspace_task_run(&state, authority, request, message, &outcome)?;
    Ok(Json(outcome.response))
}

fn launch_workspace_task_run(
    state: &Arc<LocalRuntimeState>,
    authority: Arc<WorkspaceCoreAuthority>,
    request: ProviderWebhookRequest,
    message: String,
    outcome: &ProjectWorkspaceTaskRunOutcome,
) -> Result<bool, super::BridgeError> {
    let run = &outcome.run;
    let launchable = run.status == DesktopRunStatus::Queued || is_recovered_unstarted_run(run);
    if !launchable {
        return Ok(false);
    }
    if state.control_for_run(run).is_some() {
        return Ok(false);
    }
    let Some(control) = state.claim_agent_run(&run.conversation_id, Some(&run.id)) else {
        return Err(conflict(
            "Workspace Task conversation already has another active run",
        ));
    };
    state.publish_run_status(run);
    let mut events = state.events.subscribe();
    let runtime = Arc::clone(state);
    let run = run.clone();
    tokio::spawn(async move {
        drive_send(
            runtime,
            authority,
            request,
            message,
            Some(run),
            Some(control),
            &mut events,
        )
        .await;
    });
    Ok(true)
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
    authoritative_run: Option<DesktopRun>,
    claimed_control: Option<Arc<LocalRunControl>>,
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
    let authoritative_run_id = authoritative_run.as_ref().map(|run| run.id.clone());
    let mut execution = tokio::spawn(async move {
        runtime
            .run_agent_message_for_role(
                run_conversation_id,
                project_id,
                message,
                message_id,
                None,
                authoritative_run_id,
                claimed_control,
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
    let sequence = if terminal && request.extensions.task_id.is_some() {
        event_cursor(item).ok_or_else(|| {
            "Workspace Task terminal timeline item is missing its durable sequence".to_string()
        })?
    } else {
        sequence
    };
    let provider_event = provider_event(request, state, sequence, &text, message);
    if !terminal {
        let payload = provider_callback_payload(request, sequence, &text, provider_event);
        let status =
            send_callback_once(authority, &payload, &request.to_bot.provider_bot_ref).await?;
        return if (200..300).contains(&status) {
            Ok(())
        } else {
            Err(format!("Workspace Core callback returned status {status}"))
        };
    }
    let callback = terminal_callback(request, item, state, sequence, &text, provider_event)?;
    runtime
        .session_store
        .enqueue_workspace_core_terminal_callback(&callback)?;
    deliver_terminal_callback(runtime, authority, &callback).await
}

fn provider_event(
    request: &ProviderWebhookRequest,
    state: &str,
    sequence: u64,
    text: &str,
    message: Option<Value>,
) -> Value {
    json!({
        "run_id": request.id,
        "bcs_group_id": request.bcn_group_id,
        "seq": sequence,
        "state": state,
        "message": message,
        "delta_text": (state == "delta").then_some(text),
        "errorMessage": (state == "error").then_some(text),
        "extensions": request.extensions.callback_value()
    })
}

fn provider_callback_payload(
    request: &ProviderWebhookRequest,
    sequence: u64,
    text: &str,
    provider_event: Value,
) -> Value {
    json!({
        "run_id": request.id,
        "seq": sequence,
        "event": "chat",
        "message": { "text": text },
        "payload": provider_event,
    })
}

fn terminal_callback(
    request: &ProviderWebhookRequest,
    item: &Value,
    state: &str,
    sequence: u64,
    text: &str,
    provider_event: Value,
) -> Result<DesktopWorkspaceCoreTerminalCallback, String> {
    let terminal_event_id = deterministic_terminal_event_id(&request.id, sequence);
    let terminal_message_id = deterministic_terminal_message_id(&request.id, sequence);
    let mut terminal_provider_event = provider_event.clone();
    let terminal_payload = terminal_provider_event.as_object_mut().ok_or_else(|| {
        "Workspace Task terminal Provider event must be a JSON object".to_string()
    })?;
    terminal_payload.insert(
        "terminal_message_id".to_string(),
        json!(terminal_message_id),
    );
    terminal_payload.insert("terminal_event_id".to_string(), json!(terminal_event_id));
    terminal_payload.insert(
        "terminal_report".to_string(),
        json!({
            "provider_state": state,
            "sequence": sequence,
            "message_text": text,
            "provider_event": provider_event,
        }),
    );
    let event_time_us = item
        .get("event_time_us")
        .and_then(Value::as_i64)
        .ok_or_else(|| {
            "Workspace Task terminal timeline item is missing its durable timestamp".to_string()
        })?;
    Ok(DesktopWorkspaceCoreTerminalCallback {
        id: terminal_event_id,
        run_id: request.id.clone(),
        sequence,
        provider_bot_ref: request.to_bot.provider_bot_ref.clone(),
        payload: provider_callback_payload(request, sequence, text, terminal_provider_event),
        created_at: format!("timeline-{event_time_us:020}"),
        attempt_count: 0,
        last_attempt_at: None,
        last_error: None,
    })
}

fn deterministic_terminal_event_id(run_id: &str, sequence: u64) -> String {
    Uuid::new_v5(
        &Uuid::NAMESPACE_URL,
        format!("memstack-workspace-terminal:{run_id}:{sequence}").as_bytes(),
    )
    .to_string()
}

fn deterministic_terminal_message_id(run_id: &str, sequence: u64) -> String {
    Uuid::new_v5(
        &Uuid::NAMESPACE_URL,
        format!("memstack-workspace-terminal-message:{run_id}:{sequence}").as_bytes(),
    )
    .to_string()
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
    rebuild_missing_terminal_callbacks(&state)?;
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

fn rebuild_missing_terminal_callbacks(state: &LocalRuntimeState) -> Result<usize, String> {
    let recoveries = state
        .session_store
        .workspace_task_terminals_missing_callbacks()?;
    let mut rebuilt = 0_usize;
    for recovery in recoveries {
        let callback = recovered_terminal_callback(recovery)?;
        state
            .session_store
            .enqueue_workspace_core_terminal_callback(&callback)?;
        rebuilt = rebuilt.saturating_add(1);
    }
    Ok(rebuilt)
}

fn recovered_terminal_callback(
    recovery: RecoveredWorkspaceTaskTerminal,
) -> Result<DesktopWorkspaceCoreTerminalCallback, String> {
    let request: ProviderWebhookRequest = serde_json::from_value(recovery.request_payload)
        .map_err(|error| format!("recovered Workspace Task request is invalid: {error}"))?;
    validate_provider_request(&request)
        .map_err(|_| "recovered Workspace Task request authority is invalid".to_string())?;
    if request.id != recovery.run_id
        || request.extensions.conversation_id != recovery.conversation_id
    {
        return Err(
            "recovered Workspace Task terminal authority conflicts with its run".to_string(),
        );
    }
    let Some((state, true)) = callback_state(&recovery.terminal_item) else {
        return Err("recovered Workspace Task timeline item is not terminal".to_string());
    };
    let sequence = event_cursor(&recovery.terminal_item).ok_or_else(|| {
        "recovered Workspace Task terminal is missing its durable sequence".to_string()
    })?;
    let text = event_text(&recovery.terminal_item, state);
    let message = (!text.is_empty()).then(|| {
        json!({
            "content": [{ "type": "text", "text": text }]
        })
    });
    let provider_event = provider_event(&request, state, sequence, &text, message);
    terminal_callback(
        &request,
        &recovery.terminal_item,
        state,
        sequence,
        &text,
        provider_event,
    )
}

pub(super) async fn resume_recovered_workspace_task_runs(
    state: Arc<LocalRuntimeState>,
) -> Result<usize, String> {
    let authority = state
        .workspace_core_authority
        .lock()
        .map_err(|_| "Workspace Core authority lock is unavailable".to_string())?
        .clone()
        .ok_or_else(|| "Workspace Core authority is unavailable".to_string())?;
    let recovered = state.session_store.recovered_workspace_task_runs()?;
    let mut launched = 0_usize;
    for projection in recovered {
        let request: ProviderWebhookRequest = serde_json::from_value(projection.request_payload)
            .map_err(|error| format!("recovered Workspace Task request is invalid: {error}"))?;
        validate_provider_request(&request)
            .map_err(|_| "recovered Workspace Task request authority is invalid".to_string())?;
        ensure_agent_available(
            &state,
            &request.extensions.project_id,
            &request.to_bot.provider_bot_ref,
        )
        .map_err(|_| "recovered Workspace Task Agent is unavailable".to_string())?;
        if request.id != projection.run.id
            || request.extensions.conversation_id != projection.run.conversation_id
            || message_text(request.message.as_ref())
                .map_err(|_| "recovered Workspace Task message is invalid".to_string())?
                != projection.run.request_message
        {
            return Err("recovered Workspace Task authority conflicts with its run".to_string());
        }
        let message = projection.run.request_message.clone();
        let outcome = ProjectWorkspaceTaskRunOutcome {
            run: projection.run,
            response: json!({"ok": true, "provider_run_id": request.id}),
        };
        if launch_workspace_task_run(&state, Arc::clone(&authority), request, message, &outcome)
            .map_err(|_| "recovered Workspace Task launch is unavailable".to_string())?
        {
            launched = launched.saturating_add(1);
        }
    }
    Ok(launched)
}

async fn deliver_terminal_callback(
    runtime: &LocalRuntimeState,
    authority: &WorkspaceCoreAuthority,
    callback: &DesktopWorkspaceCoreTerminalCallback,
) -> Result<(), String> {
    const ATTEMPTS: usize = 3;
    for attempt in 0..ATTEMPTS {
        let result = deliver_terminal_attempt(authority, callback).await;
        match result {
            Ok(()) => {
                return runtime
                    .session_store
                    .mark_workspace_core_terminal_callback_delivered(&callback.id, &now_iso());
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

async fn deliver_terminal_attempt(
    authority: &WorkspaceCoreAuthority,
    callback: &DesktopWorkspaceCoreTerminalCallback,
) -> Result<(), String> {
    let Some(proof) = terminal_callback_proof(callback)? else {
        let status =
            send_callback_once(authority, &callback.payload, &callback.provider_bot_ref).await?;
        return successful_status("Provider callback", status);
    };
    let terminal_status = send_runtime_terminal_once(authority, &proof).await?;
    successful_status("Runtime terminal", terminal_status)?;
    let callback_status =
        send_callback_once(authority, &callback.payload, &callback.provider_bot_ref).await?;
    successful_status("Provider callback", callback_status)?;
    let acknowledgement_status = send_callback_ack_once(authority, &proof).await?;
    successful_status("Runtime callback acknowledgement", acknowledgement_status)
}

struct TerminalCallbackProof {
    correlation_id: String,
    tenant_id: String,
    project_id: String,
    workspace_id: String,
    execution_status: &'static str,
    terminal_message_id: String,
    terminal_event_id: String,
    report: Value,
}

fn terminal_callback_proof(
    callback: &DesktopWorkspaceCoreTerminalCallback,
) -> Result<Option<TerminalCallbackProof>, String> {
    let payload = callback
        .payload
        .get("payload")
        .and_then(Value::as_object)
        .ok_or_else(|| "Workspace Core terminal callback payload is invalid".to_string())?;
    let extensions = payload
        .get("extensions")
        .and_then(Value::as_object)
        .ok_or_else(|| "Workspace Core terminal callback extensions are invalid".to_string())?;
    if extensions.get("task_id").and_then(Value::as_str).is_none() {
        return Ok(None);
    }
    let required = |object: &serde_json::Map<String, Value>, field: &str| {
        object
            .get(field)
            .and_then(Value::as_str)
            .filter(|value| !value.trim().is_empty())
            .map(str::to_string)
            .ok_or_else(|| format!("Workspace Task terminal callback is missing {field}"))
    };
    let correlation_id = required(extensions, "delivery_request_id")?;
    let tenant_id = required(extensions, "tenant_id")?;
    let project_id = required(extensions, "project_id")?;
    let workspace_id = required(extensions, "workspace_id")?;
    let provider_state = required(payload, "state")?;
    let execution_status = match provider_state.as_str() {
        "final" => "complete",
        "error" => "error",
        "aborted" => "aborted",
        _ => return Err("Workspace Task terminal callback state is invalid".to_string()),
    };
    let terminal_message_id = required(payload, "terminal_message_id")?;
    let terminal_event_id = required(payload, "terminal_event_id")?;
    let report = payload
        .get("terminal_report")
        .cloned()
        .filter(Value::is_object)
        .ok_or_else(|| "Workspace Task terminal callback report is invalid".to_string())?;
    let sequence = payload
        .get("seq")
        .and_then(Value::as_u64)
        .ok_or_else(|| "Workspace Task terminal callback sequence is invalid".to_string())?;
    let message_text = callback
        .payload
        .pointer("/message/text")
        .and_then(Value::as_str)
        .ok_or_else(|| "Workspace Task terminal callback message is invalid".to_string())?;
    let mut provider_event = Value::Object(payload.clone());
    let provider_event_object = provider_event
        .as_object_mut()
        .expect("cloned Provider event object");
    provider_event_object.remove("terminal_message_id");
    provider_event_object.remove("terminal_event_id");
    provider_event_object.remove("terminal_report");
    let expected_report = json!({
        "provider_state": provider_state,
        "sequence": sequence,
        "message_text": message_text,
        "provider_event": provider_event,
    });
    if correlation_id != callback.run_id
        || callback.payload["run_id"].as_str() != Some(callback.run_id.as_str())
        || callback.payload["seq"].as_u64() != Some(callback.sequence)
        || sequence != callback.sequence
        || payload.get("run_id").and_then(Value::as_str) != Some(callback.run_id.as_str())
        || terminal_event_id != callback.id
        || terminal_event_id != deterministic_terminal_event_id(&callback.run_id, callback.sequence)
        || terminal_message_id
            != deterministic_terminal_message_id(&callback.run_id, callback.sequence)
        || report != expected_report
    {
        return Err("Workspace Task terminal callback proof is inconsistent".to_string());
    }
    Ok(Some(TerminalCallbackProof {
        correlation_id,
        tenant_id,
        project_id,
        workspace_id,
        execution_status,
        terminal_message_id,
        terminal_event_id,
        report,
    }))
}

async fn send_runtime_terminal_once(
    authority: &WorkspaceCoreAuthority,
    proof: &TerminalCallbackProof,
) -> Result<u16, String> {
    authority
        .client
        .post(format!(
            "{}/internal/v1/runtime-correlations/{}/terminal",
            authority.core_api_base_url, proof.correlation_id
        ))
        .bearer_auth(authority.service_token.as_str())
        .header("x-memstack-tenant-id", proof.tenant_id.as_str())
        .json(&json!({
            "project_id": proof.project_id,
            "workspace_id": proof.workspace_id,
            "execution_status": proof.execution_status,
            "terminal_message_id": proof.terminal_message_id,
            "terminal_event_id": proof.terminal_event_id,
            "report": proof.report,
        }))
        .send()
        .await
        .map(|response| response.status().as_u16())
        .map_err(|error| format!("Workspace Core Runtime terminal failed: {error}"))
}

async fn send_callback_ack_once(
    authority: &WorkspaceCoreAuthority,
    proof: &TerminalCallbackProof,
) -> Result<u16, String> {
    authority
        .client
        .post(format!(
            "{}/internal/v1/runtime-correlations/{}/callback-ack",
            authority.core_api_base_url, proof.correlation_id
        ))
        .bearer_auth(authority.service_token.as_str())
        .header("x-memstack-tenant-id", proof.tenant_id.as_str())
        .json(&json!({
            "project_id": proof.project_id,
            "workspace_id": proof.workspace_id,
        }))
        .send()
        .await
        .map(|response| response.status().as_u16())
        .map_err(|error| format!("Workspace Core callback acknowledgement failed: {error}"))
}

fn successful_status(stage: &str, status: u16) -> Result<(), String> {
    if (200..300).contains(&status) {
        Ok(())
    } else {
        Err(format!("Workspace Core {stage} returned status {status}"))
    }
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
        // Canonical protocol casing: the Workspace Core /bot/events handler
        // resolves these via &str HeaderMap lookups whose hashing is
        // case-sensitive for non-standard names, so a lowercase
        // `bcn-provider-id` is rejected as missing.
        .header("X-BCN-Provider-Id", WORKSPACE_PROVIDER_ID)
        .json(payload);
    if !provider_bot_ref.is_empty() {
        request_builder = request_builder.header("X-BCN-Provider-Bot-Ref", provider_bot_ref);
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
    if request.extensions.task_id.is_some() {
        for value in [
            request.extensions.task_id.as_deref(),
            request.extensions.workspace_agent_binding_id.as_deref(),
            request.extensions.delivery_request_id.as_deref(),
        ] {
            if value.map_or(true, |value| !identifier(value, 512)) {
                return Err(bad_request("Workspace Task Provider authority is invalid"));
            }
        }
        // The first dispatch of a Workspace task legitimately carries
        // `attempt_id: null` — the attempt is materialized by this runtime
        // when the run starts, and the core matches the runtime correlation
        // with a null-safe comparison. Only a present-but-malformed attempt
        // id is rejected here.
        if request
            .extensions
            .attempt_id
            .as_deref()
            .is_some_and(|value| !identifier(value, 512))
        {
            return Err(bad_request("Workspace Task Provider authority is invalid"));
        }
        for value in [
            request.extensions.plan_id.as_deref(),
            request.extensions.plan_node_id.as_deref(),
        ] {
            if value.is_some_and(|value| !identifier(value, 512)) {
                return Err(bad_request(
                    "Workspace Task Provider association is invalid",
                ));
            }
        }
        if request.extensions.delivery_request_id.as_deref() != Some(request.id.as_str()) {
            return Err(bad_request(
                "Workspace Task delivery_request_id must match the Provider request id",
            ));
        }
    }
    Ok(())
}

fn required_task_extension<'a>(
    value: Option<&'a str>,
    field: &str,
) -> Result<&'a str, super::BridgeError> {
    value
        .filter(|value| identifier(value, 512))
        .ok_or_else(|| bad_request(&format!("Workspace Task {field} is required")))
}

fn provider_request_hash(request: &ProviderWebhookRequest) -> Result<String, super::BridgeError> {
    let encoded = serde_json::to_vec(request)
        .map_err(|_| bad_request("Workspace Core request cannot be encoded"))?;
    Ok(Sha256::digest(encoded)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect())
}

fn workspace_task_projection_error(error: ProjectWorkspaceTaskRunError) -> super::BridgeError {
    match error {
        ProjectWorkspaceTaskRunError::PayloadConflict => {
            conflict("Workspace Core request id is already bound to another payload")
        }
        ProjectWorkspaceTaskRunError::AuthorityConflict => {
            conflict("Workspace Task execution authority conflicts with persisted state")
        }
        ProjectWorkspaceTaskRunError::InvalidRequest => {
            bad_request("Workspace Task execution request is invalid")
        }
        ProjectWorkspaceTaskRunError::AuthorityMissing => (
            axum::http::StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({
                "detail": "Workspace Task execution authority is incomplete",
                "reason_code": "workspace_task_authority_incomplete",
            })),
        ),
        ProjectWorkspaceTaskRunError::Storage(error) => store_error(error),
    }
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
