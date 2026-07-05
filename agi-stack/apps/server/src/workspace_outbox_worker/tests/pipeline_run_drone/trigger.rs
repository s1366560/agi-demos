use super::*;

#[tokio::test]
async fn pipeline_run_handler_triggers_and_polls_drone_success() {
    let (server_url, captured) = drone_api_mock(vec![
            (200, r#"{"active":true,"trusted":true}"#),
            (200, r#"[]"#),
            (200, r#"{"number":41,"status":"running"}"#),
            (
                200,
                r#"{"number":41,"status":"success","link":"http://drone.local/owner/repo/41","stages":[{"name":"ci","number":1,"steps":[{"name":"test","number":1,"status":"success","exit_code":0}]}]}"#,
            ),
            (200, r#"[{"out":"cargo test ok\n"}]"#),
        ])
        .await;
    std::env::set_var("AGISTACK_TEST_DRONE_TOKEN_SUCCESS", "token-success");
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_drone_api_pipeline_contract(
        &server_url,
        "AGISTACK_TEST_DRONE_TOKEN_SUCCESS",
    ));
    store.insert_plan(plan());
    store.insert_node(plan_node());
    let handler = pipeline_run_handler(Arc::clone(&store));

    let outcome = handler
        .handle(pipeline_run_item_without_attempt())
        .await
        .unwrap();
    std::env::remove_var("AGISTACK_TEST_DRONE_TOKEN_SUCCESS");

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let run = store.pipeline_runs().into_iter().next().unwrap();
    assert_eq!(run.provider, DRONE_PROVIDER);
    assert_eq!(run.status, "success");
    assert_eq!(run.reason, None);
    assert_eq!(run.commit_ref, None);
    assert_eq!(run.metadata_json["external_provider"], DRONE_PROVIDER);
    assert_eq!(run.metadata_json["external_id"], "owner/repo#41");
    assert_eq!(
        run.metadata_json["external_url"],
        format!("{server_url}/owner/repo/41")
    );
    assert_eq!(run.metadata_json["drone_build_number"], 41);
    assert_eq!(run.metadata_json["drone_status"], "success");
    assert_eq!(run.metadata_json["source_publish_status"], "skipped");

    let stage = store.pipeline_stage_runs().into_iter().next().unwrap();
    assert_eq!(stage.stage, "ci/test");
    assert_eq!(stage.status, "success");
    assert_eq!(stage.command.as_deref(), Some("drone:ci/test"));
    assert_eq!(stage.exit_code, Some(0));
    assert_eq!(stage.stdout_preview.as_deref(), Some("cargo test ok"));
    assert_eq!(stage.metadata_json["drone_stage"], "ci");
    assert_eq!(stage.metadata_json["drone_step"], "test");

    let node = store.node("node-test");
    assert_eq!(node.metadata_json["pipeline_status"], "success");
    assert_eq!(node.metadata_json["pipeline_gate_status"], "success");
    assert_eq!(node.metadata_json["external_id"], "owner/repo#41");
    assert_eq!(
        metadata_string_values(node.metadata_json.get("pipeline_evidence_refs")),
        vec![
            "ci_pipeline:passed".to_string(),
            "drone_build:success:owner/repo#41".to_string(),
            "pipeline_external:drone:owner/repo#41".to_string(),
            "pipeline_stage:ci/test:success".to_string(),
            format!("pipeline_run:success:{}", run.id),
            "pipeline_run_external:drone:owner/repo#41".to_string(),
        ]
    );
    assert_eq!(store.outbox().len(), 1);
    assert_eq!(
        store.outbox()[0].metadata_json["source"],
        "workspace_plan.drone_pipeline_run_completed"
    );

    let requests = captured.lock().await;
    assert_eq!(requests.len(), 5);
    assert!(requests[0].contains("GET /api/repos/owner/repo"));
    assert!(requests[0].contains("authorization: Bearer token-success"));
    assert!(requests[2].contains(
        "POST /api/repos/owner/repo/builds?target=workspace-ci&branch=main&commit=abc123"
    ));
    assert!(requests[4].contains("GET /api/repos/owner/repo/builds/41/logs/1/1"));
}

#[tokio::test]
async fn pipeline_run_handler_triggers_and_polls_drone_via_cli() {
    let fixture = drone_cli_fixture();
    std::env::set_var("AGISTACK_TEST_DRONE_TOKEN_CLI", "token-cli");
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_drone_cli_pipeline_contract(
        "http://drone-cli.local",
        "AGISTACK_TEST_DRONE_TOKEN_CLI",
        &fixture.command,
    ));
    store.insert_plan(plan());
    store.insert_node(plan_node());
    let handler = pipeline_run_handler(Arc::clone(&store));

    let outcome = handler
        .handle(pipeline_run_item_without_attempt())
        .await
        .unwrap();
    std::env::remove_var("AGISTACK_TEST_DRONE_TOKEN_CLI");

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let run = store.pipeline_runs().into_iter().next().unwrap();
    assert_eq!(run.provider, DRONE_PROVIDER);
    assert_eq!(run.status, "success");
    assert_eq!(run.reason, None);
    assert_eq!(run.metadata_json["external_provider"], DRONE_PROVIDER);
    assert_eq!(run.metadata_json["external_id"], "owner/repo#51");
    assert_eq!(
        run.metadata_json["external_url"],
        "http://drone-cli.local/owner/repo/51"
    );
    assert_eq!(run.metadata_json["drone_client"], "cli");
    assert_eq!(run.metadata_json["drone_build_number"], 51);
    assert_eq!(run.metadata_json["drone_status"], "success");

    let stage = store.pipeline_stage_runs().into_iter().next().unwrap();
    assert_eq!(stage.stage, "ci/test");
    assert_eq!(stage.status, "success");
    assert_eq!(stage.command.as_deref(), Some("drone:ci/test"));
    assert_eq!(stage.exit_code, Some(0));
    assert_eq!(stage.stdout_preview.as_deref(), Some("cargo test ok"));

    let node = store.node("node-test");
    assert_eq!(node.metadata_json["pipeline_status"], "success");
    assert_eq!(
        metadata_string_values(node.metadata_json.get("pipeline_evidence_refs")),
        vec![
            "ci_pipeline:passed".to_string(),
            "drone_build:success:owner/repo#51".to_string(),
            "pipeline_external:drone:owner/repo#51".to_string(),
            "pipeline_stage:ci/test:success".to_string(),
            format!("pipeline_run:success:{}", run.id),
            "pipeline_run_external:drone:owner/repo#51".to_string(),
        ]
    );

    let captured = std::fs::read_to_string(&fixture.capture).unwrap();
    assert!(captured.contains("server=http://drone-cli.local token=token-cli args=repo info owner/repo --format {{ json . }}"));
    assert!(captured.contains("args=build ls owner/repo --limit=25 --format {{ json . }}"));
    assert!(captured.contains("args=build create owner/repo --branch=main --commit=abc123 --param=target=workspace-ci --format {{ json . }}"));
    assert!(captured.contains("args=build info owner/repo 51 --format {{ json . }}"));
    assert!(captured.contains("args=log view owner/repo 51 1 1"));
}

#[tokio::test]
async fn pipeline_run_handler_falls_back_to_drone_http_when_cli_is_missing() {
    let (server_url, captured) = drone_api_mock(vec![
            (200, r#"{"active":true,"trusted":true}"#),
            (200, r#"[]"#),
            (200, r#"{"number":52,"status":"running"}"#),
            (
                200,
                r#"{"number":52,"status":"success","link":"http://drone.local/owner/repo/52","stages":[{"name":"ci","number":1,"steps":[{"name":"test","number":1,"status":"success","exit_code":0}]}]}"#,
            ),
            (200, r#"[{"out":"cargo test via fallback\n"}]"#),
        ])
        .await;
    let missing_command =
        std::env::temp_dir().join(format!("agistack-missing-drone-{}", generate_uuid_v4()));
    std::env::set_var(
        "AGISTACK_TEST_DRONE_TOKEN_CLI_FALLBACK",
        "token-cli-fallback",
    );
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_drone_cli_pipeline_contract(
        &server_url,
        "AGISTACK_TEST_DRONE_TOKEN_CLI_FALLBACK",
        &missing_command,
    ));
    store.insert_plan(plan());
    store.insert_node(plan_node());
    let handler = pipeline_run_handler(Arc::clone(&store));

    let outcome = handler
        .handle(pipeline_run_item_without_attempt())
        .await
        .unwrap();
    std::env::remove_var("AGISTACK_TEST_DRONE_TOKEN_CLI_FALLBACK");

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let run = store.pipeline_runs().into_iter().next().unwrap();
    assert_eq!(run.status, "success");
    assert_eq!(run.metadata_json["external_id"], "owner/repo#52");
    assert_eq!(run.metadata_json["drone_client"], "http_fallback");
    let stage = store.pipeline_stage_runs().into_iter().next().unwrap();
    assert_eq!(
        stage.stdout_preview.as_deref(),
        Some("cargo test via fallback")
    );

    let requests = captured.lock().await;
    assert_eq!(requests.len(), 5);
    assert!(requests[0].contains("GET /api/repos/owner/repo"));
    assert!(requests[0].contains("authorization: Bearer token-cli-fallback"));
    assert!(requests[2].contains(
        "POST /api/repos/owner/repo/builds?target=workspace-ci&branch=main&commit=abc123"
    ));
}

#[tokio::test]
async fn pipeline_run_handler_persists_drone_failed_build() {
    let (server_url, _captured) = drone_api_mock(vec![
            (200, r#"{"active":true}"#),
            (200, r#"[]"#),
            (200, r#"{"number":42,"status":"running"}"#),
            (
                200,
                r#"{"number":42,"status":"failure","stages":[{"name":"ci","number":1,"steps":[{"name":"test","number":1,"status":"failure","exit_code":137,"error":"exit 137"}]}]}"#,
            ),
            (200, r#"[{"out":"module not found\nexit 137\n"}]"#),
        ])
        .await;
    std::env::set_var("AGISTACK_TEST_DRONE_TOKEN_FAILURE", "token-failure");
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_drone_api_pipeline_contract(
        &server_url,
        "AGISTACK_TEST_DRONE_TOKEN_FAILURE",
    ));
    store.insert_plan(plan());
    store.insert_node(plan_node());
    let handler = pipeline_run_handler(Arc::clone(&store));

    let outcome = handler
        .handle(pipeline_run_item_without_attempt())
        .await
        .unwrap();
    std::env::remove_var("AGISTACK_TEST_DRONE_TOKEN_FAILURE");

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let run = store.pipeline_runs().into_iter().next().unwrap();
    assert_eq!(run.status, "failed");
    assert_eq!(
        run.reason.as_deref(),
        Some("Drone build owner/repo#42 finished with status failure")
    );
    assert_eq!(run.metadata_json["drone_status"], "failure");
    assert_eq!(run.metadata_json["pipeline_failed_stage"], "ci/test");
    assert_eq!(
        run.metadata_json["pipeline_failure_summary"],
        "Drone build owner/repo#42 finished with status failure"
    );

    let stage = store.pipeline_stage_runs().into_iter().next().unwrap();
    assert_eq!(stage.stage, "ci/test");
    assert_eq!(stage.status, "failed");
    assert_eq!(stage.exit_code, Some(137));
    assert!(stage
        .stderr_preview
        .as_deref()
        .is_some_and(|preview| preview.contains("module not found")));

    let node = store.node("node-test");
    assert_eq!(node.metadata_json["pipeline_status"], "failed");
    assert_eq!(node.metadata_json["pipeline_failed_stage"], "ci/test");
    assert_eq!(
        metadata_string_values(node.metadata_json.get("pipeline_evidence_refs")),
        vec![
            "ci_pipeline:failed".to_string(),
            "drone_build:failure:owner/repo#42".to_string(),
            "pipeline_external:drone:owner/repo#42".to_string(),
            "pipeline_stage:ci/test:failed".to_string(),
            format!("pipeline_run:failed:{}", run.id),
            "pipeline_run_external:drone:owner/repo#42".to_string(),
        ]
    );
}
