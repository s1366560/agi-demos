use super::*;

pub(super) async fn roundtrip_plan_outbox(repo: &PgWorkspaceRepository, created_at: DateTime<Utc>) {
    let outbox_now = Utc.with_ymd_and_hms(2026, 1, 2, 4, 0, 0).unwrap();
    repo.enqueue_plan_outbox(WorkspacePlanOutboxRecord {
        id: "plan_outbox_p6_delayed".to_string(),
        plan_id: Some("plan_p6_repo".to_string()),
        workspace_id: "ws_p6_repo".to_string(),
        event_type: "attempt_retry".to_string(),
        payload_json: json!({"node_id": "plan_node_p6"}),
        status: "pending".to_string(),
        attempt_count: 2,
        max_attempts: 5,
        lease_owner: None,
        lease_expires_at: None,
        last_error: Some("retry later".to_string()),
        next_attempt_at: Some(ts(2026, 1, 2, 4, 1, 0)),
        processed_at: None,
        metadata_json: json!({"source": "delayed"}),
        created_at,
        updated_at: None,
    })
    .await
    .unwrap();
    repo.enqueue_plan_outbox(WorkspacePlanOutboxRecord {
        id: "plan_outbox_p6_expired".to_string(),
        plan_id: Some("plan_p6_repo".to_string()),
        workspace_id: "ws_p6_repo".to_string(),
        event_type: "worker_launch".to_string(),
        payload_json: json!({"node_id": "plan_node_p6"}),
        status: "processing".to_string(),
        attempt_count: 1,
        max_attempts: 5,
        lease_owner: Some("old-worker".to_string()),
        lease_expires_at: Some(ts(2026, 1, 2, 3, 59, 59)),
        last_error: Some("stale lease".to_string()),
        next_attempt_at: None,
        processed_at: None,
        metadata_json: json!({"source": "expired"}),
        created_at,
        updated_at: None,
    })
    .await
    .unwrap();
    repo.enqueue_plan_outbox(WorkspacePlanOutboxRecord {
        id: "plan_outbox_p6_release".to_string(),
        plan_id: Some("plan_p6_repo".to_string()),
        workspace_id: "ws_p6_repo".to_string(),
        event_type: "worker_launch".to_string(),
        payload_json: json!({"node_id": "plan_node_p6"}),
        status: "pending".to_string(),
        attempt_count: 0,
        max_attempts: 5,
        lease_owner: None,
        lease_expires_at: None,
        last_error: None,
        next_attempt_at: None,
        processed_at: None,
        metadata_json: json!({"source": "release"}),
        created_at,
        updated_at: None,
    })
    .await
    .unwrap();
    repo.enqueue_plan_outbox(WorkspacePlanOutboxRecord {
        id: "plan_outbox_p6_dead".to_string(),
        plan_id: Some("plan_p6_repo".to_string()),
        workspace_id: "ws_p6_repo".to_string(),
        event_type: "worker_launch".to_string(),
        payload_json: json!({"node_id": "plan_node_p6"}),
        status: "processing".to_string(),
        attempt_count: 5,
        max_attempts: 5,
        lease_owner: Some("worker-a".to_string()),
        lease_expires_at: Some(ts(2026, 1, 2, 4, 1, 0)),
        last_error: None,
        next_attempt_at: None,
        processed_at: None,
        metadata_json: json!({"source": "dead-letter"}),
        created_at,
        updated_at: None,
    })
    .await
    .unwrap();
    repo.enqueue_plan_outbox(WorkspacePlanOutboxRecord {
        id: "plan_outbox_p6_mention_runtime".to_string(),
        plan_id: None,
        workspace_id: "ws_p6_repo".to_string(),
        event_type: "workspace_agent_mention".to_string(),
        payload_json: json!({"conversation_id": "conv_p6_mention"}),
        status: "pending_runtime".to_string(),
        attempt_count: 0,
        max_attempts: 5,
        lease_owner: None,
        lease_expires_at: None,
        last_error: None,
        next_attempt_at: None,
        processed_at: None,
        metadata_json: json!({"source": "mention-runtime"}),
        created_at,
        updated_at: None,
    })
    .await
    .unwrap();
    repo.enqueue_plan_outbox(WorkspacePlanOutboxRecord {
        id: "plan_outbox_p6_mention_response".to_string(),
        plan_id: None,
        workspace_id: "ws_p6_repo".to_string(),
        event_type: "workspace_agent_mention".to_string(),
        payload_json: json!({"final_content": "done"}),
        status: "runtime_response_ready".to_string(),
        attempt_count: 0,
        max_attempts: 5,
        lease_owner: None,
        lease_expires_at: None,
        last_error: None,
        next_attempt_at: None,
        processed_at: None,
        metadata_json: json!({"source": "mention-response"}),
        created_at,
        updated_at: None,
    })
    .await
    .unwrap();
    repo.enqueue_plan_outbox(WorkspacePlanOutboxRecord {
        id: "plan_outbox_p6_mention_writer".to_string(),
        plan_id: None,
        workspace_id: "ws_p6_repo".to_string(),
        event_type: "workspace_agent_mention".to_string(),
        payload_json: json!({"conversation_id": "conv_p6_writer"}),
        status: "pending_runtime".to_string(),
        attempt_count: 0,
        max_attempts: 5,
        lease_owner: None,
        lease_expires_at: None,
        last_error: None,
        next_attempt_at: None,
        processed_at: None,
        metadata_json: json!({"source": "mention-writer"}),
        created_at,
        updated_at: None,
    })
    .await
    .unwrap();
    repo.enqueue_plan_outbox(WorkspacePlanOutboxRecord {
        id: "plan_outbox_p6_mention_error".to_string(),
        plan_id: None,
        workspace_id: "ws_p6_repo".to_string(),
        event_type: "workspace_agent_mention".to_string(),
        payload_json: json!({"runtime_error_detail": "model unavailable"}),
        status: "runtime_error_ready".to_string(),
        attempt_count: 0,
        max_attempts: 5,
        lease_owner: None,
        lease_expires_at: None,
        last_error: None,
        next_attempt_at: None,
        processed_at: None,
        metadata_json: json!({"source": "mention-error"}),
        created_at,
        updated_at: None,
    })
    .await
    .unwrap();
    repo.enqueue_plan_outbox(WorkspacePlanOutboxRecord {
        id: "plan_outbox_p6_future_runtime".to_string(),
        plan_id: None,
        workspace_id: "ws_p6_repo".to_string(),
        event_type: "future_runtime_event".to_string(),
        payload_json: json!({}),
        status: "pending_runtime".to_string(),
        attempt_count: 0,
        max_attempts: 5,
        lease_owner: None,
        lease_expires_at: None,
        last_error: None,
        next_attempt_at: None,
        processed_at: None,
        metadata_json: json!({"source": "future-runtime"}),
        created_at,
        updated_at: None,
    })
    .await
    .unwrap();

    let claimed = repo
        .claim_due_plan_outbox(10, "worker-a", 30, outbox_now)
        .await
        .unwrap();
    let claimed_ids = claimed
        .iter()
        .map(|item| item.id.as_str())
        .collect::<Vec<_>>();
    assert!(claimed_ids.contains(&"plan_outbox_p6"));
    assert!(claimed_ids.contains(&"plan_outbox_p6_expired"));
    assert!(claimed_ids.contains(&"plan_outbox_p6_release"));
    assert!(claimed_ids.contains(&"plan_outbox_p6_mention_runtime"));
    assert!(claimed_ids.contains(&"plan_outbox_p6_mention_response"));
    assert!(claimed_ids.contains(&"plan_outbox_p6_mention_writer"));
    assert!(claimed_ids.contains(&"plan_outbox_p6_mention_error"));
    assert!(!claimed_ids.contains(&"plan_outbox_p6_delayed"));
    assert!(!claimed_ids.contains(&"plan_outbox_p6_dead"));
    assert!(!claimed_ids.contains(&"plan_outbox_p6_future_runtime"));

    let claimed_due = repo
        .get_plan_outbox("plan_outbox_p6")
        .await
        .unwrap()
        .expect("claimed due outbox");
    assert_eq!(claimed_due.status, "processing");
    assert_eq!(claimed_due.attempt_count, 1);
    assert_eq!(claimed_due.lease_owner.as_deref(), Some("worker-a"));
    assert_eq!(claimed_due.lease_expires_at, Some(ts(2026, 1, 2, 4, 0, 30)));

    assert!(repo
        .renew_plan_outbox_lease("plan_outbox_p6", "worker-a", 45, outbox_now)
        .await
        .unwrap());
    assert!(!repo
        .renew_plan_outbox_lease("plan_outbox_p6", "wrong-worker", 45, outbox_now)
        .await
        .unwrap());
    let renewed = repo
        .get_plan_outbox("plan_outbox_p6")
        .await
        .unwrap()
        .expect("renewed outbox");
    assert_eq!(renewed.lease_expires_at, Some(ts(2026, 1, 2, 4, 0, 45)));

    assert!(repo
        .mark_plan_outbox_failed("plan_outbox_p6", "boom", Some("worker-a"), outbox_now)
        .await
        .unwrap());
    let failed = repo
        .get_plan_outbox("plan_outbox_p6")
        .await
        .unwrap()
        .expect("failed outbox");
    assert_eq!(failed.status, "failed");
    assert_eq!(failed.last_error.as_deref(), Some("boom"));
    assert_eq!(failed.next_attempt_at, Some(ts(2026, 1, 2, 4, 0, 2)));

    let retried = repo
        .retry_plan_outbox_now(
            "plan_outbox_p6",
            "ws_p6_repo",
            Some("u_p6_owner"),
            Some("operator retry"),
            outbox_now,
        )
        .await
        .unwrap()
        .expect("retried outbox");
    assert_eq!(retried.status, "pending");
    assert_eq!(retried.attempt_count, 1);
    assert!(retried.next_attempt_at.is_none());
    assert_eq!(
        retried.metadata_json["operator_retry"]["previous_status"],
        "failed"
    );

    let delayed_retry = repo
        .retry_plan_outbox_now(
            "plan_outbox_p6_delayed",
            "ws_p6_repo",
            Some("u_p6_owner"),
            Some("run now"),
            outbox_now,
        )
        .await
        .unwrap()
        .expect("delayed retry");
    assert_eq!(delayed_retry.status, "pending");
    assert!(delayed_retry.next_attempt_at.is_none());
    assert!(delayed_retry.metadata_json["operator_retry"]["previous_next_attempt_at"].is_string());
    assert!(repo
        .retry_plan_outbox_now(
            "plan_outbox_p6_delayed",
            "wrong_workspace",
            Some("u_p6_owner"),
            None,
            outbox_now,
        )
        .await
        .unwrap()
        .is_none());

    assert!(repo
        .release_plan_outbox_processing(
            "plan_outbox_p6_release",
            Some("shutdown"),
            Some("worker-a"),
            outbox_now,
        )
        .await
        .unwrap());
    let released = repo
        .get_plan_outbox("plan_outbox_p6_release")
        .await
        .unwrap()
        .expect("released outbox");
    assert_eq!(released.status, "pending");
    assert_eq!(released.attempt_count, 0);
    assert_eq!(released.last_error.as_deref(), Some("shutdown"));

    assert!(repo
        .park_plan_outbox_processing(
            "plan_outbox_p6_mention_runtime",
            "runtime_bound",
            &json!({
                "runtime_binding": "workspace_agent_mention_conversation",
                "conversation_id": "conv_p6_mention"
            }),
            Some("worker-a"),
            outbox_now,
        )
        .await
        .unwrap());
    let parked_runtime = repo
        .get_plan_outbox("plan_outbox_p6_mention_runtime")
        .await
        .unwrap()
        .expect("parked mention runtime outbox");
    assert_eq!(parked_runtime.status, "runtime_bound");
    assert!(parked_runtime.processed_at.is_none());
    assert!(parked_runtime.lease_owner.is_none());
    assert!(parked_runtime.lease_expires_at.is_none());
    assert_eq!(
        parked_runtime.metadata_json["runtime_binding"],
        "workspace_agent_mention_conversation"
    );
    assert!(repo
        .park_plan_outbox_processing_with_payload_patch(
            "plan_outbox_p6_mention_writer",
            "runtime_response_ready",
            &json!({"runtime_writer": "llm_port_single_turn"}),
            &json!({"final_content": "ready from writer"}),
            Some("worker-a"),
            outbox_now,
        )
        .await
        .unwrap());
    let writer_ready = repo
        .get_plan_outbox("plan_outbox_p6_mention_writer")
        .await
        .unwrap()
        .expect("writer-ready mention outbox");
    assert_eq!(writer_ready.status, "runtime_response_ready");
    assert_eq!(
        writer_ready.payload_json["final_content"],
        "ready from writer"
    );
    assert_eq!(
        writer_ready.metadata_json["runtime_writer"],
        "llm_port_single_turn"
    );
    assert!(writer_ready.processed_at.is_none());
    assert!(repo
        .mark_plan_outbox_completed(
            "plan_outbox_p6_mention_response",
            Some("worker-a"),
            outbox_now
        )
        .await
        .unwrap());
    let completed_response = repo
        .get_plan_outbox("plan_outbox_p6_mention_response")
        .await
        .unwrap()
        .expect("completed mention response");
    assert_eq!(completed_response.status, "completed");
    assert_eq!(completed_response.processed_at, Some(outbox_now));
    assert!(repo
        .mark_plan_outbox_completed("plan_outbox_p6_mention_error", Some("worker-a"), outbox_now)
        .await
        .unwrap());
    let future_runtime = repo
        .get_plan_outbox("plan_outbox_p6_future_runtime")
        .await
        .unwrap()
        .expect("future runtime outbox");
    assert_eq!(future_runtime.status, "pending_runtime");
    assert_eq!(future_runtime.attempt_count, 0);

    assert!(repo
        .mark_plan_outbox_completed("plan_outbox_p6_expired", Some("worker-a"), outbox_now)
        .await
        .unwrap());
    let completed = repo
        .get_plan_outbox("plan_outbox_p6_expired")
        .await
        .unwrap()
        .expect("completed outbox");
    assert_eq!(completed.status, "completed");
    assert_eq!(completed.processed_at, Some(outbox_now));

    assert!(repo
        .mark_plan_outbox_failed(
            "plan_outbox_p6_dead",
            "too many retries",
            Some("worker-a"),
            outbox_now,
        )
        .await
        .unwrap());
    let dead_letter = repo
        .get_plan_outbox("plan_outbox_p6_dead")
        .await
        .unwrap()
        .expect("dead letter outbox");
    assert_eq!(dead_letter.status, "dead_letter");
    assert!(dead_letter.next_attempt_at.is_none());
    let revived = repo
        .retry_plan_outbox_now(
            "plan_outbox_p6_dead",
            "ws_p6_repo",
            Some("u_p6_owner"),
            Some("revive"),
            outbox_now,
        )
        .await
        .unwrap()
        .expect("revived dead letter");
    assert_eq!(revived.status, "pending");
    assert_eq!(revived.attempt_count, 0);
}
