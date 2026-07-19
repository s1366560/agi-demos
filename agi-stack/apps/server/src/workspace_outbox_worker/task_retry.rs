use super::*;

mod outbox;

const ATTEMPT_RETRY_STALE_WORKER_STREAM_METADATA_KEYS: &[&str] = &[
    "current_attempt_conversation_id",
    "evidence_refs",
    "execution_verifications",
    "last_worker_report_artifacts",
    "last_worker_report_attempt_id",
    "last_worker_report_fingerprint",
    "last_worker_report_summary",
    "last_worker_report_type",
    "last_worker_report_verifications",
    "last_worker_reported_at",
    "pending_leader_adjudication",
    "worker_launch_admitted_at",
    "worker_launch_bound_at",
    "worker_stream_idle_finished_message_id",
    "worker_stream_idle_progress_published_at",
    "worker_stream_idle_progress_published_at_us",
    "worker_stream_idle_progress_summary",
    "worker_stream_idle_running_exists",
    "worker_stream_idle_seconds",
    "worker_stream_last_entry_id",
    "worker_stream_last_event_time_us",
    "worker_stream_last_event_type",
    "worker_stream_last_replayed_at",
    "worker_stream_message_id",
    "worker_stream_replay_attempt_id",
    "worker_stream_replay_status",
    "worker_stream_terminal_launch_state",
    "worker_stream_terminal_outcome",
    "worker_stream_terminal_replayed_at",
    "worker_stream_terminal_should_report",
];

pub(super) use outbox::{
    supervisor_replan_tick_outbox, supervisor_request_pipeline_outbox,
    supervisor_retry_attempt_outbox, worker_report_supervisor_tick,
    SupervisorReplanTickOutboxInput,
};

pub(super) fn terminal_attempt_pending_pipeline_verification(
    node: &WorkspacePlanNodeRecord,
    status: &str,
) -> bool {
    if node_waiting_for_verification_retry(node) {
        return true;
    }
    if node_has_pipeline_gate_in_flight(node, status) {
        return true;
    }
    if node.execution != "reported" || status == "accepted" {
        return false;
    }
    let metadata = object_as_map(&node.metadata_json);
    let pipeline_status = metadata_string(metadata.get("pipeline_status"))
        .unwrap_or_default()
        .to_ascii_lowercase();
    if !matches!(
        pipeline_status.as_str(),
        "failed" | "failure" | "error" | "success"
    ) {
        return false;
    }
    metadata_string(metadata.get("pipeline_run_id")).is_some()
        || metadata_string(metadata.get("external_id")).is_some()
}

pub(super) fn node_waiting_for_verification_retry(node: &WorkspacePlanNodeRecord) -> bool {
    node.execution == "reported"
        && node
            .metadata_json
            .get("retry_verification_only")
            .and_then(Value::as_bool)
            == Some(true)
}

pub(super) fn node_has_pipeline_gate_in_flight(
    node: &WorkspacePlanNodeRecord,
    status: &str,
) -> bool {
    if status == "accepted" || node.intent != "in_progress" {
        return false;
    }
    let metadata = object_as_map(&node.metadata_json);
    let pipeline_status = metadata_string(metadata.get("pipeline_status"))
        .unwrap_or_default()
        .to_ascii_lowercase();
    let gate_status = metadata_string(metadata.get("pipeline_gate_status"))
        .unwrap_or_default()
        .to_ascii_lowercase();
    matches!(
        pipeline_status.as_str(),
        "requested" | "running" | "processing"
    ) || matches!(gate_status.as_str(), "requested" | "running" | "processing")
}

pub(super) fn copy_retry_context_payload_fields(
    source: &Map<String, Value>,
    target: &mut Map<String, Value>,
) {
    for key in [
        "previous_attempt_id",
        "retry_attempt_id",
        "retry_reason",
        "retry_origin",
        "worker_stream_orphan_retry_reason",
        "worker_stream_orphan_summary",
    ] {
        if let Some(value) = source.get(key).filter(|value| !value.is_null()) {
            target.insert(key.to_string(), value.clone());
        }
    }
}

pub(super) fn should_reset_attempt_retry_worker_state(
    event_type: &str,
    payload: &Map<String, Value>,
) -> bool {
    event_type == ATTEMPT_RETRY_EVENT
        && (string_from_map(payload, "retry_reason").is_some()
            || string_from_map(payload, "previous_attempt_id").is_some()
            || string_from_map(payload, "retry_attempt_id").is_some()
            || metadata_string(payload.get("retry_origin")).is_some()
            || metadata_string(payload.get("worker_stream_orphan_retry_reason")).is_some()
            || metadata_string(payload.get("worker_stream_orphan_summary")).is_some())
}

pub(super) fn clear_attempt_retry_worker_stream_state(metadata: &mut Map<String, Value>) {
    for key in ATTEMPT_RETRY_STALE_WORKER_STREAM_METADATA_KEYS {
        metadata.remove(*key);
    }
}

pub(super) fn worker_stream_replay_metadata_matches_attempt(
    metadata: &Map<String, Value>,
    attempt_id: &str,
) -> bool {
    string_from_map(metadata, "worker_stream_replay_attempt_id")
        .or_else(|| string_from_map(metadata, LAST_WORKER_REPORT_ATTEMPT_ID))
        .as_deref()
        .is_none_or(|recorded_attempt_id| recorded_attempt_id == attempt_id)
}

pub(super) fn copy_metadata_string_field(
    source: &Map<String, Value>,
    target: &mut Map<String, Value>,
    key: &str,
) {
    if let Some(value) = metadata_string(source.get(key)) {
        target.insert(key.to_string(), json!(value));
    }
}

pub(super) fn apply_attempt_retry_context(
    metadata: &mut Map<String, Value>,
    payload: &Map<String, Value>,
    now: DateTime<Utc>,
) {
    let mut has_retry_context = false;
    if let Some(retry_reason) = string_from_map(payload, "retry_reason") {
        metadata.insert("last_retry_reason".to_string(), json!(retry_reason));
        has_retry_context = true;
    }
    if let Some(previous_attempt_id) = string_from_map(payload, "previous_attempt_id")
        .or_else(|| string_from_map(payload, "retry_attempt_id"))
    {
        metadata.insert(
            "last_retry_previous_attempt_id".to_string(),
            json!(previous_attempt_id),
        );
        has_retry_context = true;
    }
    for key in [
        "retry_origin",
        "worker_stream_orphan_retry_reason",
        "worker_stream_orphan_summary",
    ] {
        if let Some(value) = metadata_string(payload.get(key)) {
            metadata.insert(key.to_string(), json!(value));
            has_retry_context = true;
        }
    }
    if has_retry_context {
        metadata.insert("last_retry_context_at".to_string(), json!(now.to_rfc3339()));
    }
}

pub(super) fn release_node_for_terminal_retry(
    node: &mut WorkspacePlanNodeRecord,
    reason: &str,
    now: DateTime<Utc>,
    max_retries: i64,
) -> bool {
    let mut metadata = object_or_empty(node.metadata_json.clone());
    let retry_count = metadata
        .get("terminal_attempt_retry_count")
        .and_then(Value::as_i64)
        .unwrap_or(0)
        + 1;
    metadata.insert(
        "terminal_attempt_retry_count".to_string(),
        json!(retry_count),
    );
    metadata.insert("terminal_attempt_retry_reason".to_string(), json!(reason));
    metadata.insert(
        "terminal_attempt_reconciled_at".to_string(),
        json!(now.to_rfc3339()),
    );
    metadata.remove("retry_not_before");

    let retry_exhausted = retry_count > max_retries;
    node.intent = if retry_exhausted {
        "blocked".to_string()
    } else {
        "todo".to_string()
    };
    node.execution = "idle".to_string();
    node.current_attempt_id = None;
    node.metadata_json = Value::Object(metadata);
    node.updated_at = Some(now);
    retry_exhausted
}

pub(super) fn plan_terminal_attempt_max_retries() -> i64 {
    positive_i64_env(
        PLAN_TERMINAL_ATTEMPT_MAX_RETRIES_ENV,
        DEFAULT_PLAN_TERMINAL_ATTEMPT_MAX_RETRIES,
    )
}
