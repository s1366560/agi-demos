use super::*;

pub(in crate::workspace_api) fn accept_node_for_operator_review(
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

pub(in crate::workspace_api) fn apply_human_review_acceptance_to_task(
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

pub(in crate::workspace_api) fn apply_human_review_acceptance_to_node_attempt(
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

pub(in crate::workspace_api) fn trimmed_evidence_refs(values: &[String]) -> Vec<String> {
    values
        .iter()
        .map(|value| value.trim())
        .filter(|value| !value.is_empty())
        .map(ToOwned::to_owned)
        .collect()
}
