use super::*;

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
