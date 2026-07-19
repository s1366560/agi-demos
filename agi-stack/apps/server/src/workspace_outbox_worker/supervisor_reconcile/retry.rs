use super::super::*;
use super::pipeline::supervisor_noop_metadata_present;

pub(in crate::workspace_outbox_worker) fn reported_reconcilable_node(
    node: &WorkspacePlanNodeRecord,
) -> bool {
    if node
        .current_attempt_id
        .as_deref()
        .is_none_or(|attempt_id| attempt_id.trim().is_empty())
    {
        return false;
    }
    let metadata = object_as_map(&node.metadata_json);
    if supervisor_noop_metadata_present(metadata) {
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

pub(in crate::workspace_outbox_worker) fn supervisor_retry_same_node_reconcilable_node(
    node: &WorkspacePlanNodeRecord,
) -> bool {
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

pub(in crate::workspace_outbox_worker) fn supervisor_retry_same_node_summary(
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

pub(in crate::workspace_outbox_worker) fn future_metadata_datetime_utc(
    value: Option<&Value>,
    now: DateTime<Utc>,
) -> Option<DateTime<Utc>> {
    let due = value
        .and_then(Value::as_str)
        .and_then(|raw| DateTime::parse_from_rfc3339(raw.trim()).ok())
        .map(|parsed| parsed.with_timezone(&Utc))?;
    (due > now).then_some(due)
}

pub(in crate::workspace_outbox_worker) fn is_worker_report_supervisor_tick(
    item: &WorkspacePlanOutboxRecord,
    payload: &Map<String, Value>,
) -> bool {
    string_from_value_object(&item.metadata_json, "source").as_deref() == Some("worker_report")
        && string_from_map(payload, "node_id").is_some()
        && string_from_map(payload, "attempt_id").is_some()
        && string_from_map(payload, "retry_node_id").is_none()
        && string_from_map(payload, "retry_reason").is_none()
}

pub(in crate::workspace_outbox_worker) fn attempt_has_candidate_output(
    attempt: &WorkspaceTaskSessionAttemptRecord,
) -> bool {
    attempt
        .candidate_summary
        .as_deref()
        .is_some_and(|summary| !summary.trim().is_empty())
        || !attempt.candidate_artifacts_json.is_empty()
        || !attempt.candidate_verifications_json.is_empty()
}

pub(in crate::workspace_outbox_worker) fn worker_stream_orphan_report_retry_reason(
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
