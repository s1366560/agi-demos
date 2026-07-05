use super::*;

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
