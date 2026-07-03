use super::*;

pub(super) fn drone_result_from_build_and_stages(
    config: &DronePipelineConfig,
    build: &Value,
    stage_results: Vec<DronePipelineStageResult>,
) -> CoreResult<DronePipelineResult> {
    let build_number = required_i64(build.get("number"), "Drone build number")?;
    let external_id = format!("{}#{build_number}", config.repo_slug());
    let external_url = config.build_url(build_number);
    let drone_status = drone_status(build.get("status"));
    let mut status = drone_internal_status(&drone_status);
    let mut reason = drone_failure_reason(&drone_status, &external_id);
    let deploy_state = drone_deploy_state(&stage_results, config.deploy.as_ref());
    let deploy_validation_issues = if deploy_state.as_deref() == Some("invalid") {
        drone_deploy_validation_issues(&stage_results, config.deploy.as_ref())
    } else {
        Vec::new()
    };
    if let Some(deploy) = config.deploy.as_ref() {
        if deploy.required
            && matches!(
                deploy_state.as_deref(),
                Some("failed" | "missing" | "invalid")
            )
            && status == "success"
        {
            status = "failed".to_string();
            reason = Some(drone_deploy_failure_reason(
                deploy,
                &external_id,
                deploy_state.as_deref().unwrap_or("failed"),
                &deploy_validation_issues,
            ));
        }
    }
    let mut evidence_refs = vec![
        format!(
            "ci_pipeline:{}",
            if status == "success" {
                "passed"
            } else {
                "failed"
            }
        ),
        format!("drone_build:{drone_status}:{external_id}"),
        format!("pipeline_external:{DRONE_PROVIDER}:{external_id}"),
    ];
    for stage in &stage_results {
        evidence_refs.push(format!("pipeline_stage:{}:{}", stage.stage, stage.status));
    }
    if let Some(deploy) = config.deploy.as_ref() {
        if let Some(deploy_state) = deploy_state.as_deref() {
            evidence_refs.push(format!(
                "deployment:{}:{}",
                if deploy_state == "passed" {
                    "passed"
                } else {
                    deploy_state
                },
                deploy.mode
            ));
            if let Some(target) = &deploy.target {
                evidence_refs.push(format!("deployment_target:{target}"));
            }
        }
    }
    dedup_strings(&mut evidence_refs);

    let mut metadata = Map::new();
    metadata.insert("external_provider".to_string(), json!(DRONE_PROVIDER));
    metadata.insert("external_id".to_string(), json!(external_id));
    metadata.insert("external_url".to_string(), json!(external_url));
    metadata.insert("drone_build_number".to_string(), json!(build_number));
    metadata.insert("drone_repo".to_string(), json!(config.repo_slug()));
    metadata.insert("drone_status".to_string(), json!(drone_status));
    metadata.insert(
        "drone_link".to_string(),
        build
            .get("link")
            .and_then(Value::as_str)
            .map_or(Value::Null, |value| json!(value)),
    );
    metadata.extend(drone_deploy_metadata(
        config.deploy.as_ref(),
        deploy_state.as_deref(),
        &deploy_validation_issues,
    ));

    Ok(DronePipelineResult {
        status,
        reason,
        stage_results,
        evidence_refs,
        external_id: Some(external_id),
        external_url: Some(external_url),
        metadata,
    })
}

pub(super) fn drone_pipeline_stage_result(
    config: &DronePipelineConfig,
    build_number: i64,
    stage_name: &str,
    step_name: &str,
    drone_status: String,
    exit_code: Option<i32>,
    log_text: String,
    error_text: &str,
    external_url: &str,
    deploy: Option<&DroneDeployConfig>,
) -> DronePipelineStageResult {
    let status = drone_internal_status(&drone_status);
    let stage = drone_stage_label(stage_name, step_name);
    let compact_log = compact_text(log_text.trim(), 4_000);
    let compact_error = compact_text(error_text.trim(), 4_000);
    let stderr_preview = if status == "failed" {
        combine_failure_preview(&compact_error, &compact_log)
    } else {
        String::new()
    };
    let mut metadata = Map::new();
    metadata.insert("external_provider".to_string(), json!(DRONE_PROVIDER));
    metadata.insert("external_url".to_string(), json!(external_url));
    metadata.insert("drone_stage".to_string(), json!(stage_name));
    metadata.insert("drone_step".to_string(), json!(step_name));
    metadata.insert("drone_status".to_string(), json!(drone_status));
    if !compact_error.is_empty() {
        metadata.insert("drone_error".to_string(), json!(compact_error));
    }
    if drone_is_deploy_stage(stage_name, step_name, deploy) {
        metadata.insert("drone_step_kind".to_string(), json!("deploy"));
        if let Some(deploy) = deploy {
            metadata.insert("deploy_mode".to_string(), json!(deploy.mode));
            metadata.insert("deploy_stage".to_string(), json!(deploy.stage));
            if let Some(target) = &deploy.target {
                metadata.insert("deploy_target".to_string(), json!(target));
            }
        }
    }
    DronePipelineStageResult {
        stage,
        status: status.clone(),
        command: format!("drone:{stage_name}/{step_name}"),
        exit_code,
        stdout_preview: if status == "success" {
            compact_log
        } else {
            String::new()
        },
        stderr_preview,
        duration_ms: 0,
        log_ref: Some(format!(
            "drone://{}/{build_number}/{stage_name}/{step_name}",
            config.repo_slug()
        )),
        artifact_refs: vec![format!("drone_build:{external_url}")],
        metadata,
    }
}

pub(in super::super) async fn finish_drone_pipeline_result(
    store: &dyn WorkspacePlanDispatchStore,
    workspace: &WorkspaceRecord,
    contract: &PipelineContractFoundation,
    run: &WorkspacePipelineRunRecord,
    result: &DronePipelineResult,
    completed_at: DateTime<Utc>,
) -> CoreResult<(WorkspacePipelineRunRecord, Vec<String>)> {
    for stage_result in &result.stage_results {
        let mut stage_metadata = Map::new();
        stage_metadata.insert("provider".to_string(), json!(contract.provider));
        stage_metadata.extend(stage_result.metadata.clone());
        let stage_row = store
            .create_pipeline_stage_run(WorkspacePipelineStageRunRecord {
                id: generate_uuid_v4(),
                run_id: run.id.clone(),
                workspace_id: workspace.id.clone(),
                stage: stage_result.stage.clone(),
                status: "running".to_string(),
                command: Some(stage_result.command.clone()),
                exit_code: None,
                stdout_preview: None,
                stderr_preview: None,
                log_ref: None,
                artifact_refs_json: Vec::new(),
                started_at: Some(completed_at),
                completed_at: None,
                duration_ms: None,
                metadata_json: Value::Object(stage_metadata.clone()),
                created_at: completed_at,
                updated_at: None,
            })
            .await?;
        let mut finish_metadata = stage_metadata;
        finish_metadata.insert(
            "duration_ms_observed".to_string(),
            json!(stage_result.duration_ms),
        );
        let _ = store
            .finish_pipeline_stage_run(
                &stage_row.id,
                &stage_result.status,
                stage_result.exit_code,
                Some(&stage_result.stdout_preview),
                Some(&stage_result.stderr_preview),
                stage_result.log_ref.as_deref(),
                &stage_result.artifact_refs,
                &Value::Object(finish_metadata),
                completed_at,
            )
            .await?;
    }

    let mut run_metadata = Map::new();
    run_metadata.insert("stage_count".to_string(), json!(result.stage_results.len()));
    run_metadata.insert(
        "service_count".to_string(),
        json!(contract.services_json.as_array().map_or(0, Vec::len)),
    );
    run_metadata.extend(result.metadata.clone());
    if let Some(reason) = result.reason.as_deref() {
        run_metadata.insert("pipeline_failure_summary".to_string(), json!(reason));
        run_metadata.insert("pipeline_last_summary".to_string(), json!(reason));
        if let Some(stage) = first_failed_drone_stage(&result.stage_results) {
            run_metadata.insert("pipeline_failed_stage".to_string(), json!(stage.stage));
        }
    }
    let run_metadata = Value::Object(run_metadata);
    let finished = store
        .finish_pipeline_run(
            &run.id,
            &result.status,
            result.reason.as_deref(),
            &run_metadata,
            completed_at,
        )
        .await?;
    let mut evidence_refs = result.evidence_refs.clone();
    evidence_refs.push(format!("pipeline_run:{}:{}", result.status, run.id));
    if let Some(external_id) = &result.external_id {
        evidence_refs.push(format!(
            "pipeline_run_external:{DRONE_PROVIDER}:{external_id}"
        ));
    }
    dedup_strings(&mut evidence_refs);
    Ok((
        finished.unwrap_or_else(|| {
            let mut fallback = run.clone();
            fallback.status = result.status.clone();
            fallback.reason = result.reason.clone();
            fallback.metadata_json = merge_object_values(&fallback.metadata_json, &run_metadata);
            fallback.completed_at = Some(completed_at);
            fallback.updated_at = Some(completed_at);
            fallback
        }),
        evidence_refs,
    ))
}

pub(super) fn drone_configuration_failure_result(message: &str) -> DronePipelineResult {
    let preview = compact_text(message, 4_000);
    let mut metadata = Map::new();
    metadata.insert("external_provider".to_string(), json!(DRONE_PROVIDER));
    metadata.insert("configuration_error".to_string(), json!(preview));
    let mut stage_metadata = Map::new();
    stage_metadata.insert("external_provider".to_string(), json!(DRONE_PROVIDER));
    DronePipelineResult {
        status: "failed".to_string(),
        reason: Some(preview.clone()),
        stage_results: vec![DronePipelineStageResult {
            stage: "drone_config".to_string(),
            status: "failed".to_string(),
            command: "drone:configure".to_string(),
            exit_code: Some(1),
            stdout_preview: String::new(),
            stderr_preview: preview.clone(),
            duration_ms: 0,
            log_ref: None,
            artifact_refs: Vec::new(),
            metadata: stage_metadata,
        }],
        evidence_refs: vec![
            "ci_pipeline:failed".to_string(),
            "drone:configuration_failed".to_string(),
        ],
        external_id: None,
        external_url: None,
        metadata,
    }
}

pub(super) fn drone_api_failure_result(message: &str) -> DronePipelineResult {
    let preview = compact_text(message, 4_000);
    let mut metadata = Map::new();
    metadata.insert("external_provider".to_string(), json!(DRONE_PROVIDER));
    metadata.insert("provider_error".to_string(), json!(preview));
    let mut stage_metadata = Map::new();
    stage_metadata.insert("external_provider".to_string(), json!(DRONE_PROVIDER));
    DronePipelineResult {
        status: "failed".to_string(),
        reason: Some(preview.clone()),
        stage_results: vec![DronePipelineStageResult {
            stage: "drone_api".to_string(),
            status: "failed".to_string(),
            command: "drone:api".to_string(),
            exit_code: Some(1),
            stdout_preview: String::new(),
            stderr_preview: preview.clone(),
            duration_ms: 0,
            log_ref: None,
            artifact_refs: Vec::new(),
            metadata: stage_metadata,
        }],
        evidence_refs: vec![
            "ci_pipeline:failed".to_string(),
            "drone:api_failed".to_string(),
        ],
        external_id: None,
        external_url: None,
        metadata,
    }
}

pub(super) fn drone_path_segment(value: &str) -> String {
    url::form_urlencoded::byte_serialize(value.as_bytes()).collect()
}

pub(super) fn looks_like_drone_not_found(message: &str) -> bool {
    let lower = message.to_ascii_lowercase();
    lower.contains(" 404") || lower.contains("not found") || lower.contains("not enabled")
}

pub(super) fn required_i64(value: Option<&Value>, label: &str) -> CoreResult<i64> {
    optional_i64(value)
        .ok_or_else(|| CoreError::Storage(format!("{label} missing from Drone API response")))
}

fn optional_i64(value: Option<&Value>) -> Option<i64> {
    value.and_then(|value| {
        value
            .as_i64()
            .or_else(|| value.as_str()?.trim().parse::<i64>().ok())
    })
}

pub(super) fn optional_i32(value: Option<&Value>) -> Option<i32> {
    optional_i64(value).and_then(|value| i32::try_from(value).ok())
}

pub(super) fn drone_status(value: Option<&Value>) -> String {
    value
        .and_then(Value::as_str)
        .and_then(|value| metadata_string(Some(&Value::String(value.to_string()))))
        .unwrap_or_else(|| "unknown".to_string())
        .to_ascii_lowercase()
}

fn drone_internal_status(status: &str) -> String {
    if status == "success" {
        "success".to_string()
    } else if status == "skipped" {
        "skipped".to_string()
    } else if is_drone_running_status(status) {
        "running".to_string()
    } else {
        "failed".to_string()
    }
}

pub(super) fn is_drone_terminal_status(status: &str) -> bool {
    matches!(
        status,
        "success" | "failure" | "error" | "killed" | "declined" | "skipped"
    )
}

pub(super) fn is_drone_running_status(status: &str) -> bool {
    matches!(status, "pending" | "running" | "blocked" | "waiting")
}

fn drone_failure_reason(status: &str, external_id: &str) -> Option<String> {
    if status == "success" {
        None
    } else if status == "timeout" {
        Some(format!("Drone build {external_id} timed out"))
    } else if matches!(status, "failure" | "error" | "killed" | "declined") {
        Some(format!(
            "Drone build {external_id} finished with status {status}"
        ))
    } else {
        Some(format!(
            "Drone build {external_id} did not complete successfully: {status}"
        ))
    }
}

pub(super) fn drone_build_matches_commit(build: &Value, commit: &str) -> bool {
    ["after", "commit", "sha"].iter().any(|key| {
        build
            .get(*key)
            .and_then(Value::as_str)
            .is_some_and(|value| {
                value == commit || value.starts_with(commit) || commit.starts_with(value)
            })
    })
}

pub(super) fn log_part(value: Option<&Value>) -> Option<String> {
    if let Some(number) = optional_i64(value).filter(|number| *number > 0) {
        return Some(number.to_string());
    }
    value
        .and_then(Value::as_str)
        .and_then(|value| metadata_string(Some(&Value::String(value.to_string()))))
}

pub(super) fn drone_logs_text(value: Option<&Value>) -> String {
    value
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(|item| item.get("out").and_then(Value::as_str))
                .collect::<String>()
        })
        .unwrap_or_default()
}

fn drone_stage_label(stage_name: &str, step_name: &str) -> String {
    let label = if stage_name == step_name {
        step_name.to_string()
    } else {
        format!("{stage_name}/{step_name}")
    };
    label.chars().take(40).collect()
}
