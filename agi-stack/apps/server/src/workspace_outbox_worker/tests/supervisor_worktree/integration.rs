use super::*;

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
