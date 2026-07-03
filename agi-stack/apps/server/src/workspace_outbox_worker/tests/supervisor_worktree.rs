use super::*;

#[tokio::test]
async fn supervisor_tick_handler_records_already_merged_accepted_worktree() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_code_root("/workspace/app"));
    store.insert_task(task_with_plan_metadata());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.intent = "in_progress".to_string();
    node.execution = "running".to_string();
    node.current_attempt_id = Some("attempt-accepted".to_string());
    node.feature_checkpoint_json = Some(json!({
        "worktree_path": "/workspace/app",
        "branch_name": "attempt-accepted",
        "base_ref": "main",
        "commit_ref": "abcdef1"
    }));
    store.insert_node(node);
    let mut attempt = task_session_attempt(
        "attempt-accepted",
        ACCEPTED_ATTEMPT_STATUS,
        Some("conversation-test"),
    );
    attempt.leader_feedback = Some("accepted in main checkout".to_string());
    attempt.candidate_artifacts_json = vec!["commit_ref:abcdef1234567890".to_string()];
    store.insert_attempt(attempt);
    let handler = supervisor_tick_handler(Arc::clone(&store));
    let mut item = outbox("job-supervisor-tick", SUPERVISOR_TICK_EVENT);
    item.plan_id = Some("plan-test".to_string());
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "plan_id": "plan-test"
    });

    let outcome = handler.handle(item).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let node = store.node("node-test");
    let task = store.task("task-test");
    assert_eq!(node.intent, "done");
    assert_eq!(task.status, "done");
    assert_eq!(
        node.metadata_json["worktree_integration_status"],
        "already_merged"
    );
    assert_eq!(
        task.metadata_json["worktree_integration_worktree_path"],
        "/workspace/app"
    );
    assert_eq!(
        task.metadata_json["worktree_integration_summary"],
        "accepted attempt already ran in sandbox_code_root"
    );
    let events = store.plan_events();
    assert_eq!(events.len(), 1);
    assert_eq!(
        events[0].event_type,
        "accepted_worktree_integration_skipped"
    );
    assert_eq!(
        events[0].source,
        "workspace_plan.accepted_worktree_integration"
    );
    assert_eq!(events[0].payload_json["status"], "already_merged");
    assert_eq!(events[0].payload_json["commit_ref"], "abcdef1234567890");
    assert_eq!(events[0].payload_json["worktree_path"], "/workspace/app");
    assert!(store.outbox().is_empty());
}

#[tokio::test]
async fn supervisor_tick_handler_integrates_accepted_attempt_worktree() {
    let Some(fixture) = git_publish_fixture() else {
        return;
    };
    let worktree_path = fixture.root.join(".memstack/worktrees/attempt-accepted");
    std::fs::create_dir_all(worktree_path.parent().unwrap()).unwrap();
    run_git_ok(
        &fixture.repo,
        &[
            "worktree",
            "add",
            "-b",
            "attempt-accepted",
            worktree_path.to_str().unwrap(),
            "HEAD",
        ],
    );
    std::fs::write(worktree_path.join("accepted.txt"), "accepted work\n").unwrap();
    run_git_ok(&worktree_path, &["add", "accepted.txt"]);
    run_git_ok(&worktree_path, &["commit", "-m", "accepted work"]);
    let candidate_commit = run_git_ok(&worktree_path, &["rev-parse", "HEAD"])
        .trim()
        .to_string();

    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_code_root(fixture.repo.to_str().unwrap()));
    store.insert_task(task_with_plan_metadata());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.intent = "in_progress".to_string();
    node.execution = "running".to_string();
    node.current_attempt_id = Some("attempt-accepted".to_string());
    node.feature_checkpoint_json = Some(json!({
        "worktree_path": worktree_path.to_str().unwrap(),
        "branch_name": "attempt-accepted",
        "base_ref": "main",
        "commit_ref": candidate_commit
    }));
    store.insert_node(node);
    let mut attempt = task_session_attempt(
        "attempt-accepted",
        ACCEPTED_ATTEMPT_STATUS,
        Some("conversation-test"),
    );
    attempt.leader_feedback = Some("accepted in isolated worktree".to_string());
    attempt.candidate_artifacts_json = vec![format!("commit_ref:{candidate_commit}")];
    store.insert_attempt(attempt);
    let handler = supervisor_tick_handler(Arc::clone(&store));
    let mut item = outbox("job-supervisor-tick", SUPERVISOR_TICK_EVENT);
    item.plan_id = Some("plan-test".to_string());
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "plan_id": "plan-test"
    });

    let outcome = handler.handle(item).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let node = store.node("node-test");
    let task = store.task("task-test");
    assert_eq!(node.intent, "done");
    assert_eq!(node.execution, "idle");
    assert_eq!(node.current_attempt_id.as_deref(), Some("attempt-accepted"));
    assert_eq!(task.status, "done");
    assert_eq!(node.metadata_json["worktree_integration_status"], "merged");
    assert_eq!(
        node.metadata_json["worktree_integration_commit_ref"],
        candidate_commit
    );
    assert_eq!(
        task.metadata_json["worktree_integration_worktree_path"],
        worktree_path.to_str().unwrap()
    );
    assert_eq!(
        run_git_ok(&fixture.repo, &["rev-parse", "HEAD"])
            .trim()
            .to_string(),
        candidate_commit
    );
    assert_eq!(
        std::fs::read_to_string(fixture.repo.join("accepted.txt")).unwrap(),
        "accepted work\n"
    );
    let events = store.plan_events();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].event_type, "accepted_worktree_integrated");
    assert_eq!(events[0].payload_json["status"], "merged");
    assert!(store.outbox().is_empty());
}

#[tokio::test]
async fn supervisor_tick_handler_retries_blocked_accepted_worktree_when_main_is_clean() {
    let Some(fixture) = git_publish_fixture() else {
        return;
    };
    let worktree_path = fixture.root.join(".memstack/worktrees/attempt-accepted");
    std::fs::create_dir_all(worktree_path.parent().unwrap()).unwrap();
    run_git_ok(
        &fixture.repo,
        &[
            "worktree",
            "add",
            "-b",
            "attempt-accepted",
            worktree_path.to_str().unwrap(),
            "HEAD",
        ],
    );
    std::fs::write(worktree_path.join("accepted.txt"), "accepted work\n").unwrap();
    run_git_ok(&worktree_path, &["add", "accepted.txt"]);
    run_git_ok(&worktree_path, &["commit", "-m", "accepted work"]);
    let candidate_commit = run_git_ok(&worktree_path, &["rev-parse", "HEAD"])
        .trim()
        .to_string();
    std::fs::write(fixture.repo.join("dirty.txt"), "local dirty\n").unwrap();

    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_code_root(fixture.repo.to_str().unwrap()));
    store.insert_task(task_with_plan_metadata());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.intent = "in_progress".to_string();
    node.execution = "running".to_string();
    node.current_attempt_id = Some("attempt-accepted".to_string());
    node.feature_checkpoint_json = Some(json!({
        "worktree_path": worktree_path.to_str().unwrap(),
        "branch_name": "attempt-accepted",
        "base_ref": "main",
        "commit_ref": candidate_commit
    }));
    store.insert_node(node);
    let mut attempt = task_session_attempt(
        "attempt-accepted",
        ACCEPTED_ATTEMPT_STATUS,
        Some("conversation-test"),
    );
    attempt.leader_feedback = Some("accepted in isolated worktree".to_string());
    attempt.candidate_artifacts_json = vec![format!("commit_ref:{candidate_commit}")];
    store.insert_attempt(attempt);
    let handler = supervisor_tick_handler(Arc::clone(&store));
    let mut item = outbox("job-supervisor-tick", SUPERVISOR_TICK_EVENT);
    item.plan_id = Some("plan-test".to_string());
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "plan_id": "plan-test"
    });

    let outcome = handler.handle(item).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let node = store.node("node-test");
    let task = store.task("task-test");
    assert_eq!(node.intent, "done");
    assert_eq!(node.execution, "idle");
    assert_eq!(task.status, "done");
    assert_eq!(
        node.metadata_json["worktree_integration_status"],
        "blocked_dirty_main"
    );
    assert_eq!(
        task.metadata_json["worktree_integration_commit_ref"],
        candidate_commit
    );
    assert!(node.metadata_json["worktree_integration_dirty_signature"].is_string());
    assert!(node.metadata_json["worktree_integration_summary"]
        .as_str()
        .unwrap()
        .contains("sandbox_code_root has uncommitted changes"));
    assert_eq!(
        run_git_ok(&fixture.repo, &["rev-parse", "HEAD"])
            .trim()
            .to_string(),
        fixture.commit_ref
    );
    assert!(!fixture.repo.join("accepted.txt").exists());
    let events = store.plan_events();
    assert_eq!(events.len(), 1);
    assert_eq!(
        events[0].event_type,
        "accepted_worktree_integration_blocked"
    );
    assert_eq!(events[0].payload_json["status"], "blocked_dirty_main");
    assert!(store.outbox().is_empty());

    std::fs::remove_file(fixture.repo.join("dirty.txt")).unwrap();
    let mut item = outbox("job-supervisor-tick-retry", SUPERVISOR_TICK_EVENT);
    item.plan_id = Some("plan-test".to_string());
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "plan_id": "plan-test"
    });

    let outcome = handler.handle(item).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let node = store.node("node-test");
    let task = store.task("task-test");
    assert_eq!(node.intent, "done");
    assert_eq!(node.execution, "idle");
    assert_eq!(task.status, "done");
    assert_eq!(node.metadata_json["worktree_integration_status"], "merged");
    assert_eq!(
        node.metadata_json["worktree_integration_commit_ref"],
        candidate_commit
    );
    assert_eq!(
        run_git_ok(&fixture.repo, &["rev-parse", "HEAD"])
            .trim()
            .to_string(),
        candidate_commit
    );
    assert_eq!(
        std::fs::read_to_string(fixture.repo.join("accepted.txt")).unwrap(),
        "accepted work\n"
    );
    let events = store.plan_events();
    assert_eq!(events.len(), 2);
    assert_eq!(events[1].event_type, "accepted_worktree_integrated");
    assert_eq!(events[1].payload_json["status"], "merged");
}

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

#[tokio::test]
async fn supervisor_tick_handler_preserves_failed_worktree_when_commit_ref_was_missing() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_task(task_with_plan_metadata());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.intent = "done".to_string();
    node.execution = "idle".to_string();
    node.current_attempt_id = Some("attempt-accepted".to_string());
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
        "worktree_integration_summary": "status=failed\ncommit_ref not found in attempt worktree"
    });
    store.insert_node(node);
    let mut attempt = task_session_attempt(
        "attempt-accepted",
        ACCEPTED_ATTEMPT_STATUS,
        Some("conversation-test"),
    );
    attempt.candidate_artifacts_json = vec!["commit_ref:abcdef1234567890".to_string()];
    store.insert_attempt(attempt);
    let handler = supervisor_tick_handler(Arc::clone(&store));
    let mut item = outbox("job-supervisor-tick", SUPERVISOR_TICK_EVENT);
    item.plan_id = Some("plan-test".to_string());
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "plan_id": "plan-test"
    });

    let outcome = handler.handle(item).await.unwrap();

    assert_eq!(
        outcome,
        WorkspacePlanOutboxHandlerOutcome::Release {
            reason: Some("supervisor_tick_requires_full_runtime".to_string())
        }
    );
    let node = store.node("node-test");
    assert_eq!(node.intent, "done");
    assert_eq!(node.execution, "idle");
    assert_eq!(node.metadata_json["worktree_integration_status"], "failed");
    assert!(store.plan_events().is_empty());
    assert!(store.outbox().is_empty());
}

#[tokio::test]
async fn supervisor_tick_handler_skips_accepted_attempt_with_commit_mismatch() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_task(task_with_plan_metadata());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.intent = "in_progress".to_string();
    node.execution = "running".to_string();
    node.current_attempt_id = Some("attempt-accepted".to_string());
    node.feature_checkpoint_json = Some(json!({"commit_ref": "abcdef1"}));
    store.insert_node(node);
    let mut attempt = task_session_attempt(
        "attempt-accepted",
        ACCEPTED_ATTEMPT_STATUS,
        Some("conversation-test"),
    );
    attempt.candidate_artifacts_json = vec!["commit_ref:1234567890abcdef".to_string()];
    store.insert_attempt(attempt);
    let handler = supervisor_tick_handler(Arc::clone(&store));
    let mut item = outbox("job-supervisor-tick", SUPERVISOR_TICK_EVENT);
    item.plan_id = Some("plan-test".to_string());
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "plan_id": "plan-test"
    });

    let outcome = handler.handle(item).await.unwrap();

    assert_eq!(
        outcome,
        WorkspacePlanOutboxHandlerOutcome::Release {
            reason: Some("supervisor_tick_requires_full_runtime".to_string())
        }
    );
    let node = store.node("node-test");
    assert_eq!(node.intent, "in_progress");
    assert_eq!(node.execution, "running");
    assert_eq!(node.current_attempt_id.as_deref(), Some("attempt-accepted"));
    let task = store.task("task-test");
    assert_eq!(task.status, "todo");
    assert!(store.outbox().is_empty());
}
