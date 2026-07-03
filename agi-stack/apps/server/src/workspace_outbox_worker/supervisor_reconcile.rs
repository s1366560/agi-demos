use super::*;

pub(super) fn reported_reconcilable_node(node: &WorkspacePlanNodeRecord) -> bool {
    if node
        .current_attempt_id
        .as_deref()
        .is_none_or(|attempt_id| attempt_id.trim().is_empty())
    {
        return false;
    }
    let metadata = object_or_empty(node.metadata_json.clone());
    if supervisor_noop_metadata_present(&metadata) {
        return false;
    }
    if node_has_pipeline_gate_in_flight(node, AWAITING_LEADER_ADJUDICATION_STATUS) {
        return false;
    }
    if matches!(
        node.execution.as_str(),
        "dispatched" | "running" | "verifying"
    ) {
        return true;
    }
    node.intent == "in_progress" && node.execution == "idle"
}

pub(super) fn supervisor_retry_same_node_reconcilable_node(node: &WorkspacePlanNodeRecord) -> bool {
    if node
        .current_attempt_id
        .as_deref()
        .is_none_or(|attempt_id| attempt_id.trim().is_empty())
    {
        return false;
    }
    if matches!(
        node.execution.as_str(),
        "dispatched" | "running" | "reported" | "verifying"
    ) {
        return true;
    }
    node.intent == "in_progress" && node.execution == "idle"
}

pub(super) fn supervisor_retry_same_node_summary(
    metadata: &Map<String, Value>,
    attempt: &WorkspaceTaskSessionAttemptRecord,
) -> String {
    metadata_string(metadata.get("last_supervisor_decision_rationale"))
        .or_else(|| attempt.leader_feedback.clone())
        .or_else(|| attempt.candidate_summary.clone())
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "supervisor requested same-node retry".to_string())
}

pub(super) fn supervisor_blocked_human_metadata_present(metadata: &Map<String, Value>) -> bool {
    if metadata_string(metadata.get("last_verification_judge_verdict")).as_deref()
        == Some(SUPERVISOR_BLOCKED_HUMAN_VERDICT)
    {
        return true;
    }
    metadata_string(metadata.get("last_supervisor_decision_action")).as_deref()
        == Some(SUPERVISOR_DECISION_MARK_BLOCKED_HUMAN_ACTION)
        && supervisor_decision_allows_human_block(metadata)
}

pub(super) fn supervisor_decision_allows_human_block(metadata: &Map<String, Value>) -> bool {
    if supervisor_disposition_event_payload(metadata)
        .get("human_required")
        .and_then(Value::as_bool)
        == Some(true)
    {
        return true;
    }
    let Some(Value::Array(items)) = metadata.get("last_supervisor_decision_feedback_items") else {
        return false;
    };
    items.iter().any(|item| {
        let Some(item) = item.as_object() else {
            return false;
        };
        metadata_string(item.get("target_layer")).as_deref() == Some("human")
            || metadata_string(item.get("recommended_action")).as_deref() == Some("escalate_human")
            || metadata_string(item.get("next_action")).as_deref() == Some("human_required")
    })
}

pub(super) fn supervisor_request_pipeline_metadata_present(metadata: &Map<String, Value>) -> bool {
    metadata_string(metadata.get("last_supervisor_decision_action")).as_deref()
        == Some(SUPERVISOR_DECISION_REQUEST_PIPELINE_ACTION)
}

pub(super) fn supervisor_request_pipeline_projection_complete(
    metadata: &Map<String, Value>,
) -> bool {
    metadata_string(metadata.get("supervisor_pipeline_outbox_id")).is_some()
        && matches!(
            metadata_string(metadata.get("pipeline_gate_status"))
                .or_else(|| metadata_string(metadata.get("pipeline_status")))
                .as_deref(),
            Some("requested" | "running" | "success" | "failed")
        )
}

pub(super) fn supervisor_request_pipeline_summary(metadata: &Map<String, Value>) -> String {
    metadata_string(metadata.get("last_supervisor_decision_rationale"))
        .or_else(|| metadata_string(metadata.get("last_verification_summary")))
        .or_else(|| metadata_string(metadata.get(LAST_WORKER_REPORT_SUMMARY)))
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "supervisor requested platform pipeline".to_string())
}

pub(super) fn supervisor_wait_pipeline_metadata_present(metadata: &Map<String, Value>) -> bool {
    metadata_string(metadata.get("last_supervisor_decision_action")).as_deref()
        == Some(SUPERVISOR_DECISION_WAIT_PIPELINE_ACTION)
}

pub(super) fn supervisor_wait_pipeline_projection_complete(metadata: &Map<String, Value>) -> bool {
    let status = metadata_string(metadata.get("pipeline_gate_status"))
        .or_else(|| metadata_string(metadata.get("pipeline_status")))
        .unwrap_or_default()
        .to_ascii_lowercase();
    if matches!(
        status.as_str(),
        "success" | "failed" | "failure" | "error" | "skipped" | "suspended"
    ) {
        return true;
    }
    metadata_string(metadata.get("supervisor_wait_pipeline_reconciled_at")).is_some()
        && matches!(status.as_str(), "requested" | "running" | "processing")
}

pub(super) fn supervisor_wait_pipeline_summary(metadata: &Map<String, Value>) -> String {
    metadata_string(metadata.get("last_supervisor_decision_rationale"))
        .or_else(|| metadata_string(metadata.get("last_verification_summary")))
        .or_else(|| metadata_string(metadata.get(LAST_WORKER_REPORT_SUMMARY)))
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "supervisor waiting for platform pipeline".to_string())
}

pub(super) fn supervisor_noop_metadata_present(metadata: &Map<String, Value>) -> bool {
    metadata_string(metadata.get("last_supervisor_decision_action")).as_deref()
        == Some(SUPERVISOR_DECISION_NOOP_ACTION)
}

pub(super) fn supervisor_noop_projection_complete(metadata: &Map<String, Value>) -> bool {
    metadata_string(metadata.get("supervisor_noop_reconciled_at")).is_some()
}

pub(super) fn supervisor_noop_summary(metadata: &Map<String, Value>) -> String {
    metadata_string(metadata.get("last_supervisor_decision_rationale"))
        .or_else(|| metadata_string(metadata.get("last_verification_summary")))
        .or_else(|| metadata_string(metadata.get(LAST_WORKER_REPORT_SUMMARY)))
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "supervisor chose no state transition".to_string())
}

pub(super) fn metadata_positive_i64(value: Option<&Value>) -> i64 {
    value
        .and_then(Value::as_i64)
        .or_else(|| {
            value
                .and_then(Value::as_u64)
                .and_then(|value| i64::try_from(value).ok())
        })
        .or_else(|| {
            value
                .and_then(Value::as_str)
                .and_then(|raw| raw.trim().parse::<i64>().ok())
        })
        .filter(|value| *value > 0)
        .unwrap_or_default()
}

pub(super) fn supervisor_pipeline_source_commit_ref(
    metadata: &Map<String, Value>,
) -> Option<String> {
    metadata_string(metadata.get("source_publish_source_commit_ref"))
        .or_else(|| metadata_string(metadata.get("verified_commit_ref")))
        .or_else(|| {
            supervisor_disposition_event_payload(metadata)
                .get("source_commit_ref")
                .and_then(Value::as_str)
                .map(str::trim)
                .filter(|value| !value.is_empty())
                .map(ToOwned::to_owned)
        })
}

pub(super) fn supervisor_create_repair_metadata_present(metadata: &Map<String, Value>) -> bool {
    metadata_string(metadata.get("last_supervisor_decision_action")).as_deref()
        == Some(SUPERVISOR_DECISION_CREATE_REPAIR_NODE_ACTION)
}

pub(super) fn supervisor_create_repair_projection_complete(
    node: &WorkspacePlanNodeRecord,
    metadata: &Map<String, Value>,
    nodes_by_id: &HashMap<String, WorkspacePlanNodeRecord>,
) -> bool {
    let Some(repair_node_id) = metadata_string(metadata.get("supervisor_repair_node_id"))
        .or_else(|| metadata_string(metadata.get("blocked_by_repair_node_id")))
    else {
        return false;
    };
    node.current_attempt_id.is_none()
        && node.intent == "todo"
        && node.execution == "idle"
        && node.depends_on_json.iter().any(|id| id == &repair_node_id)
        && nodes_by_id.contains_key(&repair_node_id)
        && metadata_string(metadata.get("workspace_task_projection_status")).as_deref()
            == Some(SUPERVISOR_REPLAN_REQUESTED_VERDICT)
}

pub(super) fn existing_repair_node_id_for_original(
    nodes_by_id: &HashMap<String, WorkspacePlanNodeRecord>,
    original_node_id: &str,
) -> Option<String> {
    let mut ids = nodes_by_id
        .values()
        .filter_map(|node| {
            let metadata = object_or_empty(node.metadata_json.clone());
            (metadata_string(metadata.get("repair_for_node_id")).as_deref()
                == Some(original_node_id))
            .then_some(node.id.clone())
        })
        .collect::<Vec<_>>();
    ids.sort();
    ids.into_iter().next()
}

pub(super) fn supervisor_create_repair_summary(metadata: &Map<String, Value>) -> String {
    metadata_string(metadata.get("last_supervisor_decision_rationale"))
        .or_else(|| metadata_string(metadata.get("last_verification_judge_required_next_action")))
        .or_else(|| metadata_string(metadata.get("last_verification_summary")))
        .or_else(|| metadata_string(metadata.get(LAST_WORKER_REPORT_SUMMARY)))
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "supervisor requested repair node".to_string())
}

pub(super) fn clear_supervisor_create_repair_node_metadata(metadata: &mut Map<String, Value>) {
    for key in [
        "retry_count",
        "retry_last_reason",
        "retry_not_before",
        "terminal_attempt_reconciled_at",
        "terminal_attempt_retry_count",
        "terminal_attempt_retry_reason",
        "terminal_attempt_status",
        "terminal_attempt_superseded_attempt_id",
        "terminal_attempt_superseded_reason",
        "terminal_attempt_superseded_status",
    ] {
        metadata.remove(key);
    }
    clear_attempt_retry_worker_stream_state(metadata);
}

pub(super) fn generated_repair_node_id() -> String {
    let token = generate_uuid_v4()
        .chars()
        .filter(|ch| *ch != '-')
        .take(12)
        .collect::<String>();
    format!("node-{token}")
}

pub(super) fn supervisor_repair_plan_node(
    original: &WorkspacePlanNodeRecord,
    metadata: &Map<String, Value>,
    repair_node_id: &str,
    summary: &str,
    evidence_refs: &[String],
    previous_attempt_id: Option<&str>,
    now: DateTime<Utc>,
) -> WorkspacePlanNodeRecord {
    let title = supervisor_repair_title(original);
    let mut repair_metadata = Map::new();
    repair_metadata.insert(
        "generated_from_verification_failure".to_string(),
        json!(true),
    );
    repair_metadata.insert("repair_for_node_id".to_string(), json!(original.id.clone()));
    repair_metadata.insert(
        "repair_source".to_string(),
        json!("verification_judge_create_repair_node"),
    );
    repair_metadata.insert("repair_trigger".to_string(), json!("verification_failed"));
    repair_metadata.insert(
        "repair_source_iteration_phase".to_string(),
        metadata
            .get("iteration_phase")
            .cloned()
            .unwrap_or_else(|| json!("repair")),
    );
    repair_metadata.insert(
        "source_verification_judge_verdict".to_string(),
        metadata
            .get("last_verification_judge_verdict")
            .cloned()
            .unwrap_or_else(|| json!("needs_rework")),
    );
    repair_metadata.insert(
        "source_verification_judge_next_action_kind".to_string(),
        json!(SUPERVISOR_DECISION_CREATE_REPAIR_NODE_ACTION),
    );
    repair_metadata.insert(
        "source_verification_attempt_id".to_string(),
        previous_attempt_id
            .map(|attempt_id| json!(attempt_id))
            .or_else(|| metadata.get("last_verification_attempt_id").cloned())
            .unwrap_or(Value::Null),
    );
    repair_metadata.insert(
        "repair_failure_signature".to_string(),
        json!(repair_failure_signature(metadata, original)),
    );
    repair_metadata.insert(
        "last_supervisor_decision_action".to_string(),
        json!(SUPERVISOR_DECISION_CREATE_REPAIR_NODE_ACTION),
    );
    repair_metadata.insert(
        "last_supervisor_decision_rationale".to_string(),
        json!(summary),
    );
    copy_optional_metadata_value(
        metadata,
        &mut repair_metadata,
        "last_supervisor_decision_confidence",
    );
    copy_optional_metadata_value(
        metadata,
        &mut repair_metadata,
        "last_supervisor_decision_repair_brief",
    );
    copy_optional_metadata_value(
        metadata,
        &mut repair_metadata,
        "last_verification_judge_repair_brief",
    );
    copy_optional_metadata_value(
        metadata,
        &mut repair_metadata,
        "last_verification_feedback_items",
    );
    copy_optional_metadata_value(
        metadata,
        &mut repair_metadata,
        "last_supervisor_decision_feedback_items",
    );
    if let Some(value) = metadata
        .get("last_supervisor_decision_feedback_items")
        .or_else(|| metadata.get("last_verification_feedback_items"))
        .filter(|value| !value.is_null())
    {
        repair_metadata.insert(
            "source_verification_feedback_items".to_string(),
            value.clone(),
        );
    }
    for key in ["iteration_index", "iteration_phase", "scrum_artifact"] {
        copy_optional_metadata_value(metadata, &mut repair_metadata, key);
    }
    if !evidence_refs.is_empty() {
        repair_metadata.insert(
            "verification_evidence_refs".to_string(),
            json!(evidence_refs),
        );
    }

    WorkspacePlanNodeRecord {
        id: repair_node_id.to_string(),
        plan_id: original.plan_id.clone(),
        parent_id: original.parent_id.clone(),
        kind: "task".to_string(),
        title: title.clone(),
        description: supervisor_repair_description(original, summary),
        depends_on_json: original.depends_on_json.clone(),
        inputs_schema_json: json!({}),
        outputs_schema_json: json!({}),
        acceptance_criteria_json: vec![
            json!(
                "Fresh repair evidence includes a current commit_ref, git diff summary, and verification output."
            ),
        ],
        feature_checkpoint_json: Some(json!({
            "feature_id": format!("feature-{repair_node_id}"),
            "title": title,
            "base_ref": "HEAD"
        })),
        handoff_package_json: None,
        recommended_capabilities_json: original.recommended_capabilities_json.clone(),
        preferred_agent_id: original.preferred_agent_id.clone(),
        estimated_effort_json: original.estimated_effort_json.clone(),
        priority: original.priority.max(1),
        intent: "todo".to_string(),
        execution: "idle".to_string(),
        progress_json: json!({"percent": 0, "confidence": 0.0}),
        assignee_agent_id: None,
        current_attempt_id: None,
        workspace_task_id: None,
        metadata_json: Value::Object(repair_metadata),
        created_at: now,
        updated_at: Some(now),
        completed_at: None,
    }
}

pub(super) fn supervisor_repair_title(original: &WorkspacePlanNodeRecord) -> String {
    format!("Repair {}", original.title)
        .chars()
        .take(120)
        .collect()
}

pub(super) fn supervisor_repair_description(
    original: &WorkspacePlanNodeRecord,
    summary: &str,
) -> String {
    format!(
        "Repair the blockers that prevented verification of `{}`.\n\nRepair execution constraints:\n- Perform the repair in the active attempt worktree only; do not require or attempt edits, merges, or artifact copying in the main checkout or sandbox_code_root.\n- Report only fresh evidence produced during this repair turn.\n\n{}\n\nAfter the repair is complete, the original verification node will re-run.",
        original.title, summary
    )
}

pub(super) fn repair_failure_signature(
    metadata: &Map<String, Value>,
    original: &WorkspacePlanNodeRecord,
) -> String {
    for key in [
        "last_supervisor_decision_feedback_items",
        "last_verification_feedback_items",
    ] {
        let Some(Value::Array(items)) = metadata.get(key) else {
            continue;
        };
        for item in items {
            let Some(item) = item.as_object() else {
                continue;
            };
            if let Some(signature) = metadata_string(item.get("failure_signature")) {
                return signature;
            }
        }
    }
    format!("supervisor-create-repair-node:{}", original.id)
}

pub(super) fn copy_optional_metadata_value(
    source: &Map<String, Value>,
    target: &mut Map<String, Value>,
    key: &str,
) {
    if let Some(value) = source.get(key).filter(|value| !value.is_null()) {
        target.insert(key.to_string(), value.clone());
    }
}

pub(super) fn push_unique_string(values: &mut Vec<String>, value: String) {
    if !values.iter().any(|existing| existing == &value) {
        values.push(value);
    }
}

pub(super) fn supervisor_replan_metadata_present(metadata: &Map<String, Value>) -> bool {
    metadata_string(metadata.get("last_supervisor_decision_action")).as_deref()
        == Some(SUPERVISOR_DECISION_REPLAN_NODE_ACTION)
}

pub(super) fn supervisor_replan_summary(metadata: &Map<String, Value>) -> String {
    metadata_string(metadata.get("last_supervisor_decision_rationale"))
        .or_else(|| metadata_string(metadata.get("last_verification_summary")))
        .or_else(|| metadata_string(metadata.get(LAST_WORKER_REPORT_SUMMARY)))
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "supervisor requested replan".to_string())
}

pub(super) fn clear_supervisor_replan_node_metadata(metadata: &mut Map<String, Value>) {
    for key in [
        "candidate_artifacts",
        "candidate_verifications",
        "deploy_mode",
        "deployment_status",
        "evidence_refs",
        "execution_verifications",
        "external_id",
        "external_provider",
        "external_url",
        "current_repair_turn",
        "last_verification_attempt_id",
        "last_verification_feedback_items",
        "last_verification_hard_fail",
        "last_verification_judge_confidence",
        "last_verification_judge_failed_criteria",
        "last_verification_judge_next_action_kind",
        "last_verification_judge_rationale",
        "last_verification_judge_repair_brief",
        "last_verification_judge_required_next_action",
        "last_verification_judge_verdict",
        "last_verification_passed",
        "last_verification_ran_at",
        "last_verification_summary",
        "last_worker_report_attempt_id",
        "last_worker_report_artifacts",
        "last_worker_report_summary",
        "last_worker_report_type",
        "last_worker_report_verifications",
        "obsolete_by_verifier_feedback",
        "obsolete_feedback_items",
        "pipeline_evidence_refs",
        "pipeline_finished_at",
        "pipeline_gate_status",
        "pipeline_last_summary",
        "pipeline_request_count",
        "pipeline_requested_at",
        "pipeline_run_id",
        "pipeline_status",
        "reported_attempt_reconciled_at",
        "reported_attempt_status",
        "retry_count",
        "retry_last_reason",
        "retry_not_before",
        "source_publish_branch",
        "source_publish_commit_ref",
        "source_publish_provider",
        "source_publish_reason",
        "source_publish_source_commit_ref",
        "source_publish_status",
        "source_publish_token_env",
        "terminal_attempt_reconciled_at",
        "terminal_attempt_retry_count",
        "terminal_attempt_retry_reason",
        "terminal_attempt_status",
        "terminal_attempt_superseded_attempt_id",
        "terminal_attempt_superseded_reason",
        "terminal_attempt_superseded_status",
        "verification_evidence_refs",
        "verification_feedback_disposition",
        "verified_commit_ref",
        "verified_git_diff_summary",
        "verified_test_commands",
        "worktree_integration_attempt_id",
        "worktree_integration_commit_ref",
        "worktree_integration_dirty_signature",
        "worktree_integration_ran_at",
        "worktree_integration_status",
        "worktree_integration_summary",
        "worktree_integration_worktree_path",
    ] {
        metadata.remove(key);
    }
    clear_attempt_retry_worker_stream_state(metadata);
}

pub(super) fn supervisor_blocked_human_summary(metadata: &Map<String, Value>) -> String {
    metadata_string(metadata.get("last_supervisor_decision_rationale"))
        .or_else(|| metadata_string(metadata.get("last_verification_summary")))
        .or_else(|| metadata_string(metadata.get(LAST_WORKER_REPORT_SUMMARY)))
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "human intervention required by workspace supervisor".to_string())
}

pub(super) fn future_metadata_datetime_utc(
    value: Option<&Value>,
    now: DateTime<Utc>,
) -> Option<DateTime<Utc>> {
    let due = value
        .and_then(Value::as_str)
        .and_then(|raw| DateTime::parse_from_rfc3339(raw.trim()).ok())
        .map(|parsed| parsed.with_timezone(&Utc))?;
    (due > now).then_some(due)
}

pub(super) fn is_worker_report_supervisor_tick(
    item: &WorkspacePlanOutboxRecord,
    payload: &Map<String, Value>,
) -> bool {
    string_from_value_object(&item.metadata_json, "source").as_deref() == Some("worker_report")
        && string_from_map(payload, "node_id").is_some()
        && string_from_map(payload, "attempt_id").is_some()
        && string_from_map(payload, "retry_node_id").is_none()
        && string_from_map(payload, "retry_reason").is_none()
}

pub(super) fn attempt_has_candidate_output(attempt: &WorkspaceTaskSessionAttemptRecord) -> bool {
    attempt
        .candidate_summary
        .as_deref()
        .is_some_and(|summary| !summary.trim().is_empty())
        || !attempt.candidate_artifacts_json.is_empty()
        || !attempt.candidate_verifications_json.is_empty()
}

pub(super) fn worker_stream_orphan_report_retry_reason(
    node_metadata: &Map<String, Value>,
    attempt: &WorkspaceTaskSessionAttemptRecord,
) -> Option<String> {
    if metadata_string(node_metadata.get("last_worker_report_type")).as_deref() != Some("blocked")
        || metadata_string(node_metadata.get("launch_state")).as_deref()
            != Some("no_terminal_event")
    {
        return None;
    }
    let summary = attempt.candidate_summary.as_deref()?.trim();
    if !summary.contains("Worker stream stopped without a terminal complete/error event") {
        return None;
    }
    if summary.contains("agent_finished_without_terminal_event") {
        Some("worker_stream_agent_finished_without_terminal_event".to_string())
    } else if summary.contains("agent_not_running_stream_idle") {
        Some("worker_stream_agent_not_running_stream_idle".to_string())
    } else {
        Some("worker_stream_no_terminal_event".to_string())
    }
}

pub(super) fn accepted_projection_already_complete_base(
    node: &WorkspacePlanNodeRecord,
    attempt: &WorkspaceTaskSessionAttemptRecord,
    metadata: &Map<String, Value>,
) -> bool {
    node.intent == "done"
        && node.execution == "idle"
        && metadata
            .get("terminal_attempt_status")
            .and_then(Value::as_str)
            == Some(ACCEPTED_ATTEMPT_STATUS)
        && metadata
            .get("last_verification_attempt_id")
            .and_then(Value::as_str)
            == Some(attempt.id.as_str())
        && accepted_worktree_projection_complete_for_node(node, attempt, &metadata)
}

pub(super) fn accepted_attempt_summary(attempt: &WorkspaceTaskSessionAttemptRecord) -> String {
    attempt
        .leader_feedback
        .as_deref()
        .or(attempt.candidate_summary.as_deref())
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .unwrap_or("accepted terminal attempt")
        .to_string()
}

pub(super) fn done_idle_node_has_accepted_supervisor_judge(node: &WorkspacePlanNodeRecord) -> bool {
    if node.intent != "done" || node.execution != "idle" || node.current_attempt_id.is_none() {
        return false;
    }
    metadata_string(
        object_or_empty(node.metadata_json.clone()).get("last_verification_judge_verdict"),
    )
    .map(|value| value.eq_ignore_ascii_case(ACCEPTED_ATTEMPT_STATUS))
    .unwrap_or(false)
}

pub(super) fn accepted_supervisor_judge_summary(
    node: &WorkspacePlanNodeRecord,
    attempt: &WorkspaceTaskSessionAttemptRecord,
) -> String {
    let metadata = object_or_empty(node.metadata_json.clone());
    metadata_string(metadata.get("last_verification_summary"))
        .or_else(|| attempt.leader_feedback.clone())
        .or_else(|| attempt.candidate_summary.clone())
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "accepted terminal attempt".to_string())
}

pub(super) fn supervisor_dispose_metadata_present(node: &WorkspacePlanNodeRecord) -> bool {
    let metadata = object_or_empty(node.metadata_json.clone());
    metadata_string(metadata.get("last_supervisor_decision_action")).as_deref()
        == Some(SUPERVISOR_DECISION_DISPOSE_NODE_ACTION)
        || metadata_string(metadata.get("verification_feedback_disposition")).as_deref()
            == Some(SUPERVISOR_DISPOSED_NODE_DISPOSITION)
}

pub(super) fn supervisor_disposition_value(metadata: &Map<String, Value>) -> String {
    let event_payload = supervisor_disposition_event_payload(metadata);
    if let Some(disposition) = metadata_string(event_payload.get("disposition")) {
        return disposition.chars().take(120).collect();
    }
    metadata_string(metadata.get("verification_feedback_disposition"))
        .map(|value| value.chars().take(120).collect::<String>())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| SUPERVISOR_DISPOSED_NODE_DISPOSITION.to_string())
}

pub(super) fn supervisor_disposition_summary(metadata: &Map<String, Value>) -> String {
    metadata_string(metadata.get("last_supervisor_decision_rationale"))
        .or_else(|| metadata_string(metadata.get("last_verification_summary")))
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "disposed by workspace supervisor".to_string())
}

pub(super) fn supervisor_disposition_event_payload(
    metadata: &Map<String, Value>,
) -> Map<String, Value> {
    match metadata.get("last_supervisor_decision_event_payload") {
        Some(Value::Object(payload)) => payload.clone(),
        _ => Map::new(),
    }
}

pub(super) fn copy_supervisor_disposition_event_payload_fields(
    node_metadata: &Map<String, Value>,
    task_metadata: &mut Map<String, Value>,
) {
    let event_payload = supervisor_disposition_event_payload(node_metadata);
    for key in [
        "superseded_by_task_id",
        "superseded_by_node_id",
        "disposed_node_id",
    ] {
        if let Some(value) = metadata_string(event_payload.get(key)) {
            task_metadata.insert(key.to_string(), json!(value));
        }
    }
}
