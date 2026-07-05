use super::super::support_dispatch::FakeWorkspacePlanDispatchStore;
use super::super::support_outbox::outbox;
use super::super::*;

pub(in crate::workspace_outbox_worker::tests) fn pipeline_run_handler(
    store: Arc<FakeWorkspacePlanDispatchStore>,
) -> PipelineRunAdmissionHandler {
    PipelineRunAdmissionHandler::new(store as Arc<dyn WorkspacePlanDispatchStore>, None)
}

pub(in crate::workspace_outbox_worker::tests) fn pipeline_run_handler_with_stage_runner(
    store: Arc<FakeWorkspacePlanDispatchStore>,
    stage_runner: Arc<dyn WorkspacePipelineStageRunner>,
) -> PipelineRunAdmissionHandler {
    PipelineRunAdmissionHandler::new(
        store as Arc<dyn WorkspacePlanDispatchStore>,
        Some(stage_runner),
    )
}

pub(in crate::workspace_outbox_worker::tests) fn pipeline_run_item() -> WorkspacePlanOutboxRecord {
    let mut item = outbox("job-pipeline-run", PIPELINE_RUN_REQUESTED_EVENT);
    item.plan_id = Some("plan-test".to_string());
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "plan_id": "plan-test",
        "node_id": "node-test",
        "attempt_id": "attempt-test",
        "reason": "operator requested harness-native pipeline"
    });
    item
}

pub(in crate::workspace_outbox_worker::tests) fn pipeline_run_item_without_attempt(
) -> WorkspacePlanOutboxRecord {
    let mut item = pipeline_run_item();
    if let Some(payload) = item.payload_json.as_object_mut() {
        payload.remove("attempt_id");
    }
    item
}

pub(in crate::workspace_outbox_worker::tests) fn pipeline_run_record(
    id: &str,
    status: &str,
    attempt_id: Option<&str>,
    commit_ref: Option<&str>,
    metadata_json: Value,
) -> WorkspacePipelineRunRecord {
    let timestamp = Utc.with_ymd_and_hms(2026, 1, 2, 3, 5, 5).unwrap();
    WorkspacePipelineRunRecord {
        id: id.to_string(),
        contract_id: "pipeline-contract-test".to_string(),
        workspace_id: "workspace-test".to_string(),
        plan_id: Some("plan-test".to_string()),
        node_id: Some("node-test".to_string()),
        attempt_id: attempt_id.map(ToOwned::to_owned),
        commit_ref: commit_ref.map(ToOwned::to_owned),
        provider: "sandbox_native".to_string(),
        status: status.to_string(),
        reason: None,
        started_at: Some(Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap()),
        completed_at: if status == "running" {
            None
        } else {
            Some(timestamp)
        },
        metadata_json,
        created_at: Utc.with_ymd_and_hms(2026, 1, 2, 3, 6, 5).unwrap(),
        updated_at: None,
    }
}

pub(in crate::workspace_outbox_worker::tests) fn pipeline_stage_run_record(
    id: &str,
    run_id: &str,
) -> WorkspacePipelineStageRunRecord {
    let timestamp = Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap();
    WorkspacePipelineStageRunRecord {
        id: id.to_string(),
        run_id: run_id.to_string(),
        workspace_id: "workspace-test".to_string(),
        stage: "test".to_string(),
        status: "running".to_string(),
        command: Some("cargo test --workspace".to_string()),
        exit_code: None,
        stdout_preview: None,
        stderr_preview: None,
        log_ref: None,
        artifact_refs_json: Vec::new(),
        started_at: Some(timestamp),
        completed_at: None,
        duration_ms: None,
        metadata_json: json!({"required": true}),
        created_at: timestamp,
        updated_at: None,
    }
}
