use super::*;

#[tokio::test]
async fn supervisor_tick_handler_dispatches_repair_from_blocked_dirty_main_dependency() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_task(task_with_plan_metadata());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.intent = "todo".to_string();
    node.execution = "idle".to_string();
    node.depends_on_json = vec!["repair-node".to_string()];
    node.feature_checkpoint_json = Some(json!({
        "feature_id": "feature-node-test",
        "base_ref": "HEAD"
    }));
    node.metadata_json = json!({
        "blocked_by_repair_node_id": "repair-node"
    });
    store.insert_node(node);
    let mut repair = plan_node();
    repair.id = "repair-node".to_string();
    repair.workspace_task_id = None;
    repair.assignee_agent_id = None;
    repair.intent = "done".to_string();
    repair.execution = "idle".to_string();
    repair.depends_on_json = Vec::new();
    repair.feature_checkpoint_json = Some(json!({
        "feature_id": "feature-repair-node",
        "worktree_path": "/workspace/.memstack/worktrees/attempt-repair-node",
        "commit_ref": "abc1234"
    }));
    repair.metadata_json = json!({
        "repair_for_node_id": "node-test",
        "terminal_attempt_status": "accepted",
        "verified_commit_ref": "abc1234",
        "worktree_integration_commit_ref": "abc1234",
        "worktree_integration_status": "blocked_dirty_main",
        "verification_evidence_refs": ["commit_ref:abc1234"]
    });
    store.insert_node(repair);
    let handler = supervisor_tick_handler(Arc::clone(&store));
    let mut item = outbox("job-supervisor-dirty-dispatch", SUPERVISOR_TICK_EVENT);
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "plan_id": "plan-test",
        "leader_agent_id": WORKSPACE_PLAN_SYSTEM_ACTOR_ID
    });

    let outcome = handler.handle(item).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let node = store.node("node-test");
    assert_eq!(node.intent, "todo");
    assert_eq!(node.execution, "idle");
    assert_eq!(
        node.feature_checkpoint_json
            .as_ref()
            .and_then(|value| value["base_ref"].as_str()),
        Some("abc1234")
    );
    assert_eq!(
        node.metadata_json["dirty_main_dependency_base_ref"],
        "abc1234"
    );
    assert_eq!(
        node.metadata_json["dirty_main_dependency_seed_node_ids"],
        json!(["repair-node"])
    );
    assert_eq!(
        node.metadata_json["dirty_main_dependency_dispatch_status"],
        "queued"
    );
    assert!(node.metadata_json["dirty_main_dependency_dispatch_queued_at"].is_string());
    let queued = store.outbox();
    assert_eq!(queued.len(), 1);
    assert_eq!(queued[0].event_type, ATTEMPT_RETRY_EVENT);
    assert_eq!(queued[0].payload_json["node_id"], "node-test");
    assert_eq!(queued[0].payload_json["task_id"], "task-test");
    assert_eq!(queued[0].payload_json["worker_agent_id"], "agent-worker");
    assert_eq!(
        queued[0].payload_json["retry_reason"],
        "dirty_main_dependency_ready"
    );
    assert_eq!(
        queued[0].metadata_json["source"],
        "workspace_plan.supervisor_tick.retry_admission"
    );
    assert_eq!(
        queued[0].metadata_json["retry_reason"],
        "dirty_main_dependency_ready"
    );
}

#[tokio::test]
async fn supervisor_tick_handler_dispatches_release_candidate_from_dirty_main_dependencies() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_task(task_with_plan_metadata());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.intent = "todo".to_string();
    node.execution = "idle".to_string();
    node.depends_on_json = vec!["dep-a".to_string(), "dep-b".to_string()];
    node.feature_checkpoint_json = Some(json!({
        "feature_id": "feature-release",
        "base_ref": "HEAD"
    }));
    node.metadata_json = json!({
        "iteration_phase": "deploy",
        "scrum_artifact": "release_candidate"
    });
    store.insert_node(node);
    for (dependency_id, commit_ref) in [("dep-a", "aaa1111"), ("dep-b", "bbb2222")] {
        let mut dependency = plan_node();
        dependency.id = dependency_id.to_string();
        dependency.workspace_task_id = None;
        dependency.assignee_agent_id = None;
        dependency.intent = "done".to_string();
        dependency.execution = "idle".to_string();
        dependency.depends_on_json = Vec::new();
        dependency.feature_checkpoint_json = Some(json!({
            "feature_id": format!("feature-{dependency_id}"),
            "worktree_path": format!("/workspace/.memstack/worktrees/attempt-{dependency_id}"),
            "commit_ref": commit_ref
        }));
        dependency.metadata_json = json!({
            "terminal_attempt_status": "accepted",
            "verified_commit_ref": commit_ref,
            "worktree_integration_commit_ref": commit_ref,
            "worktree_integration_status": "blocked_dirty_main",
            "verification_evidence_refs": [format!("commit_ref:{commit_ref}")]
        });
        store.insert_node(dependency);
    }
    let handler = supervisor_tick_handler(Arc::clone(&store));
    let mut item = outbox(
        "job-supervisor-release-dirty-dispatch",
        SUPERVISOR_TICK_EVENT,
    );
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "plan_id": "plan-test",
        "leader_agent_id": WORKSPACE_PLAN_SYSTEM_ACTOR_ID
    });

    let outcome = handler.handle(item).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let node = store.node("node-test");
    assert_eq!(
        node.feature_checkpoint_json
            .as_ref()
            .and_then(|value| value["base_ref"].as_str()),
        Some("bbb2222")
    );
    assert_eq!(
        node.metadata_json["dirty_main_dependency_base_ref"],
        "bbb2222"
    );
    assert_eq!(
        node.metadata_json["dirty_main_dependency_seed_node_ids"],
        json!(["dep-a", "dep-b"])
    );
    let queued = store.outbox();
    assert_eq!(queued.len(), 1);
    assert_eq!(queued[0].event_type, ATTEMPT_RETRY_EVENT);
    assert_eq!(queued[0].payload_json["node_id"], "node-test");
    assert_eq!(
        queued[0].payload_json["retry_reason"],
        "dirty_main_dependency_ready"
    );
}

#[tokio::test]
async fn supervisor_tick_handler_keeps_regular_node_blocked_by_dirty_main_dependency() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_task(task_with_plan_metadata());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.intent = "todo".to_string();
    node.execution = "idle".to_string();
    node.depends_on_json = vec!["dirty-dependency".to_string()];
    node.feature_checkpoint_json = Some(json!({
        "feature_id": "feature-node-test",
        "base_ref": "HEAD"
    }));
    store.insert_node(node);
    let mut dependency = plan_node();
    dependency.id = "dirty-dependency".to_string();
    dependency.workspace_task_id = None;
    dependency.assignee_agent_id = None;
    dependency.intent = "done".to_string();
    dependency.execution = "idle".to_string();
    dependency.depends_on_json = Vec::new();
    dependency.feature_checkpoint_json = Some(json!({
        "feature_id": "feature-dirty-dependency",
        "worktree_path": "/workspace/.memstack/worktrees/attempt-dirty-dependency",
        "commit_ref": "def5678"
    }));
    dependency.metadata_json = json!({
        "terminal_attempt_status": "accepted",
        "verified_commit_ref": "def5678",
        "worktree_integration_commit_ref": "def5678",
        "worktree_integration_status": "blocked_dirty_main",
        "verification_evidence_refs": ["commit_ref:def5678"]
    });
    store.insert_node(dependency);
    let handler = supervisor_tick_handler(Arc::clone(&store));
    let mut item = outbox("job-supervisor-dirty-blocked", SUPERVISOR_TICK_EVENT);
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "plan_id": "plan-test",
        "leader_agent_id": WORKSPACE_PLAN_SYSTEM_ACTOR_ID
    });

    let outcome = handler.handle(item).await.unwrap();

    assert_eq!(
        outcome,
        WorkspacePlanOutboxHandlerOutcome::Release {
            reason: Some("supervisor_tick_requires_full_runtime".to_string())
        }
    );
    let node = store.node("node-test");
    assert_eq!(
        node.feature_checkpoint_json
            .as_ref()
            .and_then(|value| value["base_ref"].as_str()),
        Some("HEAD")
    );
    assert!(node
        .metadata_json
        .get("dirty_main_dependency_dispatch_status")
        .is_none());
    assert!(store.outbox().is_empty());
}
