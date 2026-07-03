use super::*;

#[tokio::test]
async fn pipeline_stage_run_store_persists_finish_result() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    let started = Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap();
    let completed = Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 7).unwrap();
    let stage_run = WorkspacePlanDispatchStore::create_pipeline_stage_run(
        &*store,
        pipeline_stage_run_record("pipeline-stage-run-test", "pipeline-run-test"),
    )
    .await
    .unwrap();
    assert_eq!(stage_run.status, "running");
    assert_eq!(stage_run.started_at, Some(started));

    let artifact_refs = vec![
        "pipeline_log:test:sandbox://pipeline/run/test.log".to_string(),
        "artifact:test:coverage".to_string(),
    ];
    let finished = WorkspacePlanDispatchStore::finish_pipeline_stage_run(
        &*store,
        "pipeline-stage-run-test",
        "success",
        Some(0),
        Some("ok"),
        Some(""),
        Some("sandbox://pipeline/run/test.log"),
        &artifact_refs,
        &json!({"duration_ms_observed": 1800, "service_id": null}),
        completed,
    )
    .await
    .unwrap()
    .expect("stage run finished");

    assert_eq!(finished.status, "success");
    assert_eq!(finished.exit_code, Some(0));
    assert_eq!(finished.stdout_preview.as_deref(), Some("ok"));
    assert_eq!(finished.stderr_preview.as_deref(), Some(""));
    assert_eq!(
        finished.log_ref.as_deref(),
        Some("sandbox://pipeline/run/test.log")
    );
    assert_eq!(finished.artifact_refs_json, artifact_refs);
    assert_eq!(finished.completed_at, Some(completed));
    assert_eq!(finished.duration_ms, Some(2_000));
    assert_eq!(finished.updated_at, Some(completed));
    assert_eq!(finished.metadata_json["required"], true);
    assert_eq!(finished.metadata_json["duration_ms_observed"], 1800);
    assert!(finished.metadata_json["service_id"].is_null());

    let persisted = store.pipeline_stage_run("pipeline-stage-run-test");
    assert_eq!(persisted, finished);
}

#[tokio::test]
async fn pipeline_run_handler_reflects_existing_success_run_to_node() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.intent = "in_progress".to_string();
    node.execution = "reported".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    node.metadata_json = json!({
        "iteration_phase": "test",
        "pipeline_evidence_refs": ["existing:evidence"]
    });
    store.insert_node(node);
    store.insert_pipeline_run(pipeline_run_record(
        "pipeline-run-success",
        "success",
        Some("attempt-test"),
        Some("abcdef1234567890"),
        json!({
            "source_publish_source_commit_ref": "abcdef1234567890",
            "source_publish_status": "published",
            "external_url": "https://ci.example/runs/pipeline-run-success",
            "external_provider": "sandbox_native",
            "pipeline_last_summary": "existing run already passed"
        }),
    ));
    let handler = pipeline_run_handler(Arc::clone(&store));

    let outcome = handler.handle(pipeline_run_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let node = store.node("node-test");
    assert_eq!(node.intent, "done");
    assert_eq!(node.execution, "idle");
    assert_eq!(
        node.metadata_json["pipeline_run_id"],
        "pipeline-run-success"
    );
    assert_eq!(node.metadata_json["pipeline_status"], "success");
    assert_eq!(node.metadata_json["pipeline_gate_status"], "success");
    assert_eq!(
        node.metadata_json["source_publish_source_commit_ref"],
        "abcdef1234567890"
    );
    assert_eq!(node.metadata_json["source_publish_status"], "published");
    assert_eq!(
        node.metadata_json["external_url"],
        "https://ci.example/runs/pipeline-run-success"
    );
    assert_eq!(
        node.metadata_json["pipeline_last_summary"],
        "existing run already passed"
    );
    assert_eq!(
        node.metadata_json["last_verification_summary"],
        "harness-native CI/CD pipeline passed"
    );
    assert_eq!(node.metadata_json["last_verification_passed"], true);
    assert_eq!(node.metadata_json["last_verification_hard_fail"], false);
    assert!(node.metadata_json["last_verification_ran_at"].is_string());
    assert_eq!(
        node.metadata_json["pipeline_evidence_refs"],
        json!([
            "existing:evidence",
            "ci_pipeline:passed",
            "pipeline_run:success:pipeline-run-success"
        ])
    );
    assert!(node.metadata_json.get("pipeline_requested_at").is_none());
}

#[tokio::test]
async fn pipeline_run_handler_marks_existing_running_run_on_node() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.intent = "in_progress".to_string();
    node.execution = "reported".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    node.feature_checkpoint_json = Some(json!({"commit_ref": "abcdef1234567890"}));
    store.insert_node(node);
    store.insert_pipeline_run(pipeline_run_record(
        "pipeline-run-running",
        "running",
        Some("attempt-test"),
        Some("abcdef1234567890"),
        json!({"source_publish_source_commit_ref": "abcdef1234567890"}),
    ));
    let handler = pipeline_run_handler(Arc::clone(&store));

    let outcome = handler.handle(pipeline_run_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let node = store.node("node-test");
    assert_eq!(node.intent, "in_progress");
    assert_eq!(node.execution, "idle");
    assert_eq!(
        node.metadata_json["pipeline_run_id"],
        "pipeline-run-running"
    );
    assert_eq!(node.metadata_json["pipeline_status"], "running");
    assert_eq!(node.metadata_json["pipeline_gate_status"], "running");
    assert!(node.metadata_json["pipeline_started_at"].is_string());
    assert!(node.metadata_json.get("pipeline_requested_at").is_none());
    assert!(node.metadata_json.get("last_verification_passed").is_none());
}

#[tokio::test]
async fn pipeline_run_handler_ignores_running_run_with_commit_mismatch() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_pipeline_contract());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.execution = "reported".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    node.feature_checkpoint_json = Some(json!({"commit_ref": "abcdef1234567890"}));
    store.insert_node(node);
    store.insert_pipeline_run(pipeline_run_record(
        "pipeline-run-running-stale",
        "running",
        Some("attempt-test"),
        Some("bbbbbb1234567890"),
        json!({"source_publish_source_commit_ref": "bbbbbb1234567890"}),
    ));
    let handler = pipeline_run_handler(Arc::clone(&store));

    let outcome = handler.handle(pipeline_run_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let node = store.node("node-test");
    assert_eq!(node.execution, "idle");
    assert_eq!(node.metadata_json["pipeline_status"], "running");
    assert_eq!(node.metadata_json["pipeline_gate_status"], "running");
    let new_run_id = node.metadata_json["pipeline_run_id"].as_str().unwrap();
    assert_ne!(new_run_id, "pipeline-run-running-stale");
    assert!(node.metadata_json["pipeline_started_at"].is_string());
    let run = store.pipeline_run("pipeline-run-running-stale");
    assert_eq!(run.status, "failed");
    assert_eq!(
        run.reason.as_deref(),
        Some("stale pipeline run source commit bbbbbb1234567890 superseded by abcdef1234567890")
    );
    assert_eq!(run.metadata_json["stale_pipeline_run"], true);
    assert_eq!(
        run.metadata_json["stale_source_commit_ref"],
        "bbbbbb1234567890"
    );
    assert_eq!(
        run.metadata_json["superseded_by_source_commit_ref"],
        "abcdef1234567890"
    );
    assert!(run.completed_at.is_some());
    assert!(run.updated_at.is_some());
    let new_run = store.pipeline_run(new_run_id);
    assert_eq!(new_run.status, "running");
    assert_eq!(new_run.commit_ref.as_deref(), Some("abcdef1234567890"));
    assert_eq!(
        new_run.metadata_json["reason"],
        "operator requested harness-native pipeline"
    );
}

#[tokio::test]
async fn pipeline_run_handler_marks_running_run_without_source_ref_stale() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_pipeline_contract());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.execution = "reported".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    node.feature_checkpoint_json = Some(json!({"commit_ref": "abcdef1234567890"}));
    store.insert_node(node);
    store.insert_pipeline_run(pipeline_run_record(
        "pipeline-run-running-unknown",
        "running",
        Some("attempt-test"),
        None,
        json!({"pipeline_last_summary": "still running without source ref"}),
    ));
    let handler = pipeline_run_handler(Arc::clone(&store));

    let outcome = handler.handle(pipeline_run_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let node = store.node("node-test");
    assert_eq!(node.metadata_json["pipeline_status"], "running");
    let new_run_id = node.metadata_json["pipeline_run_id"].as_str().unwrap();
    assert_ne!(new_run_id, "pipeline-run-running-unknown");
    let run = store.pipeline_run("pipeline-run-running-unknown");
    assert_eq!(run.status, "failed");
    assert_eq!(
        run.reason.as_deref(),
        Some("stale pipeline run source commit unknown superseded by abcdef1234567890")
    );
    assert_eq!(
        run.metadata_json["pipeline_last_summary"],
        "still running without source ref"
    );
    assert_eq!(run.metadata_json["stale_pipeline_run"], true);
    assert!(run.metadata_json["stale_source_commit_ref"].is_null());
    assert_eq!(
        run.metadata_json["superseded_by_source_commit_ref"],
        "abcdef1234567890"
    );
    let new_run = store.pipeline_run(new_run_id);
    assert_eq!(new_run.status, "running");
    assert_eq!(new_run.commit_ref.as_deref(), Some("abcdef1234567890"));
}

#[tokio::test]
async fn pipeline_run_handler_keeps_requested_on_success_commit_mismatch() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_pipeline_contract());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.execution = "reported".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    node.feature_checkpoint_json = Some(json!({"commit_ref": "abcdef1234567890"}));
    store.insert_node(node);
    store.insert_pipeline_run(pipeline_run_record(
        "pipeline-run-stale",
        "success",
        Some("attempt-test"),
        Some("bbbbbb1234567890"),
        json!({
            "source_publish_source_commit_ref": "bbbbbb1234567890",
            "pipeline_last_summary": "stale run passed"
        }),
    ));
    let handler = pipeline_run_handler(Arc::clone(&store));

    let outcome = handler.handle(pipeline_run_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let node = store.node("node-test");
    assert_eq!(node.execution, "idle");
    assert_eq!(node.metadata_json["pipeline_status"], "running");
    assert_eq!(node.metadata_json["pipeline_gate_status"], "running");
    let new_run_id = node.metadata_json["pipeline_run_id"].as_str().unwrap();
    assert_ne!(new_run_id, "pipeline-run-stale");
    let new_run = store.pipeline_run(new_run_id);
    assert_eq!(new_run.status, "running");
    assert_eq!(new_run.commit_ref.as_deref(), Some("abcdef1234567890"));
    assert!(node.metadata_json.get("last_verification_passed").is_none());
    assert!(node.metadata_json.get("pipeline_evidence_refs").is_none());
}

#[tokio::test]
async fn pipeline_run_handler_skips_stale_attempt_without_projection() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_plan(plan());
    let mut node = plan_node();
    node.execution = "reported".to_string();
    node.current_attempt_id = Some("attempt-new".to_string());
    store.insert_node(node);
    let handler = pipeline_run_handler(Arc::clone(&store));

    let outcome = handler.handle(pipeline_run_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let node = store.node("node-test");
    assert_eq!(node.execution, "reported");
    assert_ne!(node.metadata_json["pipeline_status"], "requested");
}
