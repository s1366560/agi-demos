use super::*;

#[allow(clippy::too_many_arguments)]
pub(in crate::workspace_outbox_worker) fn worker_report_supervisor_tick(
    workspace_id: &str,
    plan_id: &str,
    node_id: &str,
    attempt_id: &str,
    root_goal_task_id: &str,
    actor_user_id: &str,
    leader_agent_id: Option<&str>,
    now: DateTime<Utc>,
) -> WorkspacePlanOutboxRecord {
    WorkspacePlanOutboxRecord {
        id: generate_uuid_v4(),
        plan_id: Some(plan_id.to_string()),
        workspace_id: workspace_id.to_string(),
        event_type: SUPERVISOR_TICK_EVENT.to_string(),
        payload_json: json!({
            "workspace_id": workspace_id,
            "root_task_id": root_goal_task_id,
            "actor_user_id": actor_user_id,
            "leader_agent_id": leader_agent_id,
            "plan_id": plan_id,
            "node_id": node_id,
            "attempt_id": attempt_id
        }),
        status: "pending".to_string(),
        attempt_count: 0,
        max_attempts: 3,
        lease_owner: None,
        lease_expires_at: None,
        last_error: None,
        next_attempt_at: None,
        processed_at: None,
        metadata_json: json!({
            "source": "worker_report",
            "node_id": node_id,
            "attempt_id": attempt_id
        }),
        created_at: now,
        updated_at: None,
    }
}

pub(in crate::workspace_outbox_worker) struct SupervisorReplanTickOutboxInput<'a> {
    pub(in crate::workspace_outbox_worker) workspace_id: &'a str,
    pub(in crate::workspace_outbox_worker) plan_id: &'a str,
    pub(in crate::workspace_outbox_worker) node_id: &'a str,
    pub(in crate::workspace_outbox_worker) task_id: Option<&'a str>,
    pub(in crate::workspace_outbox_worker) worker_agent_id: Option<&'a str>,
    pub(in crate::workspace_outbox_worker) reason: &'a str,
    pub(in crate::workspace_outbox_worker) previous_attempt_id: Option<&'a str>,
    pub(in crate::workspace_outbox_worker) now: DateTime<Utc>,
}

pub(in crate::workspace_outbox_worker) fn supervisor_replan_tick_outbox(
    input: SupervisorReplanTickOutboxInput<'_>,
) -> WorkspacePlanOutboxRecord {
    let SupervisorReplanTickOutboxInput {
        workspace_id,
        plan_id,
        node_id,
        task_id,
        worker_agent_id,
        reason,
        previous_attempt_id,
        now,
    } = input;
    let mut payload = Map::new();
    payload.insert("workspace_id".to_string(), json!(workspace_id));
    payload.insert("plan_id".to_string(), json!(plan_id));
    payload.insert("node_id".to_string(), json!(node_id));
    payload.insert(
        "actor_user_id".to_string(),
        json!(WORKSPACE_PLAN_SYSTEM_ACTOR_ID),
    );
    payload.insert(
        "operator_action".to_string(),
        json!("operator_replan_requested"),
    );
    payload.insert(
        "supervisor_action".to_string(),
        json!(SUPERVISOR_DECISION_REPLAN_NODE_ACTION),
    );
    payload.insert(
        "retry_reason".to_string(),
        json!(SUPERVISOR_DECISION_REPLAN_NODE_REASON),
    );
    payload.insert("reason".to_string(), json!(reason));
    if let Some(task_id) = task_id {
        payload.insert("task_id".to_string(), json!(task_id));
    }
    if let Some(worker_agent_id) = worker_agent_id {
        payload.insert("worker_agent_id".to_string(), json!(worker_agent_id));
    }
    if let Some(previous_attempt_id) = previous_attempt_id {
        payload.insert(
            "previous_attempt_id".to_string(),
            json!(previous_attempt_id),
        );
        payload.insert("retry_attempt_id".to_string(), json!(previous_attempt_id));
    }

    WorkspacePlanOutboxRecord {
        id: generate_uuid_v4(),
        plan_id: Some(plan_id.to_string()),
        workspace_id: workspace_id.to_string(),
        event_type: SUPERVISOR_TICK_EVENT.to_string(),
        payload_json: Value::Object(payload),
        status: "pending".to_string(),
        attempt_count: 0,
        max_attempts: 5,
        lease_owner: None,
        lease_expires_at: None,
        last_error: None,
        next_attempt_at: None,
        processed_at: None,
        metadata_json: json!({
            "source": "workspace_plan.supervisor_decision_replan",
            "node_id": node_id,
            "previous_attempt_id": previous_attempt_id
        }),
        created_at: now,
        updated_at: None,
    }
}

pub(in crate::workspace_outbox_worker) fn supervisor_request_pipeline_outbox(
    workspace_id: &str,
    plan_id: &str,
    node_id: &str,
    attempt_id: Option<&str>,
    reason: &str,
    metadata: &Map<String, Value>,
    created_at: DateTime<Utc>,
) -> WorkspacePlanOutboxRecord {
    let mut payload = Map::new();
    payload.insert("workspace_id".to_string(), json!(workspace_id));
    payload.insert("plan_id".to_string(), json!(plan_id));
    payload.insert("node_id".to_string(), json!(node_id));
    payload.insert(
        "reason".to_string(),
        json!(SUPERVISOR_DECISION_REQUEST_PIPELINE_REASON),
    );
    payload.insert("summary".to_string(), json!(reason));
    if let Some(attempt_id) = attempt_id {
        payload.insert("attempt_id".to_string(), json!(attempt_id));
    }

    WorkspacePlanOutboxRecord {
        id: generate_uuid_v4(),
        plan_id: Some(plan_id.to_string()),
        workspace_id: workspace_id.to_string(),
        event_type: PIPELINE_RUN_REQUESTED_EVENT.to_string(),
        payload_json: Value::Object(payload),
        status: "pending".to_string(),
        attempt_count: 0,
        max_attempts: 5,
        lease_owner: None,
        lease_expires_at: None,
        last_error: None,
        next_attempt_at: None,
        processed_at: None,
        metadata_json: json!({
            "source": "workspace_plan.supervisor_decision_request_pipeline",
            "node_id": node_id,
            "attempt_id": attempt_id,
            "supervisor_action": SUPERVISOR_DECISION_REQUEST_PIPELINE_ACTION,
            "confidence": metadata.get("last_supervisor_decision_confidence").cloned().unwrap_or(Value::Null),
            "feedback_items": metadata.get("last_supervisor_decision_feedback_items").cloned().unwrap_or(Value::Null),
        }),
        created_at,
        updated_at: None,
    }
}

#[allow(clippy::too_many_arguments)]
pub(in crate::workspace_outbox_worker) fn supervisor_retry_attempt_outbox(
    item: &WorkspacePlanOutboxRecord,
    payload: &Map<String, Value>,
    workspace_id: &str,
    plan_id: &str,
    node_id: &str,
    task_id: &str,
    worker_agent_id: &str,
    actor_user_id: &str,
    leader_agent_id: &str,
    root_goal_task_id: Option<&str>,
    retry_attempt_id: Option<&str>,
    retry_reason: &str,
    created_at: DateTime<Utc>,
) -> WorkspacePlanOutboxRecord {
    let mut retry_payload = Map::new();
    retry_payload.insert("workspace_id".to_string(), json!(workspace_id));
    retry_payload.insert("plan_id".to_string(), json!(plan_id));
    retry_payload.insert("node_id".to_string(), json!(node_id));
    retry_payload.insert("task_id".to_string(), json!(task_id));
    retry_payload.insert("worker_agent_id".to_string(), json!(worker_agent_id));
    retry_payload.insert("actor_user_id".to_string(), json!(actor_user_id));
    retry_payload.insert("leader_agent_id".to_string(), json!(leader_agent_id));
    retry_payload.insert("retry_reason".to_string(), json!(retry_reason));
    if let Some(root_goal_task_id) = root_goal_task_id {
        retry_payload.insert(ROOT_GOAL_TASK_ID.to_string(), json!(root_goal_task_id));
    }
    if let Some(retry_attempt_id) = retry_attempt_id {
        retry_payload.insert("previous_attempt_id".to_string(), json!(retry_attempt_id));
        retry_payload.insert("retry_attempt_id".to_string(), json!(retry_attempt_id));
    }
    for optional_key in [
        "extra_instructions",
        "force_schedule",
        "repair_brief_prompt",
        "reuse_conversation_id",
    ] {
        if let Some(value) = payload.get(optional_key) {
            retry_payload.insert(optional_key.to_string(), value.clone());
        }
    }
    copy_retry_context_payload_fields(payload, &mut retry_payload);

    WorkspacePlanOutboxRecord {
        id: generate_uuid_v4(),
        plan_id: Some(plan_id.to_string()),
        workspace_id: workspace_id.to_string(),
        event_type: ATTEMPT_RETRY_EVENT.to_string(),
        payload_json: Value::Object(retry_payload),
        status: "pending".to_string(),
        attempt_count: 0,
        max_attempts: item.max_attempts,
        lease_owner: None,
        lease_expires_at: None,
        last_error: None,
        next_attempt_at: None,
        processed_at: None,
        metadata_json: json!({
            "source": "workspace_plan.supervisor_tick.retry_admission",
            "previous_outbox_id": item.id,
            "retry_node_id": node_id,
            "retry_attempt_id": retry_attempt_id,
            "retry_reason": retry_reason
        }),
        created_at,
        updated_at: None,
    }
}
