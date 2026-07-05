use super::*;

#[tokio::test]
async fn pipeline_run_handler_trusts_repo_and_marks_docker_deploy_success() {
    let (server_url, captured) = drone_api_mock(vec![
            (200, r#"{"active":true,"trusted":false}"#),
            (200, r#"{"active":true,"trusted":false}"#),
            (200, r#"{"active":true,"trusted":true}"#),
            (200, r#"[]"#),
            (200, r#"{"number":43,"status":"running"}"#),
            (
                200,
                r#"{"number":43,"status":"success","stages":[{"name":"docker-build-web","number":1,"steps":[{"name":"build","number":1,"status":"success","exit_code":0}]},{"name":"deploy","number":2,"steps":[{"name":"deploy","number":1,"status":"success","exit_code":0}]}]}"#,
            ),
            (
                200,
                r#"[{"out":"docker build -t registry.local/app-web:abc .\n"}]"#,
            ),
            (
                200,
                r#"[{"out":"docker run -d --name app-web registry.local/app-web:abc\n"}]"#,
            ),
        ])
        .await;
    std::env::set_var("AGISTACK_TEST_DRONE_TOKEN_DEPLOY_SUCCESS", "token-deploy");
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_drone_docker_deploy_pipeline_contract(
        &server_url,
        "AGISTACK_TEST_DRONE_TOKEN_DEPLOY_SUCCESS",
    ));
    store.insert_plan(plan());
    store.insert_node(plan_node());
    let handler = pipeline_run_handler(Arc::clone(&store));

    let outcome = handler
        .handle(pipeline_run_item_without_attempt())
        .await
        .unwrap();
    std::env::remove_var("AGISTACK_TEST_DRONE_TOKEN_DEPLOY_SUCCESS");

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let run = store.pipeline_runs().into_iter().next().unwrap();
    assert_eq!(run.status, "success");
    assert_eq!(run.metadata_json["deploy_enabled"], true);
    assert_eq!(run.metadata_json["deploy_mode"], "docker");
    assert_eq!(run.metadata_json["deploy_stage"], "deploy");
    assert_eq!(run.metadata_json["deploy_target"], "production");
    assert_eq!(run.metadata_json["deployment_status"], "deployed");
    assert_eq!(
        run.metadata_json["deploy_validation"],
        DRONE_DOCKER_DEPLOY_VALIDATION
    );
    let stages = store.pipeline_stage_runs();
    let deploy_stage = stages
        .iter()
        .find(|stage| stage.stage == "deploy")
        .expect("deploy stage should be persisted");
    assert_eq!(deploy_stage.status, "success");
    assert_eq!(deploy_stage.metadata_json["drone_step_kind"], "deploy");
    assert_eq!(deploy_stage.metadata_json["deploy_mode"], "docker");

    let node = store.node("node-test");
    assert_eq!(node.metadata_json["pipeline_status"], "success");
    assert_eq!(node.metadata_json["deployment_status"], "deployed");
    assert_eq!(
        node.metadata_json["deploy_validation"],
        DRONE_DOCKER_DEPLOY_VALIDATION
    );
    assert_eq!(
        metadata_string_values(node.metadata_json.get("pipeline_evidence_refs")),
        vec![
            "ci_pipeline:passed".to_string(),
            "drone_build:success:owner/repo#43".to_string(),
            "pipeline_external:drone:owner/repo#43".to_string(),
            "pipeline_stage:docker-build-web/build:success".to_string(),
            "pipeline_stage:deploy:success".to_string(),
            "deployment:passed:docker".to_string(),
            "deployment_target:production".to_string(),
            format!("pipeline_run:success:{}", run.id),
            "pipeline_run_external:drone:owner/repo#43".to_string(),
        ]
    );

    let requests = captured.lock().await;
    assert_eq!(requests.len(), 8);
    assert!(requests[2].contains("PATCH /api/repos/owner/repo"));
    assert!(requests[2].contains(r#""trusted":true"#));
    assert!(requests[4].contains("POST /api/repos/owner/repo/builds?"));
    assert!(requests[4].contains("MEMSTACK_DEPLOY_ENABLED=true"));
    assert!(requests[4].contains("MEMSTACK_DEPLOY_MODE=docker"));
    assert!(requests[4].contains("MEMSTACK_DEPLOY_STAGE=deploy"));
    assert!(requests[4].contains("MEMSTACK_DEPLOY_TARGET=production"));
    assert!(requests[4].contains("MEMSTACK_DEPLOY_DOCKER_HOST_PORT=18080"));
    assert!(requests[4].contains("MEMSTACK_DEPLOY_DOCKER_LABELS=blue%2Cgreen"));
    assert!(requests[4].contains("target=production"));
}

#[tokio::test]
async fn pipeline_run_handler_fails_required_docker_deploy_without_run_marker() {
    let (server_url, _captured) = drone_api_mock(vec![
            (200, r#"{"active":true,"trusted":true}"#),
            (200, r#"{"active":true,"trusted":true}"#),
            (200, r#"[]"#),
            (200, r#"{"number":44,"status":"running"}"#),
            (
                200,
                r#"{"number":44,"status":"success","stages":[{"name":"deploy","number":1,"steps":[{"name":"deploy","number":1,"status":"success","exit_code":0}]}]}"#,
            ),
            (200, r#"[{"out":"echo app-web deployed\n"}]"#),
        ])
        .await;
    std::env::set_var(
        "AGISTACK_TEST_DRONE_TOKEN_DEPLOY_INVALID",
        "token-deploy-invalid",
    );
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_drone_docker_deploy_pipeline_contract(
        &server_url,
        "AGISTACK_TEST_DRONE_TOKEN_DEPLOY_INVALID",
    ));
    store.insert_plan(plan());
    store.insert_node(plan_node());
    let handler = pipeline_run_handler(Arc::clone(&store));

    let outcome = handler
        .handle(pipeline_run_item_without_attempt())
        .await
        .unwrap();
    std::env::remove_var("AGISTACK_TEST_DRONE_TOKEN_DEPLOY_INVALID");

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let run = store.pipeline_runs().into_iter().next().unwrap();
    assert_eq!(run.status, "failed");
    assert_eq!(run.metadata_json["deployment_status"], "invalid");
    assert_eq!(
        run.metadata_json["deploy_validation_failure"],
        "missing docker run/compose/stack/service deploy command"
    );
    assert_eq!(
            run.reason.as_deref(),
            Some(
                "Drone build owner/repo#44 deploy stage deploy did not implement docker deployment semantics: missing docker run/compose/stack/service deploy command"
            )
        );

    let node = store.node("node-test");
    assert_eq!(node.metadata_json["pipeline_status"], "failed");
    assert_eq!(node.metadata_json["deployment_status"], "invalid");
    assert_eq!(
        metadata_string_values(node.metadata_json.get("pipeline_evidence_refs")),
        vec![
            "ci_pipeline:failed".to_string(),
            "drone_build:success:owner/repo#44".to_string(),
            "pipeline_external:drone:owner/repo#44".to_string(),
            "pipeline_stage:deploy:success".to_string(),
            "deployment:invalid:docker".to_string(),
            "deployment_target:production".to_string(),
            format!("pipeline_run:failed:{}", run.id),
            "pipeline_run_external:drone:owner/repo#44".to_string(),
        ]
    );
}
