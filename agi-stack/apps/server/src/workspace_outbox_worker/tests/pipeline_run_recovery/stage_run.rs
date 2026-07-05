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
