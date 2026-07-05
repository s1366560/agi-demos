use super::super::*;

pub(super) async fn latest_pipeline_run_for_node(
    store: &FakeWorkspacePlanDispatchStore,
    plan_id: &str,
    node_id: &str,
    attempt_id: Option<&str>,
) -> CoreResult<Option<WorkspacePipelineRunRecord>> {
    let mut runs = store
        .pipeline_runs
        .lock()
        .unwrap()
        .values()
        .filter(|run| {
            run.plan_id.as_deref() == Some(plan_id)
                && run.node_id.as_deref() == Some(node_id)
                && attempt_id.is_none_or(|attempt_id| run.attempt_id.as_deref() == Some(attempt_id))
        })
        .cloned()
        .collect::<Vec<_>>();
    runs.sort_by(|left, right| {
        right
            .created_at
            .cmp(&left.created_at)
            .then_with(|| right.id.cmp(&left.id))
    });
    Ok(runs.into_iter().next())
}

#[allow(clippy::too_many_arguments)]
pub(super) async fn ensure_pipeline_contract(
    store: &FakeWorkspacePlanDispatchStore,
    contract_id: &str,
    workspace_id: &str,
    plan_id: &str,
    provider: &str,
    code_root: Option<&str>,
    commands_json: &Value,
    env_json: &Value,
    trigger_policy_json: &Value,
    timeout_seconds: i32,
    auto_deploy: bool,
    preview_port: Option<i32>,
    health_url: Option<&str>,
    metadata_json: &Value,
    now: DateTime<Utc>,
) -> CoreResult<String> {
    let mut contracts = store.pipeline_contracts.lock().unwrap();
    let key = (workspace_id.to_string(), plan_id.to_string());
    if let Some(existing) = contracts.get_mut(&key) {
        existing.provider = provider.to_string();
        existing.code_root = code_root.map(ToOwned::to_owned);
        existing.commands_json = commands_json.clone();
        existing.env_json = env_json.clone();
        existing.trigger_policy_json = trigger_policy_json.clone();
        existing.timeout_seconds = timeout_seconds.max(1);
        existing.auto_deploy = auto_deploy;
        existing.preview_port = preview_port;
        existing.health_url = health_url.map(ToOwned::to_owned);
        existing.metadata_json = metadata_json.clone();
        existing.updated_at = Some(now);
        return Ok(existing.id.clone());
    }
    let record = FakePipelineContractRecord {
        id: contract_id.to_string(),
        workspace_id: workspace_id.to_string(),
        plan_id: plan_id.to_string(),
        provider: provider.to_string(),
        code_root: code_root.map(ToOwned::to_owned),
        commands_json: commands_json.clone(),
        env_json: env_json.clone(),
        trigger_policy_json: trigger_policy_json.clone(),
        timeout_seconds: timeout_seconds.max(1),
        auto_deploy,
        preview_port,
        health_url: health_url.map(ToOwned::to_owned),
        metadata_json: metadata_json.clone(),
        created_at: now,
        updated_at: None,
    };
    let id = record.id.clone();
    contracts.insert(key, record);
    Ok(id)
}

pub(super) async fn create_pipeline_run(
    store: &FakeWorkspacePlanDispatchStore,
    run: WorkspacePipelineRunRecord,
) -> CoreResult<WorkspacePipelineRunRecord> {
    store
        .pipeline_runs
        .lock()
        .unwrap()
        .insert(run.id.clone(), run.clone());
    Ok(run)
}

pub(super) async fn finish_pipeline_run(
    store: &FakeWorkspacePlanDispatchStore,
    run_id: &str,
    status: &str,
    reason: Option<&str>,
    metadata_patch: &Value,
    completed_at: DateTime<Utc>,
) -> CoreResult<Option<WorkspacePipelineRunRecord>> {
    let mut runs = store.pipeline_runs.lock().unwrap();
    let Some(run) = runs.get_mut(run_id) else {
        return Ok(None);
    };
    run.status = status.to_string();
    run.reason = reason.map(ToOwned::to_owned);
    run.completed_at = Some(completed_at);
    run.updated_at = Some(completed_at);
    let mut metadata = object_or_empty(run.metadata_json.clone());
    for (key, value) in object_or_empty(metadata_patch.clone()) {
        metadata.insert(key, value);
    }
    run.metadata_json = Value::Object(metadata);
    Ok(Some(run.clone()))
}

pub(super) async fn create_pipeline_stage_run(
    store: &FakeWorkspacePlanDispatchStore,
    stage_run: WorkspacePipelineStageRunRecord,
) -> CoreResult<WorkspacePipelineStageRunRecord> {
    store
        .pipeline_stage_runs
        .lock()
        .unwrap()
        .insert(stage_run.id.clone(), stage_run.clone());
    Ok(stage_run)
}

#[allow(clippy::too_many_arguments)]
pub(super) async fn finish_pipeline_stage_run(
    store: &FakeWorkspacePlanDispatchStore,
    stage_run_id: &str,
    status: &str,
    exit_code: Option<i32>,
    stdout_preview: Option<&str>,
    stderr_preview: Option<&str>,
    log_ref: Option<&str>,
    artifact_refs: &[String],
    metadata_patch: &Value,
    completed_at: DateTime<Utc>,
) -> CoreResult<Option<WorkspacePipelineStageRunRecord>> {
    let mut stage_runs = store.pipeline_stage_runs.lock().unwrap();
    let Some(stage_run) = stage_runs.get_mut(stage_run_id) else {
        return Ok(None);
    };
    stage_run.status = status.to_string();
    stage_run.exit_code = exit_code;
    stage_run.stdout_preview = stdout_preview.map(ToOwned::to_owned);
    stage_run.stderr_preview = stderr_preview.map(ToOwned::to_owned);
    stage_run.log_ref = log_ref.map(ToOwned::to_owned);
    stage_run.artifact_refs_json = artifact_refs.to_vec();
    stage_run.completed_at = Some(completed_at);
    let duration_ms = stage_run
        .started_at
        .map(|started_at| (completed_at - started_at).num_milliseconds().max(0))
        .unwrap_or(0);
    stage_run.duration_ms = Some(i32::try_from(duration_ms).unwrap_or(i32::MAX));
    stage_run.updated_at = Some(completed_at);
    let mut metadata = object_or_empty(stage_run.metadata_json.clone());
    for (key, value) in object_or_empty(metadata_patch.clone()) {
        metadata.insert(key, value);
    }
    stage_run.metadata_json = Value::Object(metadata);
    Ok(Some(stage_run.clone()))
}
