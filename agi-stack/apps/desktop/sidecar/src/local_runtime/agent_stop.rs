//! Reply cancellation is bound to the exact planning turn the client observed.
use serde_json::{json, Value};
use std::sync::Arc;

use super::{auth_context::AuthenticatedContext, LocalRuntimeState};

pub(super) fn handle_command(
    state: &Arc<LocalRuntimeState>,
    authenticated: &AuthenticatedContext,
    command: &Value,
) -> Value {
    let conversation_id = command["conversation_id"].as_str().unwrap_or_default();
    let message_id = command["message_id"].as_str().unwrap_or_default();
    let error = |code: &str, message: &str| {
        json!({
            "type": "error", "action": "stop_session", "code": code,
            "message": message, "conversation_id": conversation_id, "message_id": message_id,
        })
    };
    if conversation_id.is_empty() || message_id.is_empty() {
        return error(
            "STOP_SESSION_FAILED",
            "an exact planning message_id is required to stop a local reply",
        );
    }
    if !state
        .session_store
        .session_context_is_current(authenticated, chrono::Utc::now().timestamp_millis())
        .unwrap_or(false)
    {
        return error(
            "STOP_SESSION_FAILED",
            "desktop session or workspace context is no longer active",
        );
    }
    let allowed = state
        .session_store
        .conversation(conversation_id)
        .ok()
        .flatten()
        .is_some_and(|conversation| {
            conversation.tenant_id == authenticated.workspace.tenant_id
                && conversation.project_id == authenticated.workspace.project_id
        });
    if !allowed {
        return error(
            "STOP_SESSION_FAILED",
            "conversation is outside the active workspace context",
        );
    }
    // Hold the claim lock through validation and cancellation. A delayed request
    // cannot resolve the conversation again and target a successor execution.
    let runs = state.agent_runs.lock().expect("local agent runs");
    let Some(active) = runs.get(conversation_id) else {
        return error(
            "SESSION_NOT_RUNNING",
            "no running reply matches this planning turn",
        );
    };
    if active.run_id.is_some() {
        return error(
            "STOP_SESSION_FAILED",
            "authoritative executions require the run cancellation endpoint",
        );
    }
    if active
        .control
        .message_id
        .lock()
        .expect("local run message")
        .as_deref()
        != Some(message_id)
    {
        return error("STOP_SESSION_FAILED", "the planning turn has changed");
    }
    active.control.request_cancel();
    json!({
        "type": "ack", "action": "stop_session", "accepted": true,
        "status": "cancel_requested", "conversation_id": conversation_id, "message_id": message_id,
    })
}
