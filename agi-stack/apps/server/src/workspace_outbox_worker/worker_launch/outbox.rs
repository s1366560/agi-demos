use super::*;

pub(in crate::workspace_outbox_worker) struct WorkerStreamTerminalPersistence<'a> {
    pub(in crate::workspace_outbox_worker) workspace_id: &'a str,
    pub(in crate::workspace_outbox_worker) task_id: &'a str,
    pub(in crate::workspace_outbox_worker) root_goal_task_id: Option<&'a str>,
    pub(in crate::workspace_outbox_worker) attempt_id: Option<&'a str>,
    pub(in crate::workspace_outbox_worker) conversation_id: Option<&'a str>,
    pub(in crate::workspace_outbox_worker) actor_user_id: &'a str,
    pub(in crate::workspace_outbox_worker) worker_agent_id: &'a str,
    pub(in crate::workspace_outbox_worker) leader_agent_id: Option<&'a str>,
    pub(in crate::workspace_outbox_worker) plan_id: Option<&'a str>,
    pub(in crate::workspace_outbox_worker) node_id: Option<&'a str>,
    pub(in crate::workspace_outbox_worker) outcome: &'a worker_stream_watchdog::TerminalOutcome,
    pub(in crate::workspace_outbox_worker) now: DateTime<Utc>,
}

#[derive(Debug, Clone)]
pub(in crate::workspace_outbox_worker) struct WorkerReportPayload {
    pub(in crate::workspace_outbox_worker) normalized_summary: String,
    pub(in crate::workspace_outbox_worker) report_artifacts: Vec<String>,
    pub(in crate::workspace_outbox_worker) merged_artifacts: Vec<String>,
    pub(in crate::workspace_outbox_worker) report_verifications: Vec<String>,
    pub(in crate::workspace_outbox_worker) merged_verifications: Vec<String>,
    pub(in crate::workspace_outbox_worker) fingerprint: String,
}

#[allow(clippy::too_many_arguments)]
pub(in crate::workspace_outbox_worker) fn worker_launch_outbox(
    plan_id: Option<&str>,
    workspace_id: &str,
    source_event_type: &str,
    payload: &Map<String, Value>,
    task_id: &str,
    worker_agent_id: &str,
    actor_user_id: &str,
    leader_agent_id: &str,
    attempt_id: &str,
    node_id: Option<&str>,
    created_at: DateTime<Utc>,
) -> WorkspacePlanOutboxRecord {
    let mut launch_payload = Map::new();
    launch_payload.insert("workspace_id".to_string(), json!(workspace_id));
    launch_payload.insert("task_id".to_string(), json!(task_id));
    launch_payload.insert("worker_agent_id".to_string(), json!(worker_agent_id));
    launch_payload.insert("actor_user_id".to_string(), json!(actor_user_id));
    launch_payload.insert("leader_agent_id".to_string(), json!(leader_agent_id));
    launch_payload.insert("attempt_id".to_string(), json!(attempt_id));
    if let Some(node_id) = node_id {
        launch_payload.insert("node_id".to_string(), json!(node_id));
    }
    for optional_key in [
        "extra_instructions",
        "reuse_conversation_id",
        "repair_brief_prompt",
    ] {
        if let Some(value) = payload.get(optional_key) {
            launch_payload.insert(optional_key.to_string(), value.clone());
        }
    }
    copy_retry_context_payload_fields(payload, &mut launch_payload);
    WorkspacePlanOutboxRecord {
        id: generate_uuid_v4(),
        plan_id: plan_id.map(ToOwned::to_owned),
        workspace_id: workspace_id.to_string(),
        event_type: WORKER_LAUNCH_EVENT.to_string(),
        payload_json: Value::Object(launch_payload),
        status: "pending".to_string(),
        attempt_count: 0,
        max_attempts: 5,
        lease_owner: None,
        lease_expires_at: None,
        last_error: None,
        next_attempt_at: None,
        processed_at: None,
        metadata_json: json!({
            "source": format!("workspace_plan.{source_event_type}"),
            "previous_attempt_id": string_from_map(payload, "previous_attempt_id")
        }),
        created_at,
        updated_at: None,
    }
}

pub(super) fn deferred_worker_launch_outbox(
    item: &WorkspacePlanOutboxRecord,
    payload: &Map<String, Value>,
    active_count: i64,
    max_active: i64,
    delay_seconds: i64,
    now: DateTime<Utc>,
) -> WorkspacePlanOutboxRecord {
    let mut metadata = object_or_empty(item.metadata_json.clone());
    let defer_count = metadata
        .get("defer_count")
        .and_then(Value::as_i64)
        .unwrap_or(0)
        + 1;
    metadata.insert(
        "source".to_string(),
        json!("workspace_plan.worker_launch.deferred_capacity"),
    );
    metadata.insert(
        "deferred_from_outbox_id".to_string(),
        json!(item.id.clone()),
    );
    metadata.insert("defer_count".to_string(), json!(defer_count));
    metadata.insert(
        "active_worker_conversations".to_string(),
        json!(active_count),
    );
    metadata.insert(
        "max_active_worker_conversations".to_string(),
        json!(max_active),
    );
    WorkspacePlanOutboxRecord {
        id: generate_uuid_v4(),
        plan_id: item.plan_id.clone(),
        workspace_id: item.workspace_id.clone(),
        event_type: WORKER_LAUNCH_EVENT.to_string(),
        payload_json: Value::Object(payload.clone()),
        status: "pending".to_string(),
        attempt_count: 0,
        max_attempts: item.max_attempts,
        lease_owner: None,
        lease_expires_at: None,
        last_error: None,
        next_attempt_at: Some(now + ChronoDuration::seconds(delay_seconds.max(1))),
        processed_at: None,
        metadata_json: Value::Object(metadata),
        created_at: now,
        updated_at: None,
    }
}
