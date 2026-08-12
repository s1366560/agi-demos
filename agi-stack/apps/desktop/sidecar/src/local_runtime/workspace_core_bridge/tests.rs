use std::sync::{atomic::Ordering, Arc};

use agistack_adapters_device::SqliteCheckpointStore;
use agistack_adapters_local_tools::LocalToolHost;
use agistack_core::agent::react::{ReActControl, RunDirective};
use axum::{
    body::{to_bytes, Body},
    extract::State,
    http::{HeaderMap, Request, StatusCode},
    routing::post,
    Json, Router,
};
use serde_json::{json, Value};
use tokio::sync::{mpsc, Mutex};
use tower::ServiceExt;
use uuid::Uuid;

use super::*;
use crate::local_runtime::{
    local_router, now_iso, session_store::DesktopSessionStore, ConversationCapabilityMode,
    ConversationRunMode, LocalConversation, LocalRuntimeState,
};

fn state() -> Arc<LocalRuntimeState> {
    let root = std::env::temp_dir().join(format!("workspace-core-bridge-{}", Uuid::new_v4()));
    let tool_host = LocalToolHost::new(&root).expect("tool host");
    let checkpoints = Arc::new(SqliteCheckpointStore::in_memory().expect("checkpoints"));
    let session_store = DesktopSessionStore::in_memory().expect("session store");
    let state = Arc::new(
        LocalRuntimeState::new(
            root,
            tool_host,
            checkpoints,
            "launch-token".to_string(),
            session_store,
        )
        .expect("local runtime state"),
    );
    state
        .mock_llm_enabled
        .store(1, std::sync::atomic::Ordering::Release);
    state
}

async fn post_json(app: Router, path: &str, token: &str, body: Value) -> (StatusCode, Value) {
    let response = app
        .oneshot(
            Request::builder()
                .method("POST")
                .uri(path)
                .header(AUTHORIZATION, format!("Bearer {token}"))
                .header("content-type", "application/json")
                .body(Body::from(body.to_string()))
                .expect("request"),
        )
        .await
        .expect("response");
    let status = response.status();
    let body = to_bytes(response.into_body(), 1024 * 1024)
        .await
        .expect("response body");
    let value = if body.is_empty() {
        Value::Null
    } else {
        serde_json::from_slice(&body)
            .unwrap_or_else(|_| Value::String(String::from_utf8_lossy(&body).into_owned()))
    };
    (status, value)
}

fn install(state: &LocalRuntimeState, core_url: &str) -> u64 {
    install_authority(
        state,
        core_url.to_string(),
        "registry-token".to_string(),
        "provider-token".to_string(),
        "event-token".to_string(),
    )
    .expect("install authority")
}

fn agent_lookup(extra: Option<(&str, Value)>) -> Value {
    let mut body = json!({
        "tenant_id": "local",
        "project_id": "local-project",
        "agent_id": "builtin:all-access"
    });
    if let Some((name, value)) = extra {
        body[name] = value;
    }
    body
}

fn provider_request(id: &str, conversation_id: &str, method: &str) -> Value {
    json!({
        "type": "req",
        "id": id,
        "method": method,
        "session_id": "session-1",
        "bcn_group_id": "group-1",
        "to_bot": {
            "provider_id": "memstack-workspace-agent-runtime",
            "provider_bot_ref": "builtin:all-access"
        },
        "message": {
            "content": [{ "type": "text", "text": "hello from Workspace Core" }]
        },
        "timeout_ms": 30_000,
        "extensions": {
            "tenant_id": "local",
            "project_id": "local-project",
            "workspace_id": "local-workspace",
            "user_id": "local-user",
            "conversation_id": conversation_id,
            "task_id": "task-1",
            "plan_id": "plan-1",
            "plan_node_id": "node-1"
        }
    })
}

fn plan_dispatch_request(outbox_id: &str, conversation_id: &str) -> Value {
    json!({
        "tenant_id": "local",
        "project_id": "local-project",
        "workspace_id": "local-workspace",
        "plan_id": "plan-1",
        "plan_node_id": "node-1",
        "task_id": "task-1",
        "attempt_id": "attempt-1",
        "agent_id": "builtin:all-access",
        "action": "run_pipeline",
        "outbox_id": outbox_id,
        "correlation_id": "correlation-1",
        "conversation_id": conversation_id,
        "payload": { "objective": "verify plan dispatch" }
    })
}

fn insert_conversation(state: &LocalRuntimeState, conversation_id: &str) {
    let timestamp = now_iso();
    state
        .session_store
        .insert_conversation(&LocalConversation {
            id: conversation_id.to_string(),
            project_id: "local-project".to_string(),
            tenant_id: "local".to_string(),
            title: "Workspace Core bridge test".to_string(),
            workspace_id: Some("local-workspace".to_string()),
            capability_mode: ConversationCapabilityMode::Code,
            current_mode: ConversationRunMode::Plan,
            created_at: timestamp.clone(),
            updated_at: timestamp,
        })
        .expect("insert conversation");
}

#[tokio::test]
async fn registry_resolves_the_project_scoped_builtin_agent() {
    let state = state();
    install(&state, "http://127.0.0.1:21000");

    let (status, body) = post_json(
        router(state),
        "/internal/v1/workspace-core/agent-registry/resolve",
        "registry-token",
        agent_lookup(None),
    )
    .await;

    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["available"], true);
    assert_eq!(body["agent_id"], "builtin:all-access");
}

#[tokio::test]
async fn internal_authority_is_separate_from_launch_and_provider_tokens() {
    let state = state();
    install(&state, "http://127.0.0.1:21000");
    let app = local_router(state);

    let (registry_status, _) = post_json(
        app.clone(),
        "/internal/v1/workspace-core/agent-registry/resolve",
        "registry-token",
        agent_lookup(None),
    )
    .await;
    let (launch_status, _) = post_json(
        app.clone(),
        "/internal/v1/workspace-core/agent-registry/resolve",
        "launch-token",
        agent_lookup(None),
    )
    .await;
    let (provider_status, _) = post_json(
        app,
        "/internal/v1/workspace-core/agent-registry/resolve",
        "provider-token",
        agent_lookup(None),
    )
    .await;

    assert_eq!(registry_status, StatusCode::OK);
    assert_eq!(launch_status, StatusCode::UNAUTHORIZED);
    assert_eq!(provider_status, StatusCode::UNAUTHORIZED);
}

#[tokio::test]
async fn missing_authority_unknown_fields_and_cross_scope_fail_closed() {
    let state = state();
    let (missing_status, _) = post_json(
        router(Arc::clone(&state)),
        "/internal/v1/workspace-core/agent-registry/resolve",
        "registry-token",
        agent_lookup(None),
    )
    .await;
    install(&state, "http://127.0.0.1:21000");
    let (unknown_status, _) = post_json(
        router(Arc::clone(&state)),
        "/internal/v1/workspace-core/agent-registry/resolve",
        "registry-token",
        agent_lookup(Some(("unexpected", json!(true)))),
    )
    .await;
    let (scope_status, _) = post_json(
        router(state),
        "/internal/v1/workspace-core/agent-registry/resolve",
        "registry-token",
        json!({
            "tenant_id": "another-tenant",
            "project_id": "local-project",
            "agent_id": "builtin:all-access"
        }),
    )
    .await;

    assert_eq!(missing_status, StatusCode::SERVICE_UNAVAILABLE);
    assert_eq!(unknown_status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(scope_status, StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn duplicate_provider_request_does_not_execute_a_second_side_effect() {
    let state = state();
    let (core_url, mut callbacks) = callback_server().await;
    install(&state, &core_url);
    let request = provider_request("provider-run-1", "provider-conversation-1", "chat.send");

    let (first_status, first) = post_json(
        router(Arc::clone(&state)),
        "/internal/v1/workspace-core/provider",
        "provider-token",
        request.clone(),
    )
    .await;
    let callback = tokio::time::timeout(std::time::Duration::from_secs(5), async {
        loop {
            let callback = callbacks.recv().await.expect("callback");
            if matches!(
                callback["payload"]["state"].as_str(),
                Some("final" | "error" | "aborted")
            ) {
                return callback;
            }
        }
    })
    .await
    .expect("terminal callback deadline");
    let (duplicate_status, duplicate) = post_json(
        router(Arc::clone(&state)),
        "/internal/v1/workspace-core/provider",
        "provider-token",
        request,
    )
    .await;

    assert_eq!(first_status, StatusCode::OK);
    assert_eq!(duplicate_status, StatusCode::OK);
    assert_eq!(first, duplicate);
    assert_eq!(callback["run_id"], "provider-run-1");
    assert_eq!(callback["payload"]["state"], "final");
    let timeline = state
        .session_store
        .timeline("provider-conversation-1", 100)
        .expect("timeline");
    assert_eq!(
        timeline
            .iter()
            .filter(|item| item["type"] == "user_message")
            .count(),
        1
    );
    assert!(timeline
        .iter()
        .any(|item| item["type"] == "assistant_message"));
}

#[tokio::test]
async fn request_id_payload_conflict_is_rejected() {
    let state = state();
    let (core_url, _callbacks) = callback_server().await;
    install(&state, &core_url);
    let first = provider_request(
        "provider-run-conflict",
        "provider-conversation-2",
        "chat.send",
    );
    let mut conflicting = first.clone();
    conflicting["message"]["content"][0]["text"] = json!("different payload");

    let (first_status, _) = post_json(
        router(Arc::clone(&state)),
        "/internal/v1/workspace-core/provider",
        "provider-token",
        first,
    )
    .await;
    let (conflict_status, _) = post_json(
        router(state),
        "/internal/v1/workspace-core/provider",
        "provider-token",
        conflicting,
    )
    .await;

    assert_eq!(first_status, StatusCode::OK);
    assert_eq!(conflict_status, StatusCode::CONFLICT);
}

#[tokio::test]
async fn injected_context_is_returned_by_provider_history() {
    let state = state();
    install(&state, "http://127.0.0.1:21000");
    insert_conversation(&state, "provider-conversation-history");
    let mut inject = provider_request(
        "provider-inject-1",
        "provider-conversation-history",
        "chat.inject",
    );
    inject["message"]["content"][0]["text"] = json!("durable injected context");

    let (inject_status, _) = post_json(
        router(Arc::clone(&state)),
        "/internal/v1/workspace-core/provider",
        "provider-token",
        inject,
    )
    .await;
    let history = provider_request(
        "provider-history-1",
        "provider-conversation-history",
        "chat.history",
    );
    let (history_status, body) = post_json(
        router(state),
        "/internal/v1/workspace-core/provider",
        "provider-token",
        history,
    )
    .await;

    assert_eq!(inject_status, StatusCode::OK);
    assert_eq!(history_status, StatusCode::OK);
    let messages = body["messages"].as_array().expect("history messages");
    assert!(messages.iter().any(|message| {
        message["type"] == "avernet_context_injection"
            && message["content"] == "durable injected context"
    }));
}

#[tokio::test]
async fn provider_abort_sets_the_active_run_cancel_directive() {
    let state = state();
    install(&state, "http://127.0.0.1:21000");
    let conversation_id = "provider-conversation-abort";
    insert_conversation(&state, conversation_id);
    let control = state
        .claim_agent_run(conversation_id, None)
        .expect("claim active Agent run");

    let (status, body) = post_json(
        router(Arc::clone(&state)),
        "/internal/v1/workspace-core/provider",
        "provider-token",
        provider_request("provider-abort-1", conversation_id, "chat.abort"),
    )
    .await;

    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["local_worker_cancelled"], true);
    assert!(matches!(
        control.directive(conversation_id, 0).await,
        Ok(RunDirective::Cancel)
    ));
    state.release_agent_run(conversation_id);
}

#[tokio::test]
async fn duplicate_plan_dispatch_does_not_start_a_second_agent_run() {
    let state = state();
    install(&state, "http://127.0.0.1:21000");
    state.agent_run_claim_attempts.store(0, Ordering::SeqCst);
    let request = plan_dispatch_request("plan-outbox-1", "plan-conversation-1");

    let (first_status, first) = post_json(
        router(Arc::clone(&state)),
        "/internal/v1/workspace-core/plan-dispatch",
        "provider-token",
        request.clone(),
    )
    .await;
    tokio::time::timeout(std::time::Duration::from_secs(2), async {
        while state.agent_run_claim_attempts.load(Ordering::SeqCst) == 0 {
            tokio::task::yield_now().await;
        }
    })
    .await
    .expect("plan Agent start deadline");
    let (duplicate_status, duplicate) = post_json(
        router(Arc::clone(&state)),
        "/internal/v1/workspace-core/plan-dispatch",
        "provider-token",
        request,
    )
    .await;
    tokio::time::sleep(std::time::Duration::from_millis(25)).await;

    assert_eq!(first_status, StatusCode::OK);
    assert_eq!(duplicate_status, StatusCode::OK);
    assert_eq!(first, duplicate);
    assert_eq!(first["provider_id"], "memstack-agent-runtime");
    assert_eq!(first["provider_bot_ref"], "builtin:all-access");
    assert_eq!(state.agent_run_claim_attempts.load(Ordering::SeqCst), 1);
}

#[tokio::test]
async fn judge_fails_closed_when_agent_returns_finish_without_a_tool_call() {
    let state = state();
    install(&state, "http://127.0.0.1:21000");

    let (status, body) = post_json(
        router(state),
        "/internal/v1/workspace-core/plan-judge",
        "registry-token",
        json!({
            "tenant_id": "local",
            "project_id": "local-project",
            "workspace_id": "local-workspace",
            "actor_id": "supervisor-1",
            "plan_id": "plan-1",
            "plan_revision": 1,
            "kind": "select_pipeline_target",
            "candidate_node_ids": ["node-1"],
            "evidence": { "ready": true }
        }),
    )
    .await;

    assert_eq!(status, StatusCode::SERVICE_UNAVAILABLE);
    assert!(body.to_string().contains("structured tool call"));
}

#[tokio::test]
async fn stale_authority_generation_cannot_clear_the_rotated_authority() {
    let state = state();
    let first_generation = install(&state, "http://127.0.0.1:21000");
    let second_generation = install_authority(
        &state,
        "http://127.0.0.1:22000".to_string(),
        "registry-token-2".to_string(),
        "provider-token-2".to_string(),
        "event-token-2".to_string(),
    )
    .expect("rotate authority");
    clear_authority(&state, first_generation);

    let (rotated_status, _) = post_json(
        router(Arc::clone(&state)),
        "/internal/v1/workspace-core/agent-registry/resolve",
        "registry-token-2",
        agent_lookup(None),
    )
    .await;
    let (stale_status, _) = post_json(
        router(Arc::clone(&state)),
        "/internal/v1/workspace-core/agent-registry/resolve",
        "registry-token",
        agent_lookup(None),
    )
    .await;
    clear_authority(&state, second_generation);
    let (cleared_status, _) = post_json(
        router(state),
        "/internal/v1/workspace-core/agent-registry/resolve",
        "registry-token-2",
        agent_lookup(None),
    )
    .await;

    assert_eq!(rotated_status, StatusCode::OK);
    assert_eq!(stale_status, StatusCode::UNAUTHORIZED);
    assert_eq!(cleared_status, StatusCode::SERVICE_UNAVAILABLE);
}

#[tokio::test]
async fn provider_callbacks_preserve_tool_start_end_and_final_order() {
    let state = state();
    let (core_url, mut callbacks) = callback_server().await;
    install(&state, &core_url);

    let (status, _) = post_json(
        router(state),
        "/internal/v1/workspace-core/provider",
        "provider-token",
        provider_request(
            "provider-run-order",
            "provider-conversation-order",
            "chat.send",
        ),
    )
    .await;
    let states = tokio::time::timeout(std::time::Duration::from_secs(5), async {
        let mut states = Vec::new();
        loop {
            let callback = callbacks.recv().await.expect("callback");
            let callback_state = callback["payload"]["state"]
                .as_str()
                .expect("callback state")
                .to_string();
            let terminal = matches!(callback_state.as_str(), "final" | "error" | "aborted");
            states.push(callback_state);
            if terminal {
                return states;
            }
        }
    })
    .await
    .expect("ordered callback deadline");

    assert_eq!(status, StatusCode::OK);
    let start = states
        .iter()
        .position(|state| state == "tool_call_start")
        .expect("tool start callback");
    let end = states
        .iter()
        .position(|state| state == "tool_call_end")
        .expect("tool end callback");
    let final_event = states
        .iter()
        .position(|state| state == "final")
        .expect("final callback");
    assert!(
        start < end && end < final_event,
        "callback states: {states:?}"
    );
}

#[tokio::test]
async fn terminal_callback_outbox_replays_after_core_recovers() {
    let state = state();
    let (failing_core_url, mut failed_callbacks) =
        callback_server_with_status(StatusCode::SERVICE_UNAVAILABLE).await;
    install(&state, &failing_core_url);

    let (status, _) = post_json(
        router(Arc::clone(&state)),
        "/internal/v1/workspace-core/provider",
        "provider-token",
        provider_request(
            "provider-run-replay",
            "provider-conversation-replay",
            "chat.send",
        ),
    )
    .await;
    tokio::time::timeout(std::time::Duration::from_secs(5), async {
        loop {
            let callback = failed_callbacks.recv().await.expect("failed callback");
            if callback["payload"]["state"] == "final" {
                break;
            }
        }
    })
    .await
    .expect("failed terminal callback deadline");
    let pending = tokio::time::timeout(std::time::Duration::from_secs(5), async {
        loop {
            let pending = state
                .session_store
                .pending_workspace_core_terminal_callbacks(10)
                .expect("pending terminal callbacks");
            if pending
                .first()
                .is_some_and(|callback| callback.attempt_count >= 3)
            {
                return pending;
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .expect("terminal outbox persistence deadline");

    assert_eq!(status, StatusCode::OK);
    assert_eq!(pending.len(), 1);
    assert_eq!(pending[0].run_id, "provider-run-replay");
    assert_eq!(pending[0].payload["payload"]["state"], "final");
    let timeline = state
        .session_store
        .timeline("provider-conversation-replay", 100)
        .expect("terminal timeline");
    assert!(timeline
        .iter()
        .any(|item| item["type"] == "assistant_message"));

    let (recovered_core_url, mut recovered_callbacks) = callback_server().await;
    install_authority(
        &state,
        recovered_core_url,
        "registry-token".to_string(),
        "provider-token".to_string(),
        "event-token".to_string(),
    )
    .expect("install recovered authority");
    let delivered = replay_pending_terminal_callbacks(Arc::clone(&state))
        .await
        .expect("replay terminal callbacks");
    let recovered = tokio::time::timeout(
        std::time::Duration::from_secs(5),
        recovered_callbacks.recv(),
    )
    .await
    .expect("recovered callback deadline")
    .expect("recovered callback");

    assert_eq!(delivered, 1);
    assert_eq!(recovered["run_id"], "provider-run-replay");
    assert_eq!(recovered["payload"]["state"], "final");
    assert!(state
        .session_store
        .pending_workspace_core_terminal_callbacks(10)
        .expect("drained terminal callbacks")
        .is_empty());
}

#[tokio::test]
async fn terminal_callback_gone_response_is_marked_delivered() {
    let state = state();
    let (core_url, mut callbacks) = callback_server_with_status(StatusCode::GONE).await;
    install(&state, &core_url);

    let (status, _) = post_json(
        router(Arc::clone(&state)),
        "/internal/v1/workspace-core/provider",
        "provider-token",
        provider_request(
            "provider-run-gone",
            "provider-conversation-gone",
            "chat.send",
        ),
    )
    .await;
    tokio::time::timeout(std::time::Duration::from_secs(5), async {
        loop {
            let callback = callbacks.recv().await.expect("gone callback");
            if callback["payload"]["state"] == "final" {
                break;
            }
        }
    })
    .await
    .expect("gone terminal callback deadline");
    tokio::time::timeout(std::time::Duration::from_secs(5), async {
        loop {
            if state
                .session_store
                .pending_workspace_core_terminal_callbacks(10)
                .expect("pending terminal callbacks")
                .is_empty()
            {
                break;
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .expect("gone delivery marker deadline");

    assert_eq!(status, StatusCode::OK);
}

async fn callback_server() -> (String, mpsc::Receiver<Value>) {
    callback_server_with_status(StatusCode::OK).await
}

type CallbackState = Arc<Mutex<(mpsc::Sender<Value>, StatusCode)>>;

async fn callback_server_with_status(status: StatusCode) -> (String, mpsc::Receiver<Value>) {
    let (sender, receiver) = mpsc::channel(32);
    let sender = Arc::new(Mutex::new((sender, status)));

    async fn callback(
        State(state): State<CallbackState>,
        headers: HeaderMap,
        Json(body): Json<Value>,
    ) -> StatusCode {
        assert_eq!(headers["authorization"], "Bearer event-token");
        assert_eq!(
            headers["bcn-provider-id"],
            "memstack-workspace-agent-runtime"
        );
        let (sender, status) = &*state.lock().await;
        sender.send(body).await.expect("record callback");
        *status
    }

    let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
        .await
        .expect("bind callback server");
    let address = listener.local_addr().expect("callback address");
    tokio::spawn(async move {
        axum::serve(
            listener,
            Router::new()
                .route("/bot/events", post(callback))
                .with_state(sender),
        )
        .await
        .expect("callback server");
    });
    (format!("http://{address}"), receiver)
}
