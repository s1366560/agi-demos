use super::*;

#[tokio::test]
async fn pipeline_run_handler_fails_drone_source_publish_without_host_code_root() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_drone_pipeline_contract_missing_host_root());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.execution = "reported".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    node.feature_checkpoint_json = Some(json!({"commit_ref": "abcdef1234567890"}));
    store.insert_node(node);
    let handler = pipeline_run_handler(Arc::clone(&store));

    let outcome = handler.handle(pipeline_run_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let runs = store.pipeline_runs();
    assert_eq!(runs.len(), 1);
    let run = &runs[0];
    assert_eq!(run.provider, DRONE_PROVIDER);
    assert_eq!(run.status, "failed");
    assert_eq!(
        run.reason.as_deref(),
        Some("host_code_root is not available for Drone source publish")
    );
    assert_eq!(run.metadata_json["external_provider"], DRONE_PROVIDER);
    assert_eq!(run.metadata_json["pipeline_failed_stage"], "source_publish");
    assert_eq!(run.metadata_json["source_publish_status"], "failed");
    assert_eq!(run.metadata_json["source_publish_provider"], "git");
    assert_eq!(
        run.metadata_json["source_publish_commit_ref"],
        "abcdef1234567890"
    );
    assert_eq!(
        run.metadata_json["source_publish_source_commit_ref"],
        "abcdef1234567890"
    );
    assert_eq!(
        run.metadata_json["source_publish_reason"],
        "host_code_root is not available for Drone source publish"
    );

    let stages = store.pipeline_stage_runs();
    assert_eq!(stages.len(), 1);
    let stage = &stages[0];
    assert_eq!(stage.run_id, run.id);
    assert_eq!(stage.stage, "source_publish");
    assert_eq!(stage.status, "failed");
    assert_eq!(stage.command.as_deref(), Some("git:publish"));
    assert_eq!(stage.exit_code, Some(1));
    assert_eq!(
        stage.stderr_preview.as_deref(),
        Some("host_code_root is not available for Drone source publish")
    );
    assert_eq!(stage.metadata_json["external_provider"], DRONE_PROVIDER);
    assert_eq!(stage.metadata_json["source_publish_status"], "failed");

    let contract = store.pipeline_contract("workspace-test", "plan-test");
    assert_eq!(contract.provider, DRONE_PROVIDER);
    assert_eq!(contract.metadata_json["source_publish_status"], "failed");
    assert_eq!(
        contract.metadata_json["provider_config"],
        json!({"branch": "main", "repo": "owner/repo"})
    );

    let node = store.node("node-test");
    assert_eq!(node.intent, "in_progress");
    assert_eq!(node.execution, "reported");
    assert_eq!(node.metadata_json["pipeline_status"], "failed");
    assert_eq!(node.metadata_json["pipeline_gate_status"], "failed");
    assert_eq!(
        node.metadata_json["pipeline_failed_stage"],
        "source_publish"
    );
    assert_eq!(node.metadata_json["source_publish_status"], "failed");
    assert_eq!(
        metadata_string_values(node.metadata_json.get("pipeline_evidence_refs")),
        vec![
            "ci_pipeline:failed".to_string(),
            "source_publish:failed".to_string(),
            format!("pipeline_run:failed:{}", run.id)
        ]
    );

    let queued = store.outbox();
    assert_eq!(queued.len(), 1);
    assert_eq!(queued[0].event_type, SUPERVISOR_TICK_EVENT);
    assert_eq!(
        queued[0].metadata_json["source"],
        "workspace_plan.drone_pipeline_run_completed"
    );
    assert_eq!(queued[0].payload_json["pipeline_status"], "failed");
}

#[tokio::test]
async fn pipeline_run_handler_fails_drone_source_publish_without_branch() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_drone_pipeline_contract_missing_branch());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.execution = "reported".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    node.feature_checkpoint_json = Some(json!({"commit_ref": "abcdef1234567890"}));
    store.insert_node(node);
    let handler = pipeline_run_handler(Arc::clone(&store));

    let outcome = handler.handle(pipeline_run_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let run = store.pipeline_runs().into_iter().next().unwrap();
    assert_eq!(run.provider, DRONE_PROVIDER);
    assert_eq!(run.status, "failed");
    assert_eq!(
        run.reason.as_deref(),
        Some("source_control.default_branch or delivery_cicd.drone.branch is required")
    );
    assert_eq!(run.metadata_json["pipeline_failed_stage"], "source_publish");
    assert_eq!(run.metadata_json["source_publish_status"], "failed");
    assert!(run.metadata_json.get("source_publish_branch").is_none());

    let stage = store.pipeline_stage_runs().into_iter().next().unwrap();
    assert_eq!(stage.stage, "source_publish");
    assert_eq!(stage.status, "failed");
    assert_eq!(stage.exit_code, Some(1));
    assert_eq!(
        stage.stderr_preview.as_deref(),
        Some("source_control.default_branch or delivery_cicd.drone.branch is required")
    );

    let contract = store.pipeline_contract("workspace-test", "plan-test");
    assert_eq!(contract.provider, DRONE_PROVIDER);
    assert_eq!(
        contract.metadata_json["provider_config"],
        json!({"repo": "owner/repo"})
    );
    assert_eq!(contract.metadata_json["source_publish_status"], "failed");

    let node = store.node("node-test");
    assert_eq!(node.metadata_json["pipeline_status"], "failed");
    assert_eq!(node.metadata_json["source_publish_provider"], "git");
    assert_eq!(
        node.metadata_json["pipeline_failure_summary"],
        "source_control.default_branch or delivery_cicd.drone.branch is required"
    );
    assert_eq!(
        metadata_string_values(node.metadata_json.get("pipeline_evidence_refs")),
        vec![
            "ci_pipeline:failed".to_string(),
            "source_publish:failed".to_string(),
            format!("pipeline_run:failed:{}", run.id)
        ]
    );
    assert_eq!(
        store.outbox()[0].metadata_json["source"],
        "workspace_plan.drone_pipeline_run_completed"
    );
}

#[tokio::test]
async fn pipeline_run_handler_publishes_drone_source_ref_then_records_provider_unavailable() {
    let Some(fixture) = git_publish_fixture() else {
        return;
    };
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_drone_pipeline_contract_git_publish(
        &fixture.repo,
        &fixture.remote,
    ));
    store.insert_plan(plan());
    let mut node = plan_node();
    node.execution = "reported".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    node.feature_checkpoint_json = Some(json!({"commit_ref": fixture.commit_ref.clone()}));
    store.insert_node(node);
    let handler = pipeline_run_handler(Arc::clone(&store));

    let outcome = handler.handle(pipeline_run_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let pushed = run_git_ok(
        &fixture.root,
        &[
            "--git-dir",
            fixture.remote.to_str().unwrap(),
            "rev-parse",
            "refs/heads/main",
        ],
    )
    .trim()
    .to_string();
    assert_eq!(pushed, fixture.commit_ref);

    let run = store.pipeline_runs().into_iter().next().unwrap();
    assert_eq!(run.provider, DRONE_PROVIDER);
    assert_eq!(run.status, "failed");
    assert_eq!(
        run.reason.as_deref(),
        Some("pipeline provider plugin is not enabled: drone")
    );
    assert_eq!(run.commit_ref.as_deref(), Some(fixture.commit_ref.as_str()));
    assert_eq!(run.metadata_json["source_publish_status"], "published");
    assert_eq!(run.metadata_json["source_publish_provider"], "git");
    assert_eq!(run.metadata_json["source_publish_branch"], "main");
    assert_eq!(
        run.metadata_json["source_publish_commit_ref"],
        fixture.commit_ref.as_str()
    );
    assert_eq!(
        run.metadata_json["source_publish_source_commit_ref"],
        fixture.commit_ref.as_str()
    );
    assert_eq!(
        run.metadata_json["source_publish_token_env"],
        "GITHUB_TOKEN"
    );
    assert_eq!(run.metadata_json["external_provider"], DRONE_PROVIDER);
    assert_eq!(run.metadata_json["plugin_unavailable"], true);
    assert_eq!(run.metadata_json["pipeline_failed_stage"], "drone_plugin");
    assert_eq!(
        run.metadata_json["provider_error"],
        "pipeline provider plugin is not enabled: drone"
    );

    let stages = store.pipeline_stage_runs();
    assert_eq!(stages.len(), 1);
    let stage = &stages[0];
    assert_eq!(stage.stage, "drone_plugin");
    assert_eq!(stage.command.as_deref(), Some("plugin:resolve"));
    assert_eq!(stage.status, "failed");
    assert_eq!(stage.exit_code, Some(1));
    assert_eq!(stage.metadata_json["provider"], DRONE_PROVIDER);
    assert_eq!(stage.metadata_json["external_provider"], DRONE_PROVIDER);
    assert_eq!(stage.metadata_json["plugin_unavailable"], true);

    let contract = store.pipeline_contract("workspace-test", "plan-test");
    assert_eq!(contract.provider, DRONE_PROVIDER);
    assert_eq!(
        contract.metadata_json["provider_config"]["source_publish"]["status"],
        "published"
    );
    assert_eq!(
        contract.metadata_json["provider_config"]["source_publish"]["source_commit_ref"],
        fixture.commit_ref.as_str()
    );

    let node = store.node("node-test");
    assert_eq!(node.intent, "in_progress");
    assert_eq!(node.execution, "reported");
    assert_eq!(node.metadata_json["pipeline_status"], "failed");
    assert_eq!(node.metadata_json["source_publish_status"], "published");
    assert_eq!(node.metadata_json["pipeline_failed_stage"], "drone_plugin");
    assert_eq!(
        metadata_string_values(node.metadata_json.get("pipeline_evidence_refs")),
        vec![
            "ci_pipeline:failed".to_string(),
            "drone:plugin_unavailable".to_string(),
            format!("pipeline_run:failed:{}", run.id)
        ]
    );
    assert_eq!(
        store.outbox()[0].metadata_json["source"],
        "workspace_plan.drone_pipeline_run_completed"
    );
}

#[tokio::test]
async fn pipeline_run_handler_merges_advanced_remote_branch_before_drone_source_publish() {
    let Some(fixture) = git_publish_fixture() else {
        return;
    };
    run_git_ok(
        &fixture.repo,
        &[
            "push",
            fixture.remote.to_str().unwrap(),
            "HEAD:refs/heads/main",
        ],
    );

    let remote_checkout = fixture.root.join("remote-checkout");
    run_git_ok(
        &fixture.root,
        &[
            "clone",
            fixture.remote.to_str().unwrap(),
            remote_checkout.to_str().unwrap(),
        ],
    );
    run_git_ok(&remote_checkout, &["checkout", "-B", "main", "origin/main"]);
    run_git_ok(
        &remote_checkout,
        &["config", "user.email", "remote@example.test"],
    );
    run_git_ok(&remote_checkout, &["config", "user.name", "Remote Test"]);
    std::fs::write(remote_checkout.join("remote.txt"), "remote-only\n").unwrap();
    run_git_ok(&remote_checkout, &["add", "remote.txt"]);
    run_git_ok(&remote_checkout, &["commit", "-m", "remote advance"]);
    let remote_commit = run_git_ok(&remote_checkout, &["rev-parse", "HEAD"])
        .trim()
        .to_string();
    run_git_ok(
        &remote_checkout,
        &["push", "origin", "HEAD:refs/heads/main"],
    );

    std::fs::write(fixture.repo.join("candidate.txt"), "candidate-only\n").unwrap();
    run_git_ok(&fixture.repo, &["add", "candidate.txt"]);
    run_git_ok(&fixture.repo, &["commit", "-m", "candidate change"]);
    let candidate_commit = run_git_ok(&fixture.repo, &["rev-parse", "HEAD"])
        .trim()
        .to_string();

    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_drone_pipeline_contract_git_publish(
        &fixture.repo,
        &fixture.remote,
    ));
    store.insert_plan(plan());
    let mut node = plan_node();
    node.execution = "reported".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    node.feature_checkpoint_json = Some(json!({"commit_ref": candidate_commit.clone()}));
    store.insert_node(node);
    let handler = pipeline_run_handler(Arc::clone(&store));

    let outcome = handler.handle(pipeline_run_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let pushed = run_git_ok(
        &fixture.root,
        &[
            "--git-dir",
            fixture.remote.to_str().unwrap(),
            "rev-parse",
            "refs/heads/main",
        ],
    )
    .trim()
    .to_string();
    assert_ne!(pushed, candidate_commit);
    run_git_ok(
        &fixture.root,
        &[
            "--git-dir",
            fixture.remote.to_str().unwrap(),
            "merge-base",
            "--is-ancestor",
            &candidate_commit,
            "refs/heads/main",
        ],
    );
    run_git_ok(
        &fixture.root,
        &[
            "--git-dir",
            fixture.remote.to_str().unwrap(),
            "merge-base",
            "--is-ancestor",
            &remote_commit,
            "refs/heads/main",
        ],
    );
    assert_eq!(
        run_git_ok(
            &fixture.root,
            &[
                "--git-dir",
                fixture.remote.to_str().unwrap(),
                "show",
                "refs/heads/main:candidate.txt",
            ],
        ),
        "candidate-only\n"
    );
    assert_eq!(
        run_git_ok(
            &fixture.root,
            &[
                "--git-dir",
                fixture.remote.to_str().unwrap(),
                "show",
                "refs/heads/main:remote.txt",
            ],
        ),
        "remote-only\n"
    );

    let run = store.pipeline_runs().into_iter().next().unwrap();
    assert_eq!(run.provider, DRONE_PROVIDER);
    assert_eq!(run.status, "failed");
    assert_eq!(run.commit_ref.as_deref(), Some(candidate_commit.as_str()));
    assert_eq!(run.metadata_json["source_publish_status"], "published");
    assert_eq!(run.metadata_json["source_publish_commit_ref"], pushed);
    assert_eq!(
        run.metadata_json["source_publish_source_commit_ref"],
        candidate_commit
    );
    assert!(run.metadata_json["source_publish_reason"]
        .as_str()
        .is_some_and(|reason| reason.contains("merged remote branch before publish")));

    let contract = store.pipeline_contract("workspace-test", "plan-test");
    assert_eq!(
        contract.metadata_json["provider_config"]["source_publish"]["commit"],
        pushed
    );
    assert_eq!(
        contract.metadata_json["provider_config"]["source_publish"]["source_commit_ref"],
        candidate_commit
    );
    let node = store.node("node-test");
    assert_eq!(node.metadata_json["source_publish_status"], "published");
    assert_eq!(node.metadata_json["source_publish_commit_ref"], pushed);
    assert_eq!(
        node.metadata_json["source_publish_source_commit_ref"],
        candidate_commit
    );
}

#[tokio::test]
async fn pipeline_run_handler_fails_drone_source_publish_when_git_push_fails() {
    let Some(fixture) = git_publish_fixture() else {
        return;
    };
    let missing_remote = fixture.root.join("missing.git");
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_drone_pipeline_contract_git_publish(
        &fixture.repo,
        &missing_remote,
    ));
    store.insert_plan(plan());
    let mut node = plan_node();
    node.execution = "reported".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    node.feature_checkpoint_json = Some(json!({"commit_ref": fixture.commit_ref.clone()}));
    store.insert_node(node);
    let handler = pipeline_run_handler(Arc::clone(&store));

    let outcome = handler.handle(pipeline_run_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let run = store.pipeline_runs().into_iter().next().unwrap();
    assert_eq!(run.provider, DRONE_PROVIDER);
    assert_eq!(run.status, "failed");
    assert!(run
        .reason
        .as_deref()
        .is_some_and(|reason| !reason.is_empty()));
    assert_eq!(run.metadata_json["pipeline_failed_stage"], "source_publish");
    assert_eq!(run.metadata_json["source_publish_status"], "failed");
    assert_eq!(run.metadata_json["source_publish_provider"], "git");
    assert_eq!(run.metadata_json["source_publish_branch"], "main");
    assert_eq!(
        run.metadata_json["source_publish_source_commit_ref"],
        fixture.commit_ref.as_str()
    );

    let stage = store.pipeline_stage_runs().into_iter().next().unwrap();
    assert_eq!(stage.stage, "source_publish");
    assert_eq!(stage.command.as_deref(), Some("git:publish"));
    assert_eq!(stage.status, "failed");
    assert_eq!(stage.exit_code, Some(1));
    assert_eq!(stage.metadata_json["provider"], DRONE_PROVIDER);
    assert_eq!(stage.metadata_json["external_provider"], DRONE_PROVIDER);
    assert_eq!(stage.metadata_json["source_publish_status"], "failed");

    let node = store.node("node-test");
    assert_eq!(node.metadata_json["pipeline_status"], "failed");
    assert_eq!(
        node.metadata_json["pipeline_failed_stage"],
        "source_publish"
    );
    assert_eq!(node.metadata_json["source_publish_status"], "failed");
    assert_eq!(
        metadata_string_values(node.metadata_json.get("pipeline_evidence_refs")),
        vec![
            "ci_pipeline:failed".to_string(),
            "source_publish:failed".to_string(),
            format!("pipeline_run:failed:{}", run.id)
        ]
    );
}
