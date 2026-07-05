use super::*;

#[tokio::test]
async fn pipeline_run_handler_fails_drone_yaml_preflight_for_non_string_command() {
    let fixture = drone_yaml_fixture(
        r#"
kind: pipeline
type: docker
name: default
steps:
  - name: ci
    image: alpine
    commands:
      - echo ok
      - label: value
"#,
    );
    let (server_url, captured) = drone_api_mock(vec![]).await;
    std::env::set_var("AGISTACK_TEST_DRONE_TOKEN_PREFLIGHT", "token-preflight");
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_drone_api_pipeline_contract_with_host_root(
        &server_url,
        "AGISTACK_TEST_DRONE_TOKEN_PREFLIGHT",
        Some(&fixture.root),
    ));
    store.insert_plan(plan());
    store.insert_node(plan_node());
    let handler = pipeline_run_handler(Arc::clone(&store));

    let outcome = handler
        .handle(pipeline_run_item_without_attempt())
        .await
        .unwrap();
    std::env::remove_var("AGISTACK_TEST_DRONE_TOKEN_PREFLIGHT");

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    assert!(captured.lock().await.is_empty());
    let run = store.pipeline_runs().into_iter().next().unwrap();
    assert_eq!(run.status, "failed");
    assert!(run
        .reason
        .as_deref()
        .is_some_and(|reason| reason.contains("commands[1] must be a string")));
    assert_eq!(
        run.metadata_json["drone_preflight"],
        DRONE_YAML_PREFLIGHT_VALIDATION
    );
    assert_eq!(run.metadata_json["drone_preflight_status"], "failed");
    assert_eq!(
        run.metadata_json["pipeline_failed_stage"],
        "drone_preflight"
    );

    let stage = store.pipeline_stage_runs().into_iter().next().unwrap();
    assert_eq!(stage.stage, "drone_preflight");
    assert_eq!(stage.status, "failed");
    assert_eq!(stage.command.as_deref(), Some("drone:preflight .drone.yml"));
    assert!(stage
        .stderr_preview
        .as_deref()
        .is_some_and(|preview| preview.contains("commands[1] must be a string")));

    let node = store.node("node-test");
    assert_eq!(node.metadata_json["pipeline_status"], "failed");
    assert_eq!(
        node.metadata_json["pipeline_failed_stage"],
        "drone_preflight"
    );
    let evidence = metadata_string_values(node.metadata_json.get("pipeline_evidence_refs"));
    assert!(evidence.contains(&"ci_pipeline:failed".to_string()));
    assert!(evidence.contains(&"drone:preflight_failed".to_string()));
    assert!(evidence.contains(&"drone_config:.drone.yml".to_string()));
    assert!(evidence.contains(&"drone_error:yaml_unmarshal_into_string".to_string()));
}

#[tokio::test]
async fn pipeline_run_handler_fails_drone_yaml_preflight_for_missing_deploy_service() {
    let fixture = drone_yaml_fixture(
        r#"
kind: pipeline
type: docker
name: default
steps:
  - name: docker-build-web
    image: plugins/docker
    commands:
      - docker build -t registry.local/app-web:abc .
  - name: deploy
    image: docker:cli
    commands:
      - docker run -d --name other-service registry.local/other-service:abc
"#,
    );
    let (server_url, captured) = drone_api_mock(vec![]).await;
    std::env::set_var(
        "AGISTACK_TEST_DRONE_TOKEN_PREFLIGHT_DEPLOY",
        "token-preflight-deploy",
    );
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(
        workspace_with_drone_docker_deploy_pipeline_contract_with_host_root(
            &server_url,
            "AGISTACK_TEST_DRONE_TOKEN_PREFLIGHT_DEPLOY",
            Some(&fixture.root),
        ),
    );
    store.insert_plan(plan());
    store.insert_node(plan_node());
    let handler = pipeline_run_handler(Arc::clone(&store));

    let outcome = handler
        .handle(pipeline_run_item_without_attempt())
        .await
        .unwrap();
    std::env::remove_var("AGISTACK_TEST_DRONE_TOKEN_PREFLIGHT_DEPLOY");

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    assert!(captured.lock().await.is_empty());
    let run = store.pipeline_runs().into_iter().next().unwrap();
    assert_eq!(run.status, "failed");
    assert_eq!(run.metadata_json["deployment_status"], "invalid");
    assert_eq!(
        run.metadata_json["deploy_preflight_validation"],
        DRONE_YAML_PREFLIGHT_VALIDATION
    );
    assert!(run.metadata_json["deploy_validation_failure"]
        .as_str()
        .is_some_and(|failure| failure.contains("required services: app-web")));
    assert!(run
        .reason
        .as_deref()
        .is_some_and(|reason| reason.contains("required services: app-web")));

    let node = store.node("node-test");
    assert_eq!(node.metadata_json["pipeline_status"], "failed");
    assert_eq!(node.metadata_json["deployment_status"], "invalid");
    let evidence = metadata_string_values(node.metadata_json.get("pipeline_evidence_refs"));
    assert!(evidence.contains(&"ci_pipeline:failed".to_string()));
    assert!(evidence.contains(&"drone:preflight_failed".to_string()));
    assert!(evidence.contains(&"drone_error:docker_deploy_missing_required_service".to_string()));
    assert!(evidence.contains(&"deployment:invalid:docker".to_string()));
}
