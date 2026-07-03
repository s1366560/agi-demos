use agistack_adapters_postgres::{
    WorkspaceMessageRecord, WorkspacePlanNodeRecord, WorkspaceTaskRecord,
    WorkspaceTaskSessionAttemptRecord,
};
use agistack_core::ports::{CoreError, CoreResult};
use chrono::{DateTime, SecondsFormat, Utc};
use serde_json::{json, Map, Value};

use super::{
    string_from_map, string_from_value_object, GOAL_ROOT_TASK_ROLE, ROOT_GOAL_TASK_ID, TASK_ROLE,
    WORKSPACE_PLAN_ID, WORKSPACE_PLAN_SYSTEM_ACTOR_ID,
};

pub(super) fn workspace_message_event_payload(message: &WorkspaceMessageRecord) -> Value {
    json!({
        "id": &message.id,
        "workspace_id": &message.workspace_id,
        "sender_id": &message.sender_id,
        "sender_type": &message.sender_type,
        "content": &message.content,
        "mentions": &message.mentions_json,
        "parent_message_id": &message.parent_message_id,
        "metadata": &message.metadata_json,
        "created_at": workspace_event_iso(message.created_at),
    })
}

pub(super) fn workspace_event_iso(value: DateTime<Utc>) -> String {
    value.to_rfc3339_opts(SecondsFormat::Millis, true)
}

pub(super) fn root_goal_task_id_for_progress(
    task: &WorkspaceTaskRecord,
    attempt: &WorkspaceTaskSessionAttemptRecord,
) -> Option<String> {
    string_from_value_object(&task.metadata_json, ROOT_GOAL_TASK_ID).or_else(|| {
        let candidate = attempt.root_goal_task_id.trim();
        if candidate.is_empty() {
            None
        } else {
            Some(candidate.to_string())
        }
    })
}

pub(super) fn is_goal_root_task(task: &WorkspaceTaskRecord) -> bool {
    string_from_value_object(&task.metadata_json, TASK_ROLE).as_deref() == Some(GOAL_ROOT_TASK_ROLE)
}

pub(super) fn select_root_progress_child_tasks(
    child_tasks: Vec<WorkspaceTaskRecord>,
) -> Vec<WorkspaceTaskRecord> {
    let plan_projected = child_tasks
        .iter()
        .filter(|task| string_from_value_object(&task.metadata_json, WORKSPACE_PLAN_ID).is_some())
        .cloned()
        .collect::<Vec<_>>();
    if plan_projected.is_empty() {
        child_tasks
    } else {
        plan_projected
    }
}

pub(super) fn bool_from_map(map: &Map<String, Value>, key: &str) -> bool {
    map.get(key).and_then(Value::as_bool).unwrap_or(false)
}

pub(super) fn required_string(map: &Map<String, Value>, key: &str) -> CoreResult<String> {
    string_from_map(map, key)
        .ok_or_else(|| CoreError::Storage(format!("{key} is required in outbox payload")))
}

pub(super) fn persisted_attempt_leader_agent_id(leader_agent_id: &str) -> Option<String> {
    if leader_agent_id == WORKSPACE_PLAN_SYSTEM_ACTOR_ID {
        None
    } else {
        Some(leader_agent_id.to_string())
    }
}

pub(super) fn recoverable_node_attempt_id(node: &WorkspacePlanNodeRecord) -> Option<String> {
    let attempt_id = node.current_attempt_id.as_deref()?.trim();
    if attempt_id.is_empty() {
        return None;
    }
    if matches!(
        node.execution.as_str(),
        "dispatched" | "running" | "reported" | "verifying"
    ) {
        return Some(attempt_id.to_string());
    }
    if node.execution == "idle"
        && matches!(node.intent.as_str(), "in_progress" | "blocked" | "done")
    {
        return Some(attempt_id.to_string());
    }
    None
}
