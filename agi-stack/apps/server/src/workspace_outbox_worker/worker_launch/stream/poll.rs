use super::*;

pub(super) fn worker_stream_poll_outbox(
    item: &WorkspacePlanOutboxRecord,
    payload: &Map<String, Value>,
    conversation_id: &str,
    replay: &WorkerStreamReplayResult,
    delay_seconds: i64,
    now: DateTime<Utc>,
) -> WorkspacePlanOutboxRecord {
    let mut poll_payload = payload.clone();
    poll_payload.insert("worker_stream_poll".to_string(), json!(true));
    poll_payload.insert("stream_after_id".to_string(), json!(replay.next_after_id()));
    poll_payload.insert(
        "worker_stream_poll_conversation_id".to_string(),
        json!(conversation_id),
    );
    poll_payload.remove("reuse_conversation_id");

    let mut metadata = object_or_empty(item.metadata_json.clone());
    let poll_count = metadata
        .get("stream_poll_count")
        .and_then(Value::as_i64)
        .unwrap_or(0)
        + 1;
    metadata.insert(
        "source".to_string(),
        json!("workspace_plan.worker_launch.stream_poll"),
    );
    metadata.insert(
        "stream_poll_from_outbox_id".to_string(),
        json!(item.id.clone()),
    );
    metadata.insert("stream_poll_count".to_string(), json!(poll_count));
    metadata.insert(
        "stream_poll_after_id".to_string(),
        json!(replay.next_after_id()),
    );
    metadata.insert(
        "stream_poll_conversation_id".to_string(),
        json!(conversation_id),
    );
    metadata.insert(
        "stream_poll_entries_read".to_string(),
        json!(replay.entries_read),
    );

    WorkspacePlanOutboxRecord {
        id: generate_uuid_v4(),
        plan_id: item.plan_id.clone(),
        workspace_id: item.workspace_id.clone(),
        event_type: WORKER_LAUNCH_EVENT.to_string(),
        payload_json: Value::Object(poll_payload),
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
