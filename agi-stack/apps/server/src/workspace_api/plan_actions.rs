use std::collections::HashMap;

use super::*;

pub(super) fn outbox_actions(
    record: &WorkspacePlanOutboxRecord,
) -> HashMap<String, WorkspacePlanActionCapabilityView> {
    let delayed = record.status == "pending"
        && record
            .next_attempt_at
            .map(|next_attempt_at| next_attempt_at > Utc::now())
            .unwrap_or(false);
    let retryable = matches!(record.status.as_str(), "failed" | "dead_letter") || delayed;
    HashMap::from([(
        "retry_outbox".to_string(),
        plan_snapshot::action(
            retryable,
            "Retry now",
            if retryable {
                None
            } else {
                Some("Only failed, dead-letter, or delayed pending jobs can be retried.")
            },
            false,
        ),
    )])
}

pub(super) fn validate_plan_action_request(
    body: &WorkspacePlanActionRequest,
) -> Result<(), WorkspaceApiError> {
    validate_plan_action_parts(body.reason.as_ref(), body.evidence_refs.len())
}

pub(super) fn validate_plan_pipeline_request(
    body: &WorkspacePlanPipelineRunRequest,
) -> Result<(), WorkspaceApiError> {
    validate_plan_action_parts(body.reason.as_ref(), body.evidence_refs.len())
}

fn validate_plan_action_parts(
    reason: Option<&String>,
    evidence_refs_len: usize,
) -> Result<(), WorkspaceApiError> {
    if reason
        .map(|reason| reason.chars().count() > 500)
        .unwrap_or(false)
        || evidence_refs_len > 20
    {
        return Err(WorkspaceApiError::bad_request(
            "Invalid workspace plan request",
        ));
    }
    Ok(())
}

pub(super) fn map_plan_outbox_retry_error(
    err: agistack_core::ports::CoreError,
) -> WorkspaceApiError {
    if err.to_string().contains("not retryable") {
        WorkspaceApiError::bad_request("Invalid workspace plan request")
    } else {
        WorkspaceApiError::internal(err)
    }
}

pub(super) fn plan_action_outbox(
    plan_id: &str,
    workspace_id: &str,
    event_type: &str,
    payload_json: Value,
    metadata_json: Value,
    created_at: DateTime<Utc>,
) -> WorkspacePlanOutboxRecord {
    WorkspacePlanOutboxRecord {
        id: new_id(),
        plan_id: Some(plan_id.to_string()),
        workspace_id: workspace_id.to_string(),
        event_type: event_type.to_string(),
        payload_json,
        status: "pending".to_string(),
        attempt_count: 0,
        max_attempts: 5,
        lease_owner: None,
        lease_expires_at: None,
        last_error: None,
        next_attempt_at: None,
        processed_at: None,
        metadata_json,
        created_at,
        updated_at: None,
    }
}

pub(super) async fn recover_stale_plan_records_pg(
    repo: &PgWorkspaceRepository,
    workspace_id: &str,
    plan: &WorkspacePlanRecord,
    nodes: &[WorkspacePlanNodeRecord],
    actor_id: &str,
) -> Result<bool, WorkspaceApiError> {
    let outbox = repo
        .list_plan_outbox(&plan.id, 250)
        .await
        .map_err(WorkspaceApiError::internal)?;
    let events = repo
        .list_plan_events(&plan.id, 250)
        .await
        .map_err(WorkspaceApiError::internal)?;
    let Some((outbox_record, event_record)) = stale_plan_node_recovery_records(
        workspace_id,
        plan,
        nodes,
        &outbox,
        &events,
        actor_id,
        Utc::now(),
    ) else {
        return Ok(false);
    };
    repo.enqueue_plan_outbox(outbox_record)
        .await
        .map_err(WorkspaceApiError::internal)?;
    repo.create_plan_event(event_record)
        .await
        .map_err(WorkspaceApiError::internal)?;
    Ok(true)
}

pub(super) fn recover_stale_plan_records_dev(
    state: &mut DevWorkspaceState,
    workspace_id: &str,
    plan: &WorkspacePlanRecord,
    nodes: &[WorkspacePlanNodeRecord],
    actor_id: &str,
    now: DateTime<Utc>,
) -> bool {
    let outbox: Vec<_> = state
        .plan_outbox
        .iter()
        .filter(|item| item.plan_id.as_deref() == Some(plan.id.as_str()))
        .cloned()
        .collect();
    let events: Vec<_> = state
        .plan_events
        .iter()
        .filter(|event| event.plan_id == plan.id)
        .cloned()
        .collect();
    let Some((outbox_record, event_record)) = stale_plan_node_recovery_records(
        workspace_id,
        plan,
        nodes,
        &outbox,
        &events,
        actor_id,
        now,
    ) else {
        return false;
    };
    state.plan_outbox.push(outbox_record);
    state.plan_events.push(event_record);
    true
}

fn stale_plan_node_recovery_records(
    workspace_id: &str,
    plan: &WorkspacePlanRecord,
    nodes: &[WorkspacePlanNodeRecord],
    outbox: &[WorkspacePlanOutboxRecord],
    events: &[WorkspacePlanEventRecord],
    actor_id: &str,
    now: DateTime<Utc>,
) -> Option<(WorkspacePlanOutboxRecord, WorkspacePlanEventRecord)> {
    let node = nodes
        .iter()
        .find(|node| blocked_recovery_node_without_attempt(node))
        .or_else(|| nodes.iter().find(|node| stale_running_node(node, now)))?;
    if !node_has_recovery_execution_target(node)
        || has_supervisor_dispose_decision_for_node(events, &node.id)
        || has_pending_node_recovery_job(outbox, events, workspace_id, plan, node, now)
    {
        return None;
    }
    let root_goal_task_id = nodes
        .iter()
        .find(|candidate| candidate.id == plan.goal_id)
        .and_then(|candidate| candidate.workspace_task_id.clone())
        .unwrap_or_default();
    Some((
        plan_action_outbox(
            &plan.id,
            workspace_id,
            SUPERVISOR_TICK_EVENT,
            json!({
                "workspace_id": workspace_id,
                "actor_user_id": actor_id,
                "root_goal_task_id": root_goal_task_id,
                "retry_node_id": node.id.clone(),
                "retry_attempt_id": node.current_attempt_id.clone(),
                "retry_reason": "stale_plan_node_no_terminal_worker_report",
                "summary": "auto_recovery_stale_plan_node_no_terminal_worker_report"
            }),
            json!({
                "source": "workspace_plan.snapshot_stale_node_recovery",
                "node_id": node.id.clone(),
                "previous_attempt_id": node.current_attempt_id.clone()
            }),
            now,
        ),
        WorkspacePlanEventRecord {
            id: new_id(),
            plan_id: plan.id.clone(),
            workspace_id: workspace_id.to_string(),
            node_id: Some(node.id.clone()),
            attempt_id: node.current_attempt_id.clone(),
            event_type: "auto_stale_node_recovery_queued".to_string(),
            source: "workspace_plan_snapshot".to_string(),
            actor_id: Some(actor_id.to_string()),
            payload_json: json!({
                "reason": "stale_plan_node_without_recoverable_attempt",
                "execution": node.execution.clone()
            }),
            created_at: now,
        },
    ))
}

fn blocked_recovery_node_without_attempt(node: &WorkspacePlanNodeRecord) -> bool {
    if node.intent != "blocked"
        || node.execution != "idle"
        || node.current_attempt_id.is_some()
        || !node_has_recovery_execution_target(node)
    {
        return false;
    }
    let metadata = object_or_empty(node.metadata_json.clone());
    if node_human_intervention_required(&metadata) {
        return false;
    }
    string_from_value(metadata.get("terminal_attempt_retry_reason")).is_some()
        || metadata
            .get("last_verification_passed")
            .and_then(Value::as_bool)
            == Some(false)
        || string_from_value(metadata.get("pipeline_status")).as_deref() == Some("failed")
}

fn stale_running_node(node: &WorkspacePlanNodeRecord, now: DateTime<Utc>) -> bool {
    let threshold_seconds = match node.execution.as_str() {
        "dispatched" => STALE_RECOVERY_DISPATCH_STALE_SECONDS,
        "running" => STALE_RECOVERY_RUNNING_STALE_SECONDS,
        _ => return false,
    };
    let last_update = node.updated_at.unwrap_or(node.created_at);
    now - last_update > Duration::seconds(threshold_seconds)
}

fn node_has_recovery_execution_target(node: &WorkspacePlanNodeRecord) -> bool {
    node.workspace_task_id
        .as_deref()
        .map(|value| !value.trim().is_empty())
        .unwrap_or(false)
        && node
            .assignee_agent_id
            .as_deref()
            .map(|value| !value.trim().is_empty())
            .unwrap_or(false)
}

fn node_human_intervention_required(metadata: &Value) -> bool {
    string_from_value(metadata.get("last_verification_judge_verdict")).as_deref()
        == Some("blocked_human_required")
}

fn has_supervisor_dispose_decision_for_node(
    events: &[WorkspacePlanEventRecord],
    node_id: &str,
) -> bool {
    events.iter().any(|event| {
        event.node_id.as_deref() == Some(node_id)
            && event.event_type == "supervisor_decision_completed"
            && string_from_value(event.payload_json.get("action")).as_deref()
                == Some("dispose_node")
    })
}

fn has_pending_node_recovery_job(
    outbox: &[WorkspacePlanOutboxRecord],
    events: &[WorkspacePlanEventRecord],
    workspace_id: &str,
    plan: &WorkspacePlanRecord,
    node: &WorkspacePlanNodeRecord,
    now: DateTime<Utc>,
) -> bool {
    if outbox.iter().any(|item| {
        item.workspace_id == workspace_id
            && item.plan_id.as_deref() == Some(plan.id.as_str())
            && matches!(
                item.event_type.as_str(),
                HANDOFF_RESUME_EVENT | WORKER_LAUNCH_EVENT | SUPERVISOR_TICK_EVENT
            )
            && matches!(item.status.as_str(), "pending" | "processing" | "failed")
            && payload_targets_node(&item.payload_json, &node.id)
    }) {
        return true;
    }
    let recent_cutoff = now - Duration::seconds(STALE_RECOVERY_RECENT_JOB_SUPPRESSION_SECONDS);
    let previous_attempt_id = node.current_attempt_id.as_deref();
    if outbox.iter().any(|item| {
        item.workspace_id == workspace_id
            && item.plan_id.as_deref() == Some(plan.id.as_str())
            && matches!(
                item.event_type.as_str(),
                HANDOFF_RESUME_EVENT | SUPERVISOR_TICK_EVENT
            )
            && item.status == "completed"
            && item.created_at >= recent_cutoff
            && payload_targets_node(&item.payload_json, &node.id)
            && previous_attempt_id
                .map(|attempt_id| payload_targets_attempt(&item.payload_json, attempt_id))
                .unwrap_or(true)
    }) {
        return true;
    }
    events.iter().any(|event| {
        event.workspace_id == workspace_id
            && event.plan_id == plan.id
            && event.event_type == "auto_stale_node_recovery_queued"
            && event.created_at >= recent_cutoff
            && event.node_id.as_deref() == Some(node.id.as_str())
            && previous_attempt_id
                .map(|attempt_id| event.attempt_id.as_deref() == Some(attempt_id))
                .unwrap_or(true)
    })
}

fn payload_targets_node(payload: &Value, node_id: &str) -> bool {
    string_from_value(payload.get("node_id")).as_deref() == Some(node_id)
        || string_from_value(payload.get("retry_node_id")).as_deref() == Some(node_id)
}

fn payload_targets_attempt(payload: &Value, attempt_id: &str) -> bool {
    string_from_value(payload.get("previous_attempt_id")).as_deref() == Some(attempt_id)
        || string_from_value(payload.get("retry_attempt_id")).as_deref() == Some(attempt_id)
}

pub(super) fn operator_tick_outbox(
    plan_id: &str,
    workspace_id: &str,
    node_id: &str,
    actor_id: &str,
    action: &str,
    reason: Option<&str>,
    created_at: DateTime<Utc>,
) -> WorkspacePlanOutboxRecord {
    plan_action_outbox(
        plan_id,
        workspace_id,
        SUPERVISOR_TICK_EVENT,
        json!({
            "workspace_id": workspace_id,
            "plan_id": plan_id,
            "node_id": node_id,
            "actor_user_id": actor_id,
            "operator_action": action,
            "reason": reason
        }),
        json!({"source": "operator_action"}),
        created_at,
    )
}

pub(super) struct OperatorPlanEventInput<'a> {
    pub(super) plan_id: &'a str,
    pub(super) workspace_id: &'a str,
    pub(super) node_id: &'a str,
    pub(super) attempt_id: Option<String>,
    pub(super) event_type: &'a str,
    pub(super) actor_id: &'a str,
    pub(super) payload_json: Value,
    pub(super) created_at: DateTime<Utc>,
}

pub(super) fn operator_plan_event(input: OperatorPlanEventInput<'_>) -> WorkspacePlanEventRecord {
    let OperatorPlanEventInput {
        plan_id,
        workspace_id,
        node_id,
        attempt_id,
        event_type,
        actor_id,
        payload_json,
        created_at,
    } = input;
    WorkspacePlanEventRecord {
        id: new_id(),
        plan_id: plan_id.to_string(),
        workspace_id: workspace_id.to_string(),
        node_id: Some(node_id.to_string()),
        attempt_id,
        event_type: event_type.to_string(),
        source: "operator".to_string(),
        actor_id: Some(actor_id.to_string()),
        payload_json,
        created_at,
    }
}

pub(super) fn reset_node_for_operator<F>(
    mut node: WorkspacePlanNodeRecord,
    actor_id: &str,
    action: &str,
    reason: Option<&str>,
    now: DateTime<Utc>,
    allow_done_recovery: F,
) -> Result<WorkspacePlanNodeRecord, WorkspaceApiError>
where
    F: Fn(&WorkspacePlanNodeRecord) -> bool,
{
    if node.intent == "done" && !allow_done_recovery(&node) {
        return Err(WorkspaceApiError::bad_request(
            "Invalid workspace plan request",
        ));
    }
    let action_label = if action == "operator_node_reopened" {
        "reopened"
    } else {
        "sent back for replan"
    };
    let confidence = node
        .progress_json
        .get("confidence")
        .and_then(Value::as_f64)
        .unwrap_or(0.0);
    let mut metadata = metadata_map(node.metadata_json.clone());
    clear_operator_metadata(&mut metadata, OPERATOR_CLEARED_RETRY_KEYS);
    clear_operator_metadata(&mut metadata, OPERATOR_CLEARED_ATTEMPT_KEYS);
    metadata.insert(
        "operator_action".to_string(),
        json!({
            "action": action,
            "actor_id": actor_id,
            "reason": reason,
            "created_at": iso(now)
        }),
    );
    node.intent = "todo".to_string();
    node.execution = "idle".to_string();
    node.progress_json = json!({
        "percent": 0,
        "confidence": confidence,
        "note": format!("Operator {action_label}.")
    });
    node.assignee_agent_id = None;
    node.current_attempt_id = None;
    node.feature_checkpoint_json = reset_feature_checkpoint(node.feature_checkpoint_json);
    node.metadata_json = Value::Object(metadata);
    node.completed_at = None;
    node.updated_at = Some(now);
    Ok(node)
}

pub(super) fn done_node_has_recoverable_failure(node: &WorkspacePlanNodeRecord) -> bool {
    if node.intent != "done" {
        return false;
    }
    let failed = |key: &str| {
        matches!(
            normalized_metadata_status(&node.metadata_json, key).as_str(),
            "failed" | "failure" | "error"
        )
    };
    failed("pipeline_status")
        || failed("pipeline_gate_status")
        || failed("source_publish_status")
        || node
            .metadata_json
            .get("last_verification_passed")
            .and_then(Value::as_bool)
            == Some(false)
}

fn normalized_metadata_status(metadata: &Value, key: &str) -> String {
    metadata
        .get(key)
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_ascii_lowercase()
}

pub(super) fn reactivate_plan_for_operator_recovery(
    plan: &mut WorkspacePlanRecord,
    now: DateTime<Utc>,
) -> bool {
    if matches!(plan.status.as_str(), "completed" | "suspended") {
        plan.status = "active".to_string();
        plan.updated_at = Some(now);
        true
    } else {
        false
    }
}

pub(super) fn accept_node_for_operator_review(
    mut node: WorkspacePlanNodeRecord,
    actor_id: &str,
    reason: &str,
    evidence_refs: Vec<String>,
    now: DateTime<Utc>,
) -> Result<WorkspacePlanNodeRecord, WorkspaceApiError> {
    if node.intent == "done" {
        return Err(WorkspaceApiError::bad_request(
            "Invalid workspace plan request",
        ));
    }
    let metadata_value = node.metadata_json.clone();
    let reviewable = node.intent == "blocked"
        || metadata_value
            .get("last_verification_passed")
            .and_then(Value::as_bool)
            == Some(false);
    if !reviewable {
        return Err(WorkspaceApiError::bad_request(
            "Invalid workspace plan request",
        ));
    }
    let previous_refs = string_values(metadata_value.get("verification_evidence_refs"));
    let mut merged_evidence_refs = previous_refs;
    merged_evidence_refs.extend(evidence_refs);
    dedup_truncate(&mut merged_evidence_refs, usize::MAX);

    let mut metadata = metadata_map(metadata_value);
    clear_operator_metadata(&mut metadata, OPERATOR_CLEARED_RETRY_KEYS);
    let review_record = json!({
        "action": "accept_with_human_review",
        "actor_id": actor_id,
        "reason": reason,
        "evidence_refs": merged_evidence_refs,
        "created_at": iso(now)
    });
    metadata.insert("operator_action".to_string(), review_record.clone());
    metadata.insert("human_review_acceptance".to_string(), review_record.clone());
    metadata.insert("last_verification_summary".to_string(), json!(reason));
    metadata.insert("last_verification_passed".to_string(), json!(true));
    metadata.insert("last_verification_hard_fail".to_string(), json!(false));
    metadata.insert(
        "last_verification_judge_verdict".to_string(),
        json!("accepted"),
    );
    metadata.insert(
        "last_verification_judge_rationale".to_string(),
        json!(reason),
    );
    metadata.insert(
        "verification_evidence_refs".to_string(),
        review_record["evidence_refs"].clone(),
    );

    let confidence = node
        .progress_json
        .get("confidence")
        .and_then(Value::as_f64)
        .unwrap_or(0.0)
        .max(0.75);
    node.intent = "done".to_string();
    node.execution = "idle".to_string();
    node.progress_json = json!({
        "percent": 100,
        "confidence": confidence,
        "note": "Accepted after human review."
    });
    node.assignee_agent_id = None;
    node.current_attempt_id = None;
    node.metadata_json = Value::Object(metadata);
    node.completed_at = Some(now);
    node.updated_at = Some(now);
    Ok(node)
}

pub(super) fn apply_human_review_acceptance_to_task(
    task: &mut WorkspaceTaskRecord,
    reason: &str,
    node_metadata: &Value,
    accepted_attempt: Option<&WorkspaceTaskSessionAttemptRecord>,
    now: DateTime<Utc>,
) {
    let mut metadata = metadata_map(task.metadata_json.clone());
    metadata.insert("durable_plan_verdict".to_string(), json!("accepted"));
    metadata.insert(
        "durable_plan_verification_summary".to_string(),
        json!(reason),
    );
    metadata.insert("last_worker_report_type".to_string(), json!("completed"));
    metadata.insert("last_worker_report_summary".to_string(), json!(reason));
    metadata.insert(
        "human_review_acceptance".to_string(),
        node_metadata
            .get("human_review_acceptance")
            .cloned()
            .unwrap_or(Value::Null),
    );
    metadata.insert("pending_leader_adjudication".to_string(), json!(false));
    if let Some(attempt) = accepted_attempt {
        metadata.insert(
            "last_attempt_status".to_string(),
            json!(attempt.status.clone()),
        );
        metadata.insert("last_attempt_id".to_string(), json!(attempt.id.clone()));
        metadata.insert("current_attempt_id".to_string(), json!(attempt.id.clone()));
        metadata.insert(
            "current_attempt_number".to_string(),
            json!(attempt.attempt_number),
        );
    }
    let evidence_refs = string_values(node_metadata.get("verification_evidence_refs"));
    if !evidence_refs.is_empty() {
        metadata.insert("evidence_refs".to_string(), json!(evidence_refs));
    }
    task.status = "done".to_string();
    task.metadata_json = Value::Object(metadata);
    task.completed_at = Some(now);
    task.updated_at = Some(now);
}

pub(super) fn apply_human_review_acceptance_to_node_attempt(
    node: &mut WorkspacePlanNodeRecord,
    attempt: &WorkspaceTaskSessionAttemptRecord,
) {
    let mut metadata = metadata_map(node.metadata_json.clone());
    metadata.insert(
        "last_attempt_status".to_string(),
        json!(attempt.status.clone()),
    );
    metadata.insert("last_attempt_id".to_string(), json!(attempt.id.clone()));
    metadata.insert("accepted_attempt_id".to_string(), json!(attempt.id.clone()));
    metadata.insert(
        "accepted_attempt_number".to_string(),
        json!(attempt.attempt_number),
    );
    node.metadata_json = Value::Object(metadata);
}

fn reset_feature_checkpoint(value: Option<Value>) -> Option<Value> {
    match value {
        Some(Value::Object(mut checkpoint)) => {
            checkpoint.insert("worktree_path".to_string(), Value::Null);
            checkpoint.insert("branch_name".to_string(), Value::Null);
            checkpoint.insert("base_ref".to_string(), json!("HEAD"));
            checkpoint.insert("commit_ref".to_string(), Value::Null);
            Some(Value::Object(checkpoint))
        }
        other => other,
    }
}

fn metadata_map(value: Value) -> Map<String, Value> {
    match value {
        Value::Object(map) => map,
        _ => Map::new(),
    }
}

fn clear_operator_metadata(metadata: &mut Map<String, Value>, keys: &[&str]) {
    for key in keys {
        metadata.remove(*key);
    }
}

pub(super) fn trimmed_evidence_refs(values: &[String]) -> Vec<String> {
    values
        .iter()
        .map(|value| value.trim())
        .filter(|value| !value.is_empty())
        .map(ToOwned::to_owned)
        .collect()
}

pub(super) fn pipeline_target_node<'a>(
    nodes: &'a [WorkspacePlanNodeRecord],
    node_id: Option<&str>,
) -> Option<&'a WorkspacePlanNodeRecord> {
    if let Some(node_id) = node_id {
        return nodes.iter().find(|node| node.id == node_id);
    }
    let mut candidates = nodes
        .iter()
        .filter(|node| {
            matches!(node.kind.as_str(), "task" | "verify")
                && node
                    .metadata_json
                    .get("pipeline_required")
                    .and_then(Value::as_bool)
                    .unwrap_or(false)
        })
        .collect::<Vec<_>>();
    if candidates.is_empty() {
        candidates = nodes
            .iter()
            .filter(|node| matches!(node.kind.as_str(), "task" | "verify"))
            .collect::<Vec<_>>();
    }
    candidates.sort_by(|a, b| {
        pipeline_execution_rank(&a.execution)
            .cmp(&pipeline_execution_rank(&b.execution))
            .then(a.priority.cmp(&b.priority))
            .then(node_updated_or_created(a).cmp(&node_updated_or_created(b)))
    });
    candidates.into_iter().next()
}

fn pipeline_execution_rank(execution: &str) -> i32 {
    match execution {
        "reported" | "verifying" | "running" | "dispatched" => 0,
        _ => 1,
    }
}

fn node_updated_or_created(node: &WorkspacePlanNodeRecord) -> DateTime<Utc> {
    node.updated_at.unwrap_or(node.created_at)
}

pub(super) fn apply_delivery_contract_regeneration(
    metadata_json: &mut Value,
    actor_id: &str,
    reason: Option<&str>,
    now: DateTime<Utc>,
) {
    let mut metadata = match metadata_json.clone() {
        Value::Object(map) => map,
        _ => Map::new(),
    };
    let mut delivery = match metadata.get("delivery_cicd").cloned() {
        Some(Value::Object(map)) => map,
        _ => Map::new(),
    };
    delivery.insert("agent_managed".to_string(), json!(true));
    delivery.insert(
        "contract_source".to_string(),
        json!("agent_regeneration_requested"),
    );
    delivery.insert("contract_confidence".to_string(), json!(0.0));
    delivery.insert("regenerate_requested_at".to_string(), json!(iso(now)));
    delivery.insert("regenerate_requested_by".to_string(), json!(actor_id));
    if let Some(reason) = reason {
        delivery.insert("regenerate_reason".to_string(), json!(reason));
    }
    metadata.insert("delivery_cicd".to_string(), Value::Object(delivery));
    *metadata_json = Value::Object(metadata);
}

pub(super) fn latest_plan_for_workspace<'a>(
    state: &'a DevWorkspaceState,
    workspace_id: &str,
) -> Option<&'a WorkspacePlanRecord> {
    state
        .plans
        .values()
        .filter(|plan| plan.workspace_id == workspace_id)
        .max_by(|a, b| a.created_at.cmp(&b.created_at).then(a.id.cmp(&b.id)))
}

pub(super) fn plan_nodes_for_dev(
    state: &DevWorkspaceState,
    plan_id: &str,
) -> Vec<WorkspacePlanNodeRecord> {
    state
        .plan_nodes
        .values()
        .filter(|node| node.plan_id == plan_id)
        .cloned()
        .collect()
}

pub(super) fn plan_retry_event(
    plan_id: &str,
    workspace_id: &str,
    actor_id: &str,
    outbox_id: &str,
    outbox_event_type: &str,
    reason: Option<&str>,
    created_at: DateTime<Utc>,
) -> WorkspacePlanEventRecord {
    WorkspacePlanEventRecord {
        id: new_id(),
        plan_id: plan_id.to_string(),
        workspace_id: workspace_id.to_string(),
        node_id: None,
        attempt_id: None,
        event_type: "operator_retry_outbox".to_string(),
        source: "operator".to_string(),
        actor_id: Some(actor_id.to_string()),
        payload_json: json!({
            "outbox_id": outbox_id,
            "event_type": outbox_event_type,
            "reason": reason
        }),
        created_at,
    }
}
