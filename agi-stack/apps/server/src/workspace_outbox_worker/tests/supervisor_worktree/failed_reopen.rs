use super::*;

#[tokio::test]
async fn supervisor_tick_handler_reopens_failed_worktree_integration_done_node() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_task(task_with_plan_metadata());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.intent = "done".to_string();
    node.execution = "idle".to_string();
    node.current_attempt_id = Some("attempt-accepted".to_string());
    node.completed_at = Some(Utc.with_ymd_and_hms(2026, 1, 2, 4, 5, 6).unwrap());
    node.feature_checkpoint_json = Some(json!({
        "worktree_path": "/workspace/.memstack/worktrees/attempt-accepted",
        "branch_name": "workspace/node-attempt-accepted",
        "base_ref": "main",
        "commit_ref": "abcdef1"
    }));
    node.metadata_json = json!({
        "terminal_attempt_status": "accepted",
        "last_verification_passed": true,
        "last_verification_attempt_id": "attempt-accepted",
        "verified_commit_ref": "abcdef1234567890",
        "worktree_integration_attempt_id": "attempt-accepted",
        "worktree_integration_status": "failed",
        "worktree_integration_commit_ref": "abcdef1234567890",
        "worktree_integration_worktree_path": "/workspace/.memstack/worktrees/attempt-accepted",
        "worktree_integration_dirty_signature": Value::Null,
        "worktree_integration_summary": "Exit code: 128\nstatus=failed\nreason=merge_failed_aborted\nfatal: refusing to merge unrelated histories",
        "candidate_artifacts": ["commit_ref:abcdef1234567890"]
    });
    store.insert_node(node);
    let handler = supervisor_tick_handler(Arc::clone(&store));
    let mut item = outbox("job-supervisor-tick", SUPERVISOR_TICK_EVENT);
    item.plan_id = Some("plan-test".to_string());
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "plan_id": "plan-test",
        "leader_agent_id": WORKSPACE_PLAN_SYSTEM_ACTOR_ID,
        "extra_instructions": "retry failed accepted worktree integration"
    });

    let outcome = handler.handle(item).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let node = store.node("node-test");
    assert_eq!(node.intent, "todo");
    assert_eq!(node.execution, "idle");
    assert!(node.current_attempt_id.is_none());
    assert!(node.assignee_agent_id.is_none());
    assert!(node.completed_at.is_none());
    let checkpoint = node.feature_checkpoint_json.unwrap();
    assert!(checkpoint["worktree_path"].is_null());
    assert!(checkpoint["branch_name"].is_null());
    assert_eq!(checkpoint["base_ref"], "HEAD");
    assert!(checkpoint["commit_ref"].is_null());
    assert_eq!(node.metadata_json["last_verification_passed"], false);
    assert_eq!(
        node.metadata_json["terminal_attempt_retry_reason"],
        "worktree_integration_failed"
    );
    assert_eq!(
        node.metadata_json["worktree_integration_failed_previous_attempt_id"],
        "attempt-accepted"
    );
    assert_eq!(
        node.metadata_json["worktree_integration_failed_previous_commit_ref"],
        "abcdef1234567890"
    );
    assert!(node
        .metadata_json
        .get("worktree_integration_status")
        .is_none());
    assert!(node.metadata_json.get("candidate_artifacts").is_none());

    let events = store.plan_events();
    assert_eq!(events.len(), 1);
    assert_eq!(
        events[0].event_type,
        "worktree_integration_failed_done_node_reopened"
    );
    assert_eq!(events[0].source, "workspace_plan_supervisor_tick");
    assert_eq!(
        events[0].payload_json["previous_attempt_id"],
        "attempt-accepted"
    );
    assert_eq!(
        events[0].payload_json["previous_commit_ref"],
        "abcdef1234567890"
    );

    let queued = store.outbox();
    assert_eq!(queued.len(), 1);
    assert_eq!(queued[0].event_type, ATTEMPT_RETRY_EVENT);
    assert_eq!(queued[0].payload_json["node_id"], "node-test");
    assert_eq!(
        queued[0].payload_json["previous_attempt_id"],
        "attempt-accepted"
    );
    assert_eq!(
        queued[0].payload_json["retry_reason"],
        "worktree_integration_failed"
    );
}
