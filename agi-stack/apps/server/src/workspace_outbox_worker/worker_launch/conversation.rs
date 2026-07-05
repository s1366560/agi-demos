use super::*;

const WORKER_LAUNCH_CONVERSATION_SOURCE: &str = "workspace_worker_launch";
const WORKER_LAUNCH_CONVERSATION_STAGE: &str = "worker_launch";

fn worker_conversation_scope_for_task(task_id: &str, attempt_id: Option<&str>) -> String {
    attempt_id
        .map(|attempt_id| format!("task:{task_id}:attempt:{attempt_id}"))
        .unwrap_or_else(|| format!("task:{task_id}"))
}

pub(crate) fn worker_conversation_id(
    workspace_id: &str,
    worker_agent_id: &str,
    task_id: &str,
    attempt_id: Option<&str>,
) -> String {
    let scope = worker_conversation_scope_for_task(task_id, attempt_id);
    let name = format!("workspace:{workspace_id}:agent:{worker_agent_id}:scope:{scope}");
    Uuid::new_v5(&Uuid::NAMESPACE_DNS, name.as_bytes()).to_string()
}

pub(super) fn worker_conversation_title(task: &WorkspaceTaskRecord) -> String {
    let title_prefix = task.title.chars().take(80).collect::<String>();
    format!("Workspace Worker - {title_prefix}")
}

pub(super) fn worker_conversation_metadata(
    workspace_id: &str,
    task: &WorkspaceTaskRecord,
    task_metadata: &Map<String, Value>,
    worker_agent_id: &str,
    attempt: &WorkspaceTaskSessionAttemptRecord,
    now: DateTime<Utc>,
) -> Value {
    let mut metadata = json!({
        "workspace_id": workspace_id,
        "agent_id": worker_agent_id,
        "workspace_agent_binding_id": Value::Null,
        "workspace_task_id": task.id,
        "linked_workspace_task_id": task.id,
        ROOT_GOAL_TASK_ID: attempt.root_goal_task_id,
        "attempt_id": attempt.id,
        "conversation_scope": worker_conversation_scope_for_task(&task.id, Some(&attempt.id)),
        "source": WORKER_LAUNCH_CONVERSATION_SOURCE,
        "workspace_llm_stage": WORKER_LAUNCH_CONVERSATION_STAGE,
        "created_at": now.to_rfc3339(),
    });
    if let Some(preferred_language) = string_from_map(task_metadata, "preferred_language") {
        if let Some(map) = metadata.as_object_mut() {
            map.insert("preferred_language".to_string(), json!(preferred_language));
        }
    }
    if let Some(map) = metadata.as_object_mut() {
        for key in [
            "last_retry_reason",
            "last_retry_previous_attempt_id",
            "retry_origin",
            "worker_stream_orphan_retry_reason",
            "worker_stream_orphan_summary",
        ] {
            copy_metadata_string_field(task_metadata, map, key);
        }
    }
    metadata
}
