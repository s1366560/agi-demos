use super::*;

pub(crate) struct ProjectSandboxPipelineStageRunner {
    sandboxes: Arc<ProjectSandboxService>,
}

impl ProjectSandboxPipelineStageRunner {
    pub(crate) fn new(sandboxes: Arc<ProjectSandboxService>) -> Self {
        Self { sandboxes }
    }
}

#[async_trait]
impl WorkspacePipelineStageRunner for ProjectSandboxPipelineStageRunner {
    async fn run_stage(
        &self,
        project_id: &str,
        contract: &PipelineContractFoundation,
        stage: &PipelineStageSpec,
    ) -> PipelineStageResult {
        let command = wrapped_pipeline_command(
            &stage.command,
            contract.code_root.as_deref(),
            &contract.env_json,
        );
        let started = Instant::now();
        let raw = self
            .sandboxes
            .execute_pipeline_tool(
                project_id,
                "bash",
                &json!({
                    "command": command,
                    "timeout": stage.timeout_seconds
                }),
                f64::from(stage.timeout_seconds.saturating_add(5).max(1)),
            )
            .await;
        let duration_ms = saturating_duration_ms(started.elapsed().as_millis());
        match raw {
            Ok(response) => pipeline_stage_result_from_tool_response(stage, response, duration_ms),
            Err(err) => PipelineStageResult {
                stage: stage.stage.clone(),
                status: "failed".to_string(),
                command: stage.command.clone(),
                exit_code: Some(1),
                stdout_preview: String::new(),
                stderr_preview: compact_text(&format!("{err:?}"), 4_000),
                duration_ms,
                log_ref: None,
                artifact_refs: Vec::new(),
                service_id: stage.service_id.clone(),
                required: stage.required,
            },
        }
    }
}

pub(crate) struct PipelineRunAdmissionHandler {
    store: Arc<dyn WorkspacePlanDispatchStore>,
    stage_runner: Option<Arc<dyn WorkspacePipelineStageRunner>>,
}

impl PipelineRunAdmissionHandler {
    pub(crate) fn new(
        store: Arc<dyn WorkspacePlanDispatchStore>,
        stage_runner: Option<Arc<dyn WorkspacePipelineStageRunner>>,
    ) -> Self {
        Self {
            store,
            stage_runner,
        }
    }
}

#[async_trait]
impl WorkspacePlanOutboxHandler for PipelineRunAdmissionHandler {
    async fn handle(
        &self,
        item: WorkspacePlanOutboxRecord,
    ) -> CoreResult<WorkspacePlanOutboxHandlerOutcome> {
        let payload = object_or_empty(item.payload_json.clone());
        let workspace_id =
            string_from_map(&payload, "workspace_id").unwrap_or_else(|| item.workspace_id.clone());
        let plan_id = item
            .plan_id
            .clone()
            .or_else(|| string_from_map(&payload, "plan_id"))
            .ok_or_else(|| {
                CoreError::Storage(
                    "pipeline_run_requested requires plan_id and node_id".to_string(),
                )
            })?;
        let node_id = required_string(&payload, "node_id")?;
        let attempt_id = string_from_map(&payload, "attempt_id");
        let reason = string_from_map(&payload, "reason")
            .unwrap_or_else(|| "pipeline_gate_required".to_string());

        let plan = self.store.get_plan(&plan_id).await?.ok_or_else(|| {
            CoreError::Storage(format!(
                "workspace plan {plan_id} not found for workspace {workspace_id}"
            ))
        })?;
        if plan.workspace_id != workspace_id {
            return Err(CoreError::Storage(format!(
                "workspace plan {plan_id} not found for workspace {workspace_id}"
            )));
        }
        let nodes = self.store.list_plan_nodes(&plan_id).await?;
        let Some(mut node) = nodes.into_iter().find(|candidate| candidate.id == node_id) else {
            return Err(CoreError::Storage(format!(
                "workspace plan node {node_id} not found"
            )));
        };
        if node.intent == "done" {
            return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
        }
        if attempt_id.is_some()
            && node.current_attempt_id.as_deref().is_some()
            && node.current_attempt_id.as_deref() != attempt_id.as_deref()
        {
            return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
        }

        let now = Utc::now();
        if let Some(run) = self
            .store
            .latest_pipeline_run_for_node(&plan_id, &node_id, attempt_id.as_deref())
            .await?
        {
            if run.status == "running" {
                if pipeline_run_matches_node_expected_commit(&run, &node) {
                    mark_existing_pipeline_run_running(&mut node, &run, now);
                    self.store.save_plan_node(node).await?;
                    return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
                }
                let (reason, metadata_patch) = stale_pipeline_run_failure_metadata(&run, &node);
                let _ = self
                    .store
                    .finish_pipeline_run(&run.id, "failed", Some(&reason), &metadata_patch, now)
                    .await?;
            }
            if can_reflect_existing_pipeline_run(&run, &node) {
                reflect_existing_pipeline_run_to_node(&mut node, &run, now);
                self.store.save_plan_node(node).await?;
                return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
            }
        }

        let workspace = self
            .store
            .get_workspace(&workspace_id)
            .await?
            .ok_or_else(|| CoreError::Storage(format!("workspace {workspace_id} not found")))?;
        let mut contract = pipeline_contract_foundation(&workspace);
        let source_publish_outcome =
            prepare_drone_source_publish(&mut contract, &workspace, &node, attempt_id.as_deref())
                .await?;
        if !contract.can_create_sandbox_native_run() && source_publish_outcome.is_none() {
            mark_pipeline_requested(
                &mut node,
                &item,
                &reason,
                attempt_id.as_deref(),
                now,
                "runtime_admitted",
            );
            self.store.save_plan_node(node).await?;
            return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
        }

        let trigger_policy_json = json!({
            "trigger": "verification_gate",
            "node_id": node_id,
            "attempt_id": attempt_id
        });
        let contract_id = self
            .store
            .ensure_pipeline_contract(
                &generate_uuid_v4(),
                &workspace_id,
                &plan_id,
                &contract.provider,
                contract.code_root.as_deref(),
                &contract.commands_json,
                &contract.env_json,
                &trigger_policy_json,
                contract.timeout_seconds,
                contract.auto_deploy,
                contract.preview_port,
                contract.health_url.as_deref(),
                &pipeline_contract_metadata(&contract, source_publish_outcome.as_ref()),
                now,
            )
            .await?;
        let run_metadata = pipeline_run_metadata(&reason, source_publish_outcome.as_ref());
        let run = WorkspacePipelineRunRecord {
            id: generate_uuid_v4(),
            contract_id,
            workspace_id: workspace_id.clone(),
            plan_id: Some(plan_id.clone()),
            node_id: Some(node_id.clone()),
            attempt_id: attempt_id.clone(),
            commit_ref: source_publish_source_commit_ref(source_publish_outcome.as_ref())
                .or_else(|| node_expected_commit_ref(&node)),
            provider: contract.provider.clone(),
            status: "running".to_string(),
            reason: None,
            started_at: Some(now),
            completed_at: None,
            metadata_json: run_metadata,
            created_at: now,
            updated_at: None,
        };
        let run = self.store.create_pipeline_run(run).await?;
        mark_existing_pipeline_run_running(&mut node, &run, now);
        self.store.save_plan_node(node.clone()).await?;

        if let Some(source_publish_failure) = source_publish_outcome
            .as_ref()
            .and_then(DroneSourcePublishOutcome::failure)
        {
            let completed_at = Utc::now();
            let run = finish_drone_source_publish_failure(
                self.store.as_ref(),
                &workspace,
                &contract,
                &run,
                &source_publish_failure,
                completed_at,
            )
            .await?;
            finish_pipeline_on_node(
                &mut node,
                &run,
                "failed",
                Some(&source_publish_failure.reason),
                &source_publish_failure.evidence_refs(&run.id),
                None,
                contract.health_url.as_deref(),
                completed_at,
            );
            self.store.save_plan_node(node).await?;
            self.store
                .enqueue_plan_outbox(pipeline_completed_supervisor_tick_with_source(
                    &workspace_id,
                    &plan_id,
                    &node_id,
                    &run.id,
                    "failed",
                    "workspace_plan.drone_pipeline_run_completed",
                    completed_at,
                ))
                .await?;
            return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
        }

        if contract.provider == DRONE_PROVIDER {
            let completed_at = Utc::now();
            if let Some(result) = run_drone_pipeline_if_configured(&contract).await? {
                let (run, evidence_refs) = finish_drone_pipeline_result(
                    self.store.as_ref(),
                    &workspace,
                    &contract,
                    &run,
                    &result,
                    completed_at,
                )
                .await?;
                finish_pipeline_on_node(
                    &mut node,
                    &run,
                    &result.status,
                    run.reason.as_deref(),
                    &evidence_refs,
                    None,
                    contract.health_url.as_deref(),
                    completed_at,
                );
                self.store.save_plan_node(node).await?;
                self.store
                    .enqueue_plan_outbox(pipeline_completed_supervisor_tick_with_source(
                        &workspace_id,
                        &plan_id,
                        &node_id,
                        &run.id,
                        &result.status,
                        "workspace_plan.drone_pipeline_run_completed",
                        completed_at,
                    ))
                    .await?;
                return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
            }
            let run = finish_drone_provider_unavailable(
                self.store.as_ref(),
                &workspace,
                &contract,
                &run,
                source_publish_outcome.as_ref(),
                completed_at,
            )
            .await?;
            let evidence_refs = vec![
                "ci_pipeline:failed".to_string(),
                "drone:plugin_unavailable".to_string(),
                format!("pipeline_run:failed:{}", run.id),
            ];
            finish_pipeline_on_node(
                &mut node,
                &run,
                "failed",
                run.reason.as_deref(),
                &evidence_refs,
                None,
                contract.health_url.as_deref(),
                completed_at,
            );
            self.store.save_plan_node(node).await?;
            self.store
                .enqueue_plan_outbox(pipeline_completed_supervisor_tick_with_source(
                    &workspace_id,
                    &plan_id,
                    &node_id,
                    &run.id,
                    "failed",
                    "workspace_plan.drone_pipeline_run_completed",
                    completed_at,
                ))
                .await?;
            return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
        }

        if contract.can_execute_inline_stages() {
            if let Some(stage_runner) = &self.stage_runner {
                let outcome = execute_sandbox_native_pipeline_stages(
                    self.store.as_ref(),
                    stage_runner.as_ref(),
                    &workspace,
                    &contract,
                    &run,
                )
                .await?;
                let completed_at = Utc::now();
                let run = self
                    .store
                    .finish_pipeline_run(
                        &run.id,
                        &outcome.status,
                        outcome.reason.as_deref(),
                        &json!({
                            "stage_count": outcome.stage_results.len(),
                            "service_count": 0,
                            "preview_urls": {}
                        }),
                        completed_at,
                    )
                    .await?
                    .unwrap_or_else(|| {
                        let mut fallback = run.clone();
                        fallback.status = outcome.status.clone();
                        fallback.reason = outcome.reason.clone();
                        fallback.completed_at = Some(completed_at);
                        fallback.updated_at = Some(completed_at);
                        fallback
                    });
                finish_pipeline_on_node(
                    &mut node,
                    &run,
                    &outcome.status,
                    outcome.reason.as_deref(),
                    &outcome.evidence_refs,
                    None,
                    contract.health_url.as_deref(),
                    completed_at,
                );
                self.store.save_plan_node(node).await?;
                self.store
                    .enqueue_plan_outbox(pipeline_completed_supervisor_tick(
                        &workspace_id,
                        &plan_id,
                        &node_id,
                        &run.id,
                        &outcome.status,
                        completed_at,
                    ))
                    .await?;
            }
        }

        Ok(WorkspacePlanOutboxHandlerOutcome::Complete)
    }
}

pub(crate) struct PipelineContractFoundation {
    provider: String,
    host_code_root: Option<String>,
    code_root: Option<String>,
    commands_json: Value,
    env_json: Value,
    timeout_seconds: i32,
    auto_deploy: bool,
    preview_port: Option<i32>,
    health_url: Option<String>,
    services_json: Value,
    deploy_command: Option<String>,
    agent_managed: bool,
    contract_source: String,
    provider_config_json: Value,
    metadata_json: Value,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct PipelineStageSpec {
    pub(super) stage: String,
    pub(super) command: String,
    pub(super) required: bool,
    pub(super) timeout_seconds: i32,
    pub(super) service_id: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct PipelineStageResult {
    pub(super) stage: String,
    pub(super) status: String,
    pub(super) command: String,
    pub(super) exit_code: Option<i32>,
    pub(super) stdout_preview: String,
    pub(super) stderr_preview: String,
    pub(super) duration_ms: i32,
    pub(super) log_ref: Option<String>,
    pub(super) artifact_refs: Vec<String>,
    pub(super) service_id: Option<String>,
    pub(super) required: bool,
}

impl PipelineStageResult {
    fn passed(&self) -> bool {
        matches!(self.status.as_str(), "success" | "skipped")
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct PipelineStageExecutionOutcome {
    status: String,
    reason: Option<String>,
    stage_results: Vec<PipelineStageResult>,
    evidence_refs: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct DroneSourcePublishFailure {
    reason: String,
    metadata: Map<String, Value>,
}

impl DroneSourcePublishFailure {
    fn evidence_refs(&self, run_id: &str) -> Vec<String> {
        vec![
            "ci_pipeline:failed".to_string(),
            "source_publish:failed".to_string(),
            format!("pipeline_run:failed:{run_id}"),
        ]
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct DroneSourcePublishSuccess {
    metadata: Map<String, Value>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct DroneSourcePublishSkipped {
    metadata: Map<String, Value>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum DroneSourcePublishOutcome {
    Failed(DroneSourcePublishFailure),
    Published(DroneSourcePublishSuccess),
    Skipped(DroneSourcePublishSkipped),
}

impl DroneSourcePublishOutcome {
    fn metadata(&self) -> &Map<String, Value> {
        match self {
            Self::Failed(failure) => &failure.metadata,
            Self::Published(success) => &success.metadata,
            Self::Skipped(skipped) => &skipped.metadata,
        }
    }

    fn failure(&self) -> Option<&DroneSourcePublishFailure> {
        match self {
            Self::Failed(failure) => Some(failure),
            Self::Published(_) | Self::Skipped(_) => None,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct GitPublishResult {
    status: String,
    reason: Option<String>,
    published_commit: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct GitRemoteMergeResult {
    status: String,
    reason: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) struct AcceptedWorktreeIntegrationResult {
    pub(super) status: String,
    pub(super) summary: String,
    pub(super) commit_ref: String,
    pub(super) dirty_signature: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) struct GitCommandOutput {
    pub(super) exit_code: i32,
    pub(super) stdout: String,
    pub(super) stderr: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct DronePipelineConfig {
    owner: String,
    repo: String,
    server_url: String,
    token: String,
    client: String,
    cli_command: String,
    host_code_root: Option<PathBuf>,
    branch: Option<String>,
    commit: Option<String>,
    params: Vec<(String, String)>,
    deploy: Option<DroneDeployConfig>,
    timeout_seconds: u64,
    poll_interval_seconds: u64,
}

impl DronePipelineConfig {
    fn repo_slug(&self) -> String {
        format!("{}/{}", self.owner, self.repo)
    }

    fn build_url(&self, build_number: i64) -> String {
        format!(
            "{}/{}/{}/{}",
            self.server_url.trim_end_matches('/'),
            drone_path_segment(&self.owner),
            drone_path_segment(&self.repo),
            build_number
        )
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct DroneDeployConfig {
    mode: String,
    stage: String,
    required: bool,
    target: Option<String>,
    docker: Map<String, Value>,
    kubernetes: Map<String, Value>,
    cli: Map<String, Value>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct DronePipelineResult {
    status: String,
    reason: Option<String>,
    stage_results: Vec<DronePipelineStageResult>,
    evidence_refs: Vec<String>,
    external_id: Option<String>,
    external_url: Option<String>,
    metadata: Map<String, Value>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct DronePipelineStageResult {
    stage: String,
    status: String,
    command: String,
    exit_code: Option<i32>,
    stdout_preview: String,
    stderr_preview: String,
    duration_ms: i32,
    log_ref: Option<String>,
    artifact_refs: Vec<String>,
    metadata: Map<String, Value>,
}

impl PipelineContractFoundation {
    fn can_create_sandbox_native_run(&self) -> bool {
        if self.provider != SANDBOX_NATIVE_PROVIDER {
            return false;
        }
        if !self.auto_deploy {
            return true;
        }
        let service_count = self.services_json.as_array().map_or(0, Vec::len);
        if self.agent_managed {
            if self.contract_source != PLANNING_CONTRACT_SOURCE {
                return false;
            }
            if service_count == 0 && self.deploy_command.is_none() && self.health_url.is_none() {
                return false;
            }
        }
        service_count > 0
    }

    fn can_execute_inline_stages(&self) -> bool {
        self.provider == SANDBOX_NATIVE_PROVIDER
            && !self.auto_deploy
            && self.services_json.as_array().map_or(0, Vec::len) == 0
    }
}

async fn execute_sandbox_native_pipeline_stages(
    store: &dyn WorkspacePlanDispatchStore,
    runner: &dyn WorkspacePipelineStageRunner,
    workspace: &WorkspaceRecord,
    contract: &PipelineContractFoundation,
    run: &WorkspacePipelineRunRecord,
) -> CoreResult<PipelineStageExecutionOutcome> {
    let stages = pipeline_stage_specs_from_json(&contract.commands_json, contract.timeout_seconds);
    let mut stage_results = Vec::new();
    let mut evidence_refs = Vec::new();
    let mut failure_reason = None;

    for stage in stages {
        let started_at = Utc::now();
        let stage_row = store
            .create_pipeline_stage_run(WorkspacePipelineStageRunRecord {
                id: generate_uuid_v4(),
                run_id: run.id.clone(),
                workspace_id: workspace.id.clone(),
                stage: stage.stage.clone(),
                status: "running".to_string(),
                command: Some(stage.command.clone()),
                exit_code: None,
                stdout_preview: None,
                stderr_preview: None,
                log_ref: None,
                artifact_refs_json: Vec::new(),
                started_at: Some(started_at),
                completed_at: None,
                duration_ms: None,
                metadata_json: json!({
                    "required": stage.required,
                    "service_id": stage.service_id
                }),
                created_at: started_at,
                updated_at: None,
            })
            .await?;
        let stage_result = runner
            .run_stage(&workspace.project_id, contract, &stage)
            .await;
        let completed_at = Utc::now();
        let _ = store
            .finish_pipeline_stage_run(
                &stage_row.id,
                &stage_result.status,
                stage_result.exit_code,
                Some(&stage_result.stdout_preview),
                Some(&stage_result.stderr_preview),
                stage_result.log_ref.as_deref(),
                &stage_result.artifact_refs,
                &json!({
                    "duration_ms_observed": stage_result.duration_ms,
                    "service_id": stage_result.service_id
                }),
                completed_at,
            )
            .await?;

        let passed = stage_result.passed();
        let status_label = if passed { "passed" } else { "failed" };
        evidence_refs.push(format!(
            "pipeline_stage:{}:{status_label}",
            stage_result.stage
        ));
        if let Some(service_id) = &stage_result.service_id {
            evidence_refs.push(format!(
                "pipeline_stage:{}:{status_label}:{service_id}",
                stage_result.stage
            ));
        }
        if !passed && stage_result.required {
            failure_reason = Some(format!(
                "stage {} failed with exit {}",
                stage_result.stage,
                stage_result.exit_code.unwrap_or(1)
            ));
            stage_results.push(stage_result);
            break;
        }
        stage_results.push(stage_result);
    }

    let status = if failure_reason.is_none() {
        "success"
    } else {
        "failed"
    }
    .to_string();
    evidence_refs.insert(
        0,
        format!(
            "ci_pipeline:{}",
            if status == "success" {
                "passed"
            } else {
                "failed"
            }
        ),
    );
    evidence_refs.push(format!("pipeline_run:{status}:{}", run.id));
    dedup_strings(&mut evidence_refs);

    Ok(PipelineStageExecutionOutcome {
        status,
        reason: failure_reason,
        stage_results,
        evidence_refs,
    })
}

async fn finish_drone_source_publish_failure(
    store: &dyn WorkspacePlanDispatchStore,
    workspace: &WorkspaceRecord,
    contract: &PipelineContractFoundation,
    run: &WorkspacePipelineRunRecord,
    failure: &DroneSourcePublishFailure,
    completed_at: DateTime<Utc>,
) -> CoreResult<WorkspacePipelineRunRecord> {
    let stage_row = store
        .create_pipeline_stage_run(WorkspacePipelineStageRunRecord {
            id: generate_uuid_v4(),
            run_id: run.id.clone(),
            workspace_id: workspace.id.clone(),
            stage: "source_publish".to_string(),
            status: "running".to_string(),
            command: Some("git:publish".to_string()),
            exit_code: None,
            stdout_preview: None,
            stderr_preview: None,
            log_ref: None,
            artifact_refs_json: Vec::new(),
            started_at: Some(completed_at),
            completed_at: None,
            duration_ms: None,
            metadata_json: Value::Object(source_publish_stage_metadata(failure)),
            created_at: completed_at,
            updated_at: None,
        })
        .await?;
    let _ = store
        .finish_pipeline_stage_run(
            &stage_row.id,
            "failed",
            Some(1),
            Some(""),
            Some(&failure.reason),
            None,
            &[],
            &Value::Object(source_publish_stage_metadata(failure)),
            completed_at,
        )
        .await?;

    let run_metadata = Value::Object(drone_source_publish_run_metadata(
        contract,
        failure,
        completed_at,
    ));
    let finished = store
        .finish_pipeline_run(
            &run.id,
            "failed",
            Some(&failure.reason),
            &run_metadata,
            completed_at,
        )
        .await?;
    Ok(finished.unwrap_or_else(|| {
        let mut fallback = run.clone();
        fallback.status = "failed".to_string();
        fallback.reason = Some(failure.reason.clone());
        fallback.metadata_json = merge_object_values(&fallback.metadata_json, &run_metadata);
        fallback.completed_at = Some(completed_at);
        fallback.updated_at = Some(completed_at);
        fallback
    }))
}

async fn finish_drone_provider_unavailable(
    store: &dyn WorkspacePlanDispatchStore,
    workspace: &WorkspaceRecord,
    contract: &PipelineContractFoundation,
    run: &WorkspacePipelineRunRecord,
    source_publish_outcome: Option<&DroneSourcePublishOutcome>,
    completed_at: DateTime<Utc>,
) -> CoreResult<WorkspacePipelineRunRecord> {
    let message = format!("pipeline provider plugin is not enabled: {DRONE_PROVIDER}");
    let stage_metadata = drone_provider_unavailable_stage_metadata(contract);
    let stage_row = store
        .create_pipeline_stage_run(WorkspacePipelineStageRunRecord {
            id: generate_uuid_v4(),
            run_id: run.id.clone(),
            workspace_id: workspace.id.clone(),
            stage: "drone_plugin".to_string(),
            status: "running".to_string(),
            command: Some("plugin:resolve".to_string()),
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
    let _ = store
        .finish_pipeline_stage_run(
            &stage_row.id,
            "failed",
            Some(1),
            Some(""),
            Some(&message),
            None,
            &[],
            &Value::Object(stage_metadata),
            completed_at,
        )
        .await?;

    let run_metadata = Value::Object(drone_provider_unavailable_run_metadata(
        contract,
        source_publish_outcome,
        &message,
    ));
    let finished = store
        .finish_pipeline_run(
            &run.id,
            "failed",
            Some(&message),
            &run_metadata,
            completed_at,
        )
        .await?;
    Ok(finished.unwrap_or_else(|| {
        let mut fallback = run.clone();
        fallback.status = "failed".to_string();
        fallback.reason = Some(message);
        fallback.metadata_json = merge_object_values(&fallback.metadata_json, &run_metadata);
        fallback.completed_at = Some(completed_at);
        fallback.updated_at = Some(completed_at);
        fallback
    }))
}

fn drone_provider_unavailable_stage_metadata(
    contract: &PipelineContractFoundation,
) -> Map<String, Value> {
    let mut metadata = Map::new();
    metadata.insert("external_provider".to_string(), json!(DRONE_PROVIDER));
    metadata.insert("plugin_unavailable".to_string(), json!(true));
    metadata.insert("provider".to_string(), json!(contract.provider));
    metadata
}

fn drone_provider_unavailable_run_metadata(
    contract: &PipelineContractFoundation,
    source_publish_outcome: Option<&DroneSourcePublishOutcome>,
    message: &str,
) -> Map<String, Value> {
    let mut metadata = Map::new();
    metadata.insert("stage_count".to_string(), json!(1));
    metadata.insert(
        "service_count".to_string(),
        json!(contract.services_json.as_array().map_or(0, Vec::len)),
    );
    metadata.insert("external_provider".to_string(), json!(DRONE_PROVIDER));
    metadata.insert("plugin_unavailable".to_string(), json!(true));
    metadata.insert("provider".to_string(), json!(DRONE_PROVIDER));
    metadata.insert("provider_error".to_string(), json!(message));
    metadata.insert("pipeline_failed_stage".to_string(), json!("drone_plugin"));
    metadata.insert("pipeline_failure_summary".to_string(), json!(message));
    metadata.insert("pipeline_last_summary".to_string(), json!(message));
    if let Some(outcome) = source_publish_outcome {
        metadata.extend(outcome.metadata().clone());
    }
    metadata
}

async fn run_drone_pipeline_if_configured(
    contract: &PipelineContractFoundation,
) -> CoreResult<Option<DronePipelineResult>> {
    let Some(config) = drone_pipeline_config(contract)? else {
        return Ok(None);
    };
    let result = match run_drone_pipeline(&config).await {
        Ok(result) => result,
        Err(err) => drone_api_failure_result(&err.to_string()),
    };
    Ok(Some(result))
}

fn drone_pipeline_config(
    contract: &PipelineContractFoundation,
) -> CoreResult<Option<DronePipelineConfig>> {
    let provider_config = object_or_empty(contract.provider_config_json.clone());
    let Some(repo_slug) = string_from_map(&provider_config, "repo")
        .or_else(|| string_from_map(&provider_config, "repository"))
    else {
        return Ok(None);
    };
    let Some((owner, repo)) = repo_slug.split_once('/') else {
        return Ok(Some(drone_config_failure_config(
            "delivery_cicd.drone.repo must be '<owner>/<repo>'",
        )));
    };
    let owner = owner.trim();
    let repo = repo.trim();
    if owner.is_empty() || repo.is_empty() || repo.contains('/') {
        return Ok(Some(drone_config_failure_config(
            "delivery_cicd.drone.repo must be '<owner>/<repo>'",
        )));
    }

    let server_env = string_from_map(&provider_config, "drone_server_env")
        .or_else(|| string_from_map(&provider_config, "server_env"))
        .or_else(|| string_from_map(&provider_config, "server_url_env"))
        .unwrap_or_else(|| DRONE_SERVER_ENV.to_string());
    let server_url = string_from_map(&provider_config, "server_url")
        .or_else(|| drone_config_value_env(&server_env))
        .or_else(|| {
            if server_env == DRONE_SERVER_URL_ENV {
                None
            } else {
                drone_config_value_env(DRONE_SERVER_URL_ENV)
            }
        });
    let Some(server_url) = server_url else {
        return Ok(None);
    };

    let token_env = string_from_map(&provider_config, "drone_token_env")
        .or_else(|| string_from_map(&provider_config, "token_env"))
        .unwrap_or_else(|| DRONE_TOKEN_ENV.to_string());
    let Some(token) = drone_config_value_env(&token_env) else {
        return Ok(None);
    };

    let deploy = drone_deploy_config(provider_config.get("deploy"));
    let mut params = string_pairs_from_map(
        provider_config
            .get("params")
            .or_else(|| provider_config.get("build_params")),
    );
    let target = string_from_map(&provider_config, "target")
        .or_else(|| deploy.as_ref().and_then(|deploy| deploy.target.clone()));
    if let Some(target) = target {
        insert_default_param(&mut params, "target", target);
    }
    add_drone_deploy_params(&mut params, deploy.as_ref());
    params.sort_by(|left, right| left.0.cmp(&right.0));

    Ok(Some(DronePipelineConfig {
        owner: owner.to_string(),
        repo: repo.to_string(),
        server_url: server_url.trim_end_matches('/').to_string(),
        token,
        client: drone_client_from_config(&provider_config),
        cli_command: drone_cli_command_from_config(&provider_config),
        host_code_root: contract.host_code_root.as_deref().map(PathBuf::from),
        branch: string_from_map(&provider_config, "branch"),
        commit: string_from_map(&provider_config, "commit"),
        params,
        deploy,
        timeout_seconds: positive_u64_from_map(
            &provider_config,
            "timeout_seconds",
            contract.timeout_seconds.max(1) as u64,
        ),
        poll_interval_seconds: positive_u64_from_map(&provider_config, "poll_interval_seconds", 5),
    }))
}

fn drone_client_from_config(provider_config: &Map<String, Value>) -> String {
    if bool_from_map_default(provider_config, "use_cli", false) {
        return "cli".to_string();
    }
    let raw = string_from_map(provider_config, "drone_client")
        .or_else(|| string_from_map(provider_config, "client"))
        .or_else(|| string_from_map(provider_config, "transport"))
        .unwrap_or_else(|| "http".to_string());
    let normalized = raw.trim().to_ascii_lowercase().replace('-', "_");
    if matches!(normalized.as_str(), "cli" | "drone_cli") {
        "cli".to_string()
    } else {
        "http".to_string()
    }
}

fn drone_cli_command_from_config(provider_config: &Map<String, Value>) -> String {
    string_from_map(provider_config, "drone_command")
        .or_else(|| string_from_map(provider_config, "cli_command"))
        .or_else(|| string_from_map(provider_config, "command"))
        .or_else(|| drone_config_value_env("DRONE_CLI"))
        .unwrap_or_else(|| "drone".to_string())
}

fn drone_deploy_config(value: Option<&Value>) -> Option<DroneDeployConfig> {
    let map = value.and_then(Value::as_object)?;
    if !bool_from_map_default(map, "enabled", false) {
        return None;
    }
    let mode = string_from_map(map, "mode")
        .unwrap_or_else(|| DEFAULT_DRONE_DEPLOY_MODE.to_string())
        .to_ascii_lowercase();
    let stage =
        string_from_map(map, "stage").unwrap_or_else(|| DEFAULT_DRONE_DEPLOY_STAGE.to_string());
    Some(DroneDeployConfig {
        mode,
        stage,
        required: bool_from_map_default(map, "required", true),
        target: string_from_map(map, "target"),
        docker: map
            .get("docker")
            .cloned()
            .map(object_or_empty)
            .unwrap_or_default(),
        kubernetes: map
            .get("kubernetes")
            .cloned()
            .map(object_or_empty)
            .unwrap_or_default(),
        cli: map
            .get("cli")
            .cloned()
            .map(object_or_empty)
            .unwrap_or_default(),
    })
}

fn add_drone_deploy_params(params: &mut Vec<(String, String)>, deploy: Option<&DroneDeployConfig>) {
    let Some(deploy) = deploy else {
        return;
    };
    insert_default_param(params, "MEMSTACK_DEPLOY_ENABLED", "true");
    insert_default_param(params, "MEMSTACK_DEPLOY_MODE", deploy.mode.clone());
    insert_default_param(params, "MEMSTACK_DEPLOY_STAGE", deploy.stage.clone());
    if let Some(target) = &deploy.target {
        insert_default_param(params, "MEMSTACK_DEPLOY_TARGET", target.clone());
    }
    match deploy.mode.as_str() {
        "docker" => {
            add_prefixed_drone_deploy_params(params, "MEMSTACK_DEPLOY_DOCKER", &deploy.docker)
        }
        "kubernetes" => add_prefixed_drone_deploy_params(
            params,
            "MEMSTACK_DEPLOY_KUBERNETES",
            &deploy.kubernetes,
        ),
        "cli" => add_prefixed_drone_deploy_params(params, "MEMSTACK_DEPLOY_CLI", &deploy.cli),
        _ => {}
    }
}

fn add_prefixed_drone_deploy_params(
    params: &mut Vec<(String, String)>,
    prefix: &str,
    values: &Map<String, Value>,
) {
    for (key, value) in values {
        let Some(param_value) = drone_deploy_param_value(value) else {
            continue;
        };
        let safe_key = drone_deploy_safe_param_key(key);
        if !safe_key.is_empty() {
            insert_default_param(params, format!("{prefix}_{safe_key}"), param_value);
        }
    }
}

fn insert_default_param(
    params: &mut Vec<(String, String)>,
    key: impl Into<String>,
    value: impl Into<String>,
) {
    let key = key.into();
    if params.iter().any(|(existing, _)| existing == &key) {
        return;
    }
    params.push((key, value.into()));
}

fn drone_deploy_safe_param_key(key: &str) -> String {
    key.chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() {
                ch.to_ascii_uppercase()
            } else {
                '_'
            }
        })
        .collect::<String>()
        .trim_matches('_')
        .to_string()
}

fn drone_deploy_param_value(value: &Value) -> Option<String> {
    if value.is_null() {
        None
    } else if let Some(value) = value.as_bool() {
        Some(if value { "true" } else { "false" }.to_string())
    } else if value.is_i64() || value.is_u64() || value.is_f64() {
        Some(value.to_string())
    } else if let Some(value) = value.as_str() {
        metadata_string(Some(&Value::String(value.to_string())))
    } else if let Some(items) = value.as_array() {
        let joined = items
            .iter()
            .filter_map(|item| metadata_string(Some(&Value::String(scalar_to_string(item)))))
            .collect::<Vec<_>>()
            .join(",");
        if joined.is_empty() {
            None
        } else {
            Some(joined)
        }
    } else {
        None
    }
}

fn drone_config_failure_config(message: &str) -> DronePipelineConfig {
    DronePipelineConfig {
        owner: String::new(),
        repo: String::new(),
        server_url: String::new(),
        token: String::new(),
        client: "http".to_string(),
        cli_command: "drone".to_string(),
        host_code_root: None,
        branch: None,
        commit: None,
        params: vec![("__configuration_error__".to_string(), message.to_string())],
        deploy: None,
        timeout_seconds: 1,
        poll_interval_seconds: 1,
    }
}

fn drone_yaml_preflight_failure_result(
    config: &DronePipelineConfig,
) -> Option<DronePipelineResult> {
    let host_code_root = config.host_code_root.as_ref()?;
    let path = host_code_root.join(".drone.yml");
    let content = match std::fs::read_to_string(&path) {
        Ok(content) => content,
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => {
            return Some(drone_preflight_failure_result(
                "Drone build .drone.yml preflight failed: .drone.yml is missing",
                &[".drone.yml is missing".to_string()],
                &["drone_error:missing_config".to_string()],
                config.deploy.as_ref(),
            ));
        }
        Err(err) => {
            return Some(drone_preflight_failure_result(
                &format!("Drone build .drone.yml preflight failed: {err}"),
                &[format!("could not read .drone.yml: {err}")],
                &["drone_error:config_read_failed".to_string()],
                config.deploy.as_ref(),
            ));
        }
    };
    let yaml = match serde_yaml_ng::from_str::<YamlValue>(&content) {
        Ok(value) => value,
        Err(err) => {
            return Some(drone_preflight_failure_result(
                &format!("Drone build .drone.yml preflight failed: {err}"),
                &[format!(".drone.yml parse error: {err}")],
                &[
                    "drone_error:yaml_parse_failed".to_string(),
                    "drone_config:.drone.yml".to_string(),
                ],
                config.deploy.as_ref(),
            ));
        }
    };
    let mut issues = drone_yaml_command_type_issues(&yaml);
    if let Some(deploy) = config
        .deploy
        .as_ref()
        .filter(|deploy| deploy.mode == "docker")
    {
        issues.extend(drone_yaml_docker_deploy_issues(&yaml, deploy));
    }
    dedup_strings(&mut issues);
    if issues.is_empty() {
        return None;
    }
    let mut evidence_refs = vec![
        "drone:preflight_failed".to_string(),
        "drone_config:.drone.yml".to_string(),
    ];
    if issues
        .iter()
        .any(|issue| issue.contains("commands") && issue.contains("string"))
    {
        evidence_refs.push("drone_error:yaml_unmarshal_into_string".to_string());
    }
    if issues
        .iter()
        .any(|issue| issue.contains("required services"))
    {
        evidence_refs.push("drone_error:docker_deploy_missing_required_service".to_string());
    }
    if issues
        .iter()
        .any(|issue| issue.contains("host.docker.internal") || issue.contains("localhost"))
    {
        evidence_refs.push("drone_error:docker_deploy_local_registry".to_string());
    }
    dedup_strings(&mut evidence_refs);
    Some(drone_preflight_failure_result(
        &format!(
            "Drone build .drone.yml preflight failed: {}",
            issues
                .iter()
                .take(4)
                .cloned()
                .collect::<Vec<_>>()
                .join("; ")
        ),
        &issues,
        &evidence_refs,
        config.deploy.as_ref(),
    ))
}

fn drone_preflight_failure_result(
    reason: &str,
    issues: &[String],
    evidence_refs: &[String],
    deploy: Option<&DroneDeployConfig>,
) -> DronePipelineResult {
    let preview = compact_text(reason, 4_000);
    let mut metadata = Map::new();
    metadata.insert("external_provider".to_string(), json!(DRONE_PROVIDER));
    metadata.insert(
        "drone_preflight".to_string(),
        json!(DRONE_YAML_PREFLIGHT_VALIDATION),
    );
    metadata.insert("drone_preflight_status".to_string(), json!("failed"));
    metadata.insert("drone_config_path".to_string(), json!(".drone.yml"));
    metadata.insert(
        "drone_preflight_issues".to_string(),
        json!(issues.iter().take(8).cloned().collect::<Vec<_>>()),
    );
    if let Some(deploy) = deploy {
        metadata.extend(drone_deploy_metadata(Some(deploy), Some("invalid"), issues));
        metadata.insert(
            "deploy_preflight_validation".to_string(),
            json!(DRONE_YAML_PREFLIGHT_VALIDATION),
        );
    }

    let mut stage_metadata = Map::new();
    stage_metadata.insert("external_provider".to_string(), json!(DRONE_PROVIDER));
    stage_metadata.insert(
        "drone_preflight".to_string(),
        json!(DRONE_YAML_PREFLIGHT_VALIDATION),
    );
    stage_metadata.insert("drone_config_path".to_string(), json!(".drone.yml"));
    stage_metadata.insert(
        "drone_preflight_issues".to_string(),
        json!(issues.iter().take(8).cloned().collect::<Vec<_>>()),
    );

    let mut refs = vec!["ci_pipeline:failed".to_string()];
    refs.extend(evidence_refs.iter().cloned());
    if deploy.is_some() {
        refs.push("deployment:invalid:docker".to_string());
    }
    dedup_strings(&mut refs);

    DronePipelineResult {
        status: "failed".to_string(),
        reason: Some(preview.clone()),
        stage_results: vec![DronePipelineStageResult {
            stage: "drone_preflight".to_string(),
            status: "failed".to_string(),
            command: "drone:preflight .drone.yml".to_string(),
            exit_code: Some(1),
            stdout_preview: String::new(),
            stderr_preview: preview,
            duration_ms: 0,
            log_ref: Some("drone://preflight/.drone.yml".to_string()),
            artifact_refs: vec!["drone_config:.drone.yml".to_string()],
            metadata: stage_metadata,
        }],
        evidence_refs: refs,
        external_id: None,
        external_url: None,
        metadata,
    }
}

fn drone_yaml_command_type_issues(yaml: &YamlValue) -> Vec<String> {
    let mut issues = Vec::new();
    for (index, step) in drone_yaml_steps(yaml).iter().enumerate() {
        let step_name = drone_yaml_step_name(step, index);
        let Some(commands) = yaml_get(step, "commands") else {
            continue;
        };
        let Some(commands) = yaml_sequence(commands) else {
            issues.push(format!(
                "steps[{step_name}].commands must be a list of strings"
            ));
            continue;
        };
        for (command_index, command) in commands.iter().enumerate() {
            if yaml_string(command).is_none() {
                issues.push(format!(
                    "steps[{step_name}].commands[{command_index}] must be a string"
                ));
            }
        }
    }
    issues
}

fn drone_yaml_docker_deploy_issues(yaml: &YamlValue, deploy: &DroneDeployConfig) -> Vec<String> {
    let deploy_commands = drone_yaml_deploy_commands(yaml, deploy);
    if deploy_commands.is_empty() {
        return vec![format!("docker deploy stage {} is missing", deploy.stage)];
    }
    let output = deploy_commands.join("\n").to_ascii_lowercase();
    let mut issues = Vec::new();
    if drone_docker_deploy_uses_forbidden_local_registry_pull(&output) {
        issues.push(
            "deploy step pulls or runs host.docker.internal/localhost local-registry images through the mounted host Docker daemon".to_string(),
        );
    }
    let missing_services = drone_missing_docker_deploy_required_services(&output, deploy);
    if !missing_services.is_empty() {
        issues.push(format!(
            "docker deploy stage {} does not cover required services: {}",
            deploy.stage,
            missing_services.join(", ")
        ));
    }
    if !drone_docker_deploy_has_run_marker(&output) {
        issues.push(format!(
            "docker deploy stage {} missing docker run/compose/stack/service deploy command",
            deploy.stage
        ));
    }
    issues
}

fn drone_yaml_deploy_commands(yaml: &YamlValue, deploy: &DroneDeployConfig) -> Vec<String> {
    drone_yaml_steps(yaml)
        .into_iter()
        .filter(|step| {
            yaml_get(step, "name")
                .and_then(yaml_string)
                .is_some_and(|name| drone_is_deploy_label(name, deploy))
        })
        .filter_map(|step| yaml_get(step, "commands"))
        .filter_map(yaml_sequence)
        .flat_map(|commands| commands.iter().filter_map(yaml_string))
        .map(ToOwned::to_owned)
        .collect()
}

fn drone_yaml_steps(yaml: &YamlValue) -> Vec<&YamlValue> {
    yaml_get(yaml, "steps")
        .and_then(yaml_sequence)
        .map(|steps| steps.iter().collect())
        .unwrap_or_default()
}

fn drone_yaml_step_name(step: &YamlValue, index: usize) -> String {
    yaml_get(step, "name")
        .and_then(yaml_string)
        .filter(|value| !value.trim().is_empty())
        .map(ToOwned::to_owned)
        .unwrap_or_else(|| index.to_string())
}

fn yaml_get<'a>(value: &'a YamlValue, key: &str) -> Option<&'a YamlValue> {
    let YamlValue::Mapping(map) = value else {
        return None;
    };
    map.get(YamlValue::String(key.to_string()))
}

fn yaml_sequence(value: &YamlValue) -> Option<&Vec<YamlValue>> {
    match value {
        YamlValue::Sequence(items) => Some(items),
        _ => None,
    }
}

fn yaml_string(value: &YamlValue) -> Option<&str> {
    match value {
        YamlValue::String(text) => Some(text),
        _ => None,
    }
}

async fn run_drone_pipeline(config: &DronePipelineConfig) -> CoreResult<DronePipelineResult> {
    if let Some((_, message)) = config
        .params
        .iter()
        .find(|(key, _)| key == "__configuration_error__")
    {
        return Ok(drone_configuration_failure_result(message));
    }
    if let Some(result) = drone_yaml_preflight_failure_result(config) {
        return Ok(result);
    }

    if config.client == "cli" {
        match run_drone_pipeline_cli(config).await {
            Ok(mut result) => {
                result
                    .metadata
                    .insert("drone_client".to_string(), json!("cli"));
                return Ok(result);
            }
            Err(err) if is_drone_cli_unavailable_error(&err) => {
                let mut result = run_drone_pipeline_http(config).await?;
                result
                    .metadata
                    .insert("drone_client".to_string(), json!("http_fallback"));
                return Ok(result);
            }
            Err(err) => return Err(err),
        }
    }

    run_drone_pipeline_http(config).await
}

async fn run_drone_pipeline_http(config: &DronePipelineConfig) -> CoreResult<DronePipelineResult> {
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(30))
        .build()
        .map_err(|err| CoreError::Storage(format!("Drone HTTP client error: {err}")))?;
    ensure_drone_repo_enabled(&client, config).await?;
    ensure_drone_docker_deploy_repo_trusted(&client, config).await?;
    let running = running_drone_build_for_commit(&client, config).await?;
    let build_number = if let Some(build) = running {
        required_i64(build.get("number"), "Drone build number")?
    } else {
        let created = create_drone_build(&client, config).await?;
        required_i64(created.get("number"), "Drone build number")?
    };
    let build = poll_drone_build(&client, config, build_number).await?;
    drone_result_from_build(&client, config, &build).await
}

async fn run_drone_pipeline_cli(config: &DronePipelineConfig) -> CoreResult<DronePipelineResult> {
    ensure_drone_repo_enabled_cli(config).await?;
    ensure_drone_docker_deploy_repo_trusted_cli(config).await?;
    let running = running_drone_build_for_commit_cli(config).await?;
    let build_number = if let Some(build) = running {
        required_i64(build.get("number"), "Drone build number")?
    } else {
        let created = create_drone_build_cli(config).await?;
        required_i64(created.get("number"), "Drone build number")?
    };
    let build = poll_drone_build_cli(config, build_number).await?;
    drone_result_from_build_cli(config, &build).await
}

async fn ensure_drone_repo_enabled_cli(config: &DronePipelineConfig) -> CoreResult<()> {
    match drone_cli_json_object(config, &["repo", "info", &config.repo_slug()]).await {
        Ok(repo) => {
            if repo.get("active").and_then(Value::as_bool) == Some(false) {
                let _ = drone_cli_text(config, &["repo", "enable", &config.repo_slug()]).await?;
            }
            Ok(())
        }
        Err(err) if looks_like_drone_not_found(&err.to_string()) => {
            let _ = drone_cli_text(config, &["repo", "enable", &config.repo_slug()]).await?;
            Ok(())
        }
        Err(err) => Err(err),
    }
}

async fn ensure_drone_docker_deploy_repo_trusted_cli(
    config: &DronePipelineConfig,
) -> CoreResult<()> {
    if !drone_docker_deploy_requires_trusted_repo(config.deploy.as_ref()) {
        return Ok(());
    }
    let repo = drone_cli_json_object(config, &["repo", "info", &config.repo_slug()]).await?;
    if repo.get("trusted").and_then(Value::as_bool) == Some(true) {
        return Ok(());
    }
    let _ = drone_cli_text(
        config,
        &["repo", "update", &config.repo_slug(), "--trusted"],
    )
    .await?;
    let updated = drone_cli_json_object(config, &["repo", "info", &config.repo_slug()])
        .await
        .unwrap_or_else(|_| {
            let mut updated = Map::new();
            updated.insert("trusted".to_string(), json!(true));
            updated
        });
    if updated.get("trusted").and_then(Value::as_bool) != Some(true) {
        return Err(CoreError::Storage(format!(
            "Drone repo {} must be trusted for docker deploy host volumes",
            config.repo_slug()
        )));
    }
    Ok(())
}

async fn running_drone_build_for_commit_cli(
    config: &DronePipelineConfig,
) -> CoreResult<Option<Value>> {
    let Some(commit) = config.commit.as_deref() else {
        return Ok(None);
    };
    let builds = drone_cli_build_list(config, 25).await;
    let Ok(builds) = builds else {
        return Ok(None);
    };
    Ok(builds.into_iter().find(|build| {
        let status = drone_status(build.get("status"));
        is_drone_running_status(&status) && drone_build_matches_commit(build, commit)
    }))
}

async fn create_drone_build_cli(config: &DronePipelineConfig) -> CoreResult<Value> {
    let mut args = vec![
        "build".to_string(),
        "create".to_string(),
        config.repo_slug(),
    ];
    if let Some(branch) = &config.branch {
        args.push(format!("--branch={branch}"));
    }
    if let Some(commit) = &config.commit {
        args.push(format!("--commit={commit}"));
    }
    for (key, value) in &config.params {
        args.push(format!("--param={key}={value}"));
    }
    drone_cli_json_value_owned(config, args).await
}

async fn poll_drone_build_cli(
    config: &DronePipelineConfig,
    build_number: i64,
) -> CoreResult<Value> {
    let started = Instant::now();
    let mut latest: Option<Value> = None;
    loop {
        let build = drone_cli_json_value_owned(
            config,
            vec![
                "build".to_string(),
                "info".to_string(),
                config.repo_slug(),
                build_number.to_string(),
            ],
        )
        .await?;
        let status = drone_status(build.get("status"));
        if is_drone_terminal_status(&status) {
            return Ok(build);
        }
        if started.elapsed() >= Duration::from_secs(config.timeout_seconds.max(1)) {
            let _ = drone_cli_text_owned(
                config,
                vec![
                    "build".to_string(),
                    "stop".to_string(),
                    config.repo_slug(),
                    build_number.to_string(),
                ],
            )
            .await;
            let mut timeout_build = object_or_empty(latest.unwrap_or(build));
            timeout_build.insert("number".to_string(), json!(build_number));
            timeout_build.insert("status".to_string(), json!("timeout"));
            return Ok(Value::Object(timeout_build));
        }
        latest = Some(build);
        sleep(Duration::from_secs(config.poll_interval_seconds.max(1))).await;
    }
}

async fn drone_result_from_build_cli(
    config: &DronePipelineConfig,
    build: &Value,
) -> CoreResult<DronePipelineResult> {
    let build_number = required_i64(build.get("number"), "Drone build number")?;
    let external_url = config.build_url(build_number);
    let stage_results = drone_stage_results_cli(config, build_number, build, &external_url).await;
    drone_result_from_build_and_stages(config, build, stage_results)
}

async fn drone_stage_results_cli(
    config: &DronePipelineConfig,
    build_number: i64,
    build: &Value,
    external_url: &str,
) -> Vec<DronePipelineStageResult> {
    let Some(stages) = build.get("stages").and_then(Value::as_array) else {
        return vec![drone_pipeline_stage_result(
            config,
            build_number,
            "drone",
            "build",
            drone_status(build.get("status")),
            optional_i32(build.get("exit_code")),
            String::new(),
            build.get("error").and_then(Value::as_str).unwrap_or(""),
            external_url,
            config.deploy.as_ref(),
        )];
    };
    let mut output = Vec::new();
    for stage in stages {
        let stage_name = stage
            .get("name")
            .and_then(Value::as_str)
            .filter(|value| !value.trim().is_empty())
            .unwrap_or("stage");
        let stage_log_ref = log_part(stage.get("number")).unwrap_or_else(|| stage_name.to_string());
        if let Some(steps) = stage.get("steps").and_then(Value::as_array) {
            for step in steps {
                let step_name = step
                    .get("name")
                    .and_then(Value::as_str)
                    .filter(|value| !value.trim().is_empty())
                    .unwrap_or("step");
                let step_log_ref =
                    log_part(step.get("number")).unwrap_or_else(|| step_name.to_string());
                let log_text = drone_cli_text_owned(
                    config,
                    vec![
                        "log".to_string(),
                        "view".to_string(),
                        config.repo_slug(),
                        build_number.to_string(),
                        stage_log_ref.clone(),
                        step_log_ref,
                    ],
                )
                .await
                .unwrap_or_default();
                output.push(drone_pipeline_stage_result(
                    config,
                    build_number,
                    stage_name,
                    step_name,
                    drone_status(step.get("status")),
                    optional_i32(step.get("exit_code")),
                    log_text,
                    step.get("error").and_then(Value::as_str).unwrap_or(""),
                    external_url,
                    config.deploy.as_ref(),
                ));
            }
        } else {
            output.push(drone_pipeline_stage_result(
                config,
                build_number,
                stage_name,
                stage_name,
                drone_status(stage.get("status")),
                optional_i32(stage.get("exit_code")),
                String::new(),
                stage.get("error").and_then(Value::as_str).unwrap_or(""),
                external_url,
                config.deploy.as_ref(),
            ));
        }
    }
    if output.is_empty() {
        output.push(drone_pipeline_stage_result(
            config,
            build_number,
            "drone",
            "build",
            drone_status(build.get("status")),
            optional_i32(build.get("exit_code")),
            String::new(),
            build.get("error").and_then(Value::as_str).unwrap_or(""),
            external_url,
            config.deploy.as_ref(),
        ));
    }
    output
}

async fn drone_cli_build_list(
    config: &DronePipelineConfig,
    per_page: usize,
) -> CoreResult<Vec<Value>> {
    let text = drone_cli_text_owned(
        config,
        vec![
            "build".to_string(),
            "ls".to_string(),
            config.repo_slug(),
            format!("--limit={}", per_page.max(1)),
            "--format".to_string(),
            DRONE_CLI_JSON_TEMPLATE.to_string(),
        ],
    )
    .await?;
    Ok(text
        .lines()
        .filter_map(|line| serde_json::from_str::<Value>(line).ok())
        .filter(|value| value.is_object())
        .collect())
}

async fn drone_cli_json_object(
    config: &DronePipelineConfig,
    args: &[&str],
) -> CoreResult<Map<String, Value>> {
    let value = drone_cli_json_value(config, args).await?;
    match value {
        Value::Object(map) => Ok(map),
        _ => Err(CoreError::Storage(
            "Drone CLI JSON response was not an object".to_string(),
        )),
    }
}

async fn drone_cli_json_value(config: &DronePipelineConfig, args: &[&str]) -> CoreResult<Value> {
    drone_cli_json_value_owned(config, args.iter().map(|arg| (*arg).to_string()).collect()).await
}

async fn drone_cli_json_value_owned(
    config: &DronePipelineConfig,
    mut args: Vec<String>,
) -> CoreResult<Value> {
    args.push("--format".to_string());
    args.push(DRONE_CLI_JSON_TEMPLATE.to_string());
    let arg_refs = args.iter().map(String::as_str).collect::<Vec<_>>();
    let text = drone_cli_text(config, &arg_refs).await?;
    serde_json::from_str(&text)
        .map_err(|err| CoreError::Storage(format!("Drone CLI returned invalid JSON: {err}")))
}

async fn drone_cli_text(config: &DronePipelineConfig, args: &[&str]) -> CoreResult<String> {
    let output = run_drone_cli_command(config, args).await?;
    if output.exit_code != 0 {
        let text = if output.stderr.trim().is_empty() {
            output.stdout.trim()
        } else {
            output.stderr.trim()
        };
        return Err(CoreError::Storage(format!(
            "Drone CLI command failed: {}",
            compact_text(text, 600)
        )));
    }
    Ok(output.stdout)
}

async fn drone_cli_text_owned(
    config: &DronePipelineConfig,
    args: Vec<String>,
) -> CoreResult<String> {
    let arg_refs = args.iter().map(String::as_str).collect::<Vec<_>>();
    drone_cli_text(config, &arg_refs).await
}

async fn run_drone_cli_command(
    config: &DronePipelineConfig,
    args: &[&str],
) -> CoreResult<GitCommandOutput> {
    let mut command = tokio::process::Command::new(&config.cli_command);
    command
        .args(args)
        .env(DRONE_SERVER_ENV, &config.server_url)
        .env(DRONE_TOKEN_ENV, &config.token)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    let output = tokio::time::timeout(Duration::from_secs(30), command.output())
        .await
        .map_err(|_| {
            CoreError::Storage(format!(
                "Drone CLI {} timed out after 30s",
                config.cli_command
            ))
        })?
        .map_err(|err| {
            if err.kind() == std::io::ErrorKind::NotFound {
                CoreError::Storage(format!(
                    "Drone CLI executable not found: {}",
                    config.cli_command
                ))
            } else {
                CoreError::Storage(format!(
                    "Drone CLI {} failed to start: {err}",
                    config.cli_command
                ))
            }
        })?;
    Ok(GitCommandOutput {
        exit_code: output.status.code().unwrap_or(1),
        stdout: String::from_utf8_lossy(&output.stdout).into_owned(),
        stderr: String::from_utf8_lossy(&output.stderr).into_owned(),
    })
}

fn is_drone_cli_unavailable_error(err: &CoreError) -> bool {
    err.to_string()
        .to_ascii_lowercase()
        .contains("drone cli executable not found")
}

async fn ensure_drone_repo_enabled(
    client: &reqwest::Client,
    config: &DronePipelineConfig,
) -> CoreResult<()> {
    match drone_api_request(
        client,
        config,
        reqwest::Method::GET,
        &drone_repo_path(config),
        &[],
    )
    .await
    {
        Ok(repo) => {
            if repo.get("active").and_then(Value::as_bool) == Some(false) {
                let _ = drone_api_request(
                    client,
                    config,
                    reqwest::Method::POST,
                    &drone_repo_path(config),
                    &[],
                )
                .await
                .map_err(CoreError::Storage)?;
            }
            Ok(())
        }
        Err(err) if looks_like_drone_not_found(&err) => {
            let _ = drone_api_request(
                client,
                config,
                reqwest::Method::POST,
                &drone_repo_path(config),
                &[],
            )
            .await
            .map_err(CoreError::Storage)?;
            Ok(())
        }
        Err(err) => Err(CoreError::Storage(err)),
    }
}

async fn ensure_drone_docker_deploy_repo_trusted(
    client: &reqwest::Client,
    config: &DronePipelineConfig,
) -> CoreResult<()> {
    if !drone_docker_deploy_requires_trusted_repo(config.deploy.as_ref()) {
        return Ok(());
    }
    let repo = drone_api_request(
        client,
        config,
        reqwest::Method::GET,
        &drone_repo_path(config),
        &[],
    )
    .await
    .map_err(CoreError::Storage)?;
    if repo.get("trusted").and_then(Value::as_bool) == Some(true) {
        return Ok(());
    }
    let updated = drone_api_json_request(
        client,
        config,
        reqwest::Method::PATCH,
        &drone_repo_path(config),
        &[],
        Some(&json!({"trusted": true})),
    )
    .await
    .map_err(CoreError::Storage)?;
    if updated.get("trusted").and_then(Value::as_bool) != Some(true) {
        return Err(CoreError::Storage(format!(
            "Drone repo {} must be trusted for docker deploy host volumes",
            config.repo_slug()
        )));
    }
    Ok(())
}

fn drone_docker_deploy_requires_trusted_repo(deploy: Option<&DroneDeployConfig>) -> bool {
    let Some(deploy) = deploy else {
        return false;
    };
    if deploy.mode != "docker" {
        return false;
    }
    deploy
        .docker
        .get("trusted")
        .and_then(Value::as_bool)
        .unwrap_or(true)
}

async fn running_drone_build_for_commit(
    client: &reqwest::Client,
    config: &DronePipelineConfig,
) -> CoreResult<Option<Value>> {
    let Some(commit) = config.commit.as_deref() else {
        return Ok(None);
    };
    let builds = drone_api_request(
        client,
        config,
        reqwest::Method::GET,
        &drone_repo_child_path(config, &["builds"]),
        &[("per_page", "25".to_string())],
    )
    .await;
    let Ok(Value::Array(builds)) = builds else {
        return Ok(None);
    };
    Ok(builds.into_iter().find(|build| {
        let status = drone_status(build.get("status"));
        is_drone_running_status(&status) && drone_build_matches_commit(build, commit)
    }))
}

async fn create_drone_build(
    client: &reqwest::Client,
    config: &DronePipelineConfig,
) -> CoreResult<Value> {
    let mut query = config
        .params
        .iter()
        .map(|(key, value)| (key.as_str(), value.clone()))
        .collect::<Vec<_>>();
    if let Some(branch) = &config.branch {
        query.push(("branch", branch.clone()));
    }
    if let Some(commit) = &config.commit {
        query.push(("commit", commit.clone()));
    }
    drone_api_request(
        client,
        config,
        reqwest::Method::POST,
        &drone_repo_child_path(config, &["builds"]),
        &query,
    )
    .await
    .map_err(CoreError::Storage)
}

async fn poll_drone_build(
    client: &reqwest::Client,
    config: &DronePipelineConfig,
    build_number: i64,
) -> CoreResult<Value> {
    let started = Instant::now();
    let path = drone_repo_child_path(config, &["builds", &build_number.to_string()]);
    let mut latest: Option<Value> = None;
    loop {
        let build = drone_api_request(client, config, reqwest::Method::GET, &path, &[])
            .await
            .map_err(CoreError::Storage)?;
        let status = drone_status(build.get("status"));
        if is_drone_terminal_status(&status) {
            return Ok(build);
        }
        if started.elapsed() >= Duration::from_secs(config.timeout_seconds.max(1)) {
            let _ = drone_api_request(client, config, reqwest::Method::DELETE, &path, &[]).await;
            let mut timeout_build = object_or_empty(latest.unwrap_or(build));
            timeout_build.insert("number".to_string(), json!(build_number));
            timeout_build.insert("status".to_string(), json!("timeout"));
            return Ok(Value::Object(timeout_build));
        }
        latest = Some(build);
        sleep(Duration::from_secs(config.poll_interval_seconds.max(1))).await;
    }
}

async fn drone_result_from_build(
    client: &reqwest::Client,
    config: &DronePipelineConfig,
    build: &Value,
) -> CoreResult<DronePipelineResult> {
    let build_number = required_i64(build.get("number"), "Drone build number")?;
    let external_url = config.build_url(build_number);
    let stage_results =
        drone_stage_results(client, config, build_number, build, &external_url).await;
    drone_result_from_build_and_stages(config, build, stage_results)
}

fn drone_result_from_build_and_stages(
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

async fn drone_stage_results(
    client: &reqwest::Client,
    config: &DronePipelineConfig,
    build_number: i64,
    build: &Value,
    external_url: &str,
) -> Vec<DronePipelineStageResult> {
    let Some(stages) = build.get("stages").and_then(Value::as_array) else {
        return vec![drone_pipeline_stage_result(
            config,
            build_number,
            "drone",
            "build",
            drone_status(build.get("status")),
            optional_i32(build.get("exit_code")),
            String::new(),
            build.get("error").and_then(Value::as_str).unwrap_or(""),
            external_url,
            config.deploy.as_ref(),
        )];
    };
    let mut output = Vec::new();
    for stage in stages {
        let stage_name = stage
            .get("name")
            .and_then(Value::as_str)
            .filter(|value| !value.trim().is_empty())
            .unwrap_or("stage");
        let stage_log_ref = log_part(stage.get("number")).unwrap_or_else(|| stage_name.to_string());
        if let Some(steps) = stage.get("steps").and_then(Value::as_array) {
            for step in steps {
                let step_name = step
                    .get("name")
                    .and_then(Value::as_str)
                    .filter(|value| !value.trim().is_empty())
                    .unwrap_or("step");
                let step_log_ref =
                    log_part(step.get("number")).unwrap_or_else(|| step_name.to_string());
                let log_text = drone_logs_text(
                    drone_api_request(
                        client,
                        config,
                        reqwest::Method::GET,
                        &drone_repo_child_path(
                            config,
                            &[
                                "builds",
                                &build_number.to_string(),
                                "logs",
                                &stage_log_ref,
                                &step_log_ref,
                            ],
                        ),
                        &[],
                    )
                    .await
                    .ok()
                    .as_ref(),
                );
                output.push(drone_pipeline_stage_result(
                    config,
                    build_number,
                    stage_name,
                    step_name,
                    drone_status(step.get("status")),
                    optional_i32(step.get("exit_code")),
                    log_text,
                    step.get("error").and_then(Value::as_str).unwrap_or(""),
                    external_url,
                    config.deploy.as_ref(),
                ));
            }
        } else {
            output.push(drone_pipeline_stage_result(
                config,
                build_number,
                stage_name,
                stage_name,
                drone_status(stage.get("status")),
                optional_i32(stage.get("exit_code")),
                String::new(),
                stage.get("error").and_then(Value::as_str).unwrap_or(""),
                external_url,
                config.deploy.as_ref(),
            ));
        }
    }
    if output.is_empty() {
        output.push(drone_pipeline_stage_result(
            config,
            build_number,
            "drone",
            "build",
            drone_status(build.get("status")),
            optional_i32(build.get("exit_code")),
            String::new(),
            build.get("error").and_then(Value::as_str).unwrap_or(""),
            external_url,
            config.deploy.as_ref(),
        ));
    }
    output
}

fn drone_pipeline_stage_result(
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

async fn finish_drone_pipeline_result(
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

fn drone_configuration_failure_result(message: &str) -> DronePipelineResult {
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

fn drone_api_failure_result(message: &str) -> DronePipelineResult {
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

async fn drone_api_request(
    client: &reqwest::Client,
    config: &DronePipelineConfig,
    method: reqwest::Method,
    path: &str,
    query: &[(&str, String)],
) -> Result<Value, String> {
    drone_api_json_request(client, config, method, path, query, None).await
}

async fn drone_api_json_request(
    client: &reqwest::Client,
    config: &DronePipelineConfig,
    method: reqwest::Method,
    path: &str,
    query: &[(&str, String)],
    json_body: Option<&Value>,
) -> Result<Value, String> {
    let url = format!("{}{}", config.server_url.trim_end_matches('/'), path);
    let mut request = client
        .request(method.clone(), &url)
        .bearer_auth(&config.token)
        .query(query);
    if let Some(json_body) = json_body {
        request = request.json(json_body);
    }
    let response = request
        .send()
        .await
        .map_err(|err| format!("Drone API {method} {path} failed: {err}"))?;
    let status = response.status();
    let body = response
        .text()
        .await
        .map_err(|err| format!("Drone API {method} {path} body failed: {err}"))?;
    if !status.is_success() {
        return Err(format!(
            "Drone API {method} {path} returned {}: {}",
            status.as_u16(),
            compact_text(&body, 600)
        ));
    }
    serde_json::from_str(&body)
        .map_err(|err| format!("Drone API {method} {path} returned invalid JSON: {err}"))
}

fn drone_repo_path(config: &DronePipelineConfig) -> String {
    drone_repo_child_path(config, &[])
}

fn drone_repo_child_path(config: &DronePipelineConfig, parts: &[&str]) -> String {
    let mut path = format!(
        "/api/repos/{}/{}",
        drone_path_segment(&config.owner),
        drone_path_segment(&config.repo)
    );
    for part in parts {
        path.push('/');
        path.push_str(&drone_path_segment(part));
    }
    path
}

fn drone_path_segment(value: &str) -> String {
    url::form_urlencoded::byte_serialize(value.as_bytes()).collect()
}

fn looks_like_drone_not_found(message: &str) -> bool {
    let lower = message.to_ascii_lowercase();
    lower.contains(" 404") || lower.contains("not found") || lower.contains("not enabled")
}

fn drone_config_value_env(name: &str) -> Option<String> {
    std::env::var(name)
        .ok()
        .and_then(|value| metadata_string(Some(&Value::String(value))))
        .or_else(|| source_publish_dotenv_value(name))
}

fn string_pairs_from_map(value: Option<&Value>) -> Vec<(String, String)> {
    value
        .and_then(Value::as_object)
        .map(|map| {
            map.iter()
                .filter_map(|(key, value)| {
                    if value.is_null() {
                        None
                    } else {
                        Some((key.clone(), scalar_to_string(value)))
                    }
                })
                .collect()
        })
        .unwrap_or_default()
}

fn scalar_to_string(value: &Value) -> String {
    value
        .as_str()
        .map_or_else(|| value.to_string(), ToOwned::to_owned)
}

fn positive_u64_from_map(map: &Map<String, Value>, key: &str, fallback: u64) -> u64 {
    map.get(key)
        .and_then(|value| {
            value
                .as_u64()
                .or_else(|| value.as_str()?.trim().parse::<u64>().ok())
        })
        .filter(|value| *value > 0)
        .unwrap_or(fallback.max(1))
}

fn required_i64(value: Option<&Value>, label: &str) -> CoreResult<i64> {
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

fn optional_i32(value: Option<&Value>) -> Option<i32> {
    optional_i64(value).and_then(|value| i32::try_from(value).ok())
}

fn drone_status(value: Option<&Value>) -> String {
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

fn is_drone_terminal_status(status: &str) -> bool {
    matches!(
        status,
        "success" | "failure" | "error" | "killed" | "declined" | "skipped"
    )
}

fn is_drone_running_status(status: &str) -> bool {
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

fn drone_build_matches_commit(build: &Value, commit: &str) -> bool {
    ["after", "commit", "sha"].iter().any(|key| {
        build
            .get(*key)
            .and_then(Value::as_str)
            .is_some_and(|value| {
                value == commit || value.starts_with(commit) || commit.starts_with(value)
            })
    })
}

fn log_part(value: Option<&Value>) -> Option<String> {
    if let Some(number) = optional_i64(value).filter(|number| *number > 0) {
        return Some(number.to_string());
    }
    value
        .and_then(Value::as_str)
        .and_then(|value| metadata_string(Some(&Value::String(value.to_string()))))
}

fn drone_logs_text(value: Option<&Value>) -> String {
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

fn drone_is_deploy_stage(
    stage_name: &str,
    step_name: &str,
    deploy: Option<&DroneDeployConfig>,
) -> bool {
    let Some(deploy) = deploy else {
        return false;
    };
    drone_is_deploy_label(stage_name, deploy) || drone_is_deploy_label(step_name, deploy)
}

fn drone_is_deploy_label(value: &str, deploy: &DroneDeployConfig) -> bool {
    let normalized = value.trim().to_ascii_lowercase();
    let configured = deploy.stage.trim().to_ascii_lowercase();
    normalized == configured
        || normalized.ends_with(&format!("/{configured}"))
        || normalized.starts_with("deploy-")
        || normalized.ends_with("-deploy")
        || normalized == "deployment"
}

fn drone_deploy_state(
    stages: &[DronePipelineStageResult],
    deploy: Option<&DroneDeployConfig>,
) -> Option<String> {
    let deploy = deploy?;
    let deploy_results = stages
        .iter()
        .filter(|stage| {
            stage
                .metadata
                .get("drone_step_kind")
                .and_then(Value::as_str)
                == Some("deploy")
                || drone_is_deploy_label(&stage.stage, deploy)
        })
        .collect::<Vec<_>>();
    if deploy_results.is_empty() {
        return Some("missing".to_string());
    }
    if !deploy_results
        .iter()
        .all(|stage| matches!(stage.status.as_str(), "success" | "skipped"))
    {
        return Some("failed".to_string());
    }
    if !deploy_results
        .iter()
        .any(|stage| drone_deploy_result_matches_mode(stage, deploy, stages))
    {
        return Some("invalid".to_string());
    }
    Some("passed".to_string())
}

fn drone_deploy_result_matches_mode(
    stage: &DronePipelineStageResult,
    deploy: &DroneDeployConfig,
    stages: &[DronePipelineStageResult],
) -> bool {
    match deploy.mode.as_str() {
        "docker" => drone_docker_deploy_validation_issues(stage, deploy, stages).is_empty(),
        "kubernetes" => {
            let image = stage
                .metadata
                .get("drone_image")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_ascii_lowercase();
            let output = drone_stage_output(stage).to_ascii_lowercase();
            image.contains("kubectl")
                || output.contains("kubectl apply")
                || output.contains("helm upgrade")
        }
        "cli" => true,
        _ => false,
    }
}

fn drone_deploy_validation_issues(
    stages: &[DronePipelineStageResult],
    deploy: Option<&DroneDeployConfig>,
) -> Vec<String> {
    let Some(deploy) = deploy else {
        return Vec::new();
    };
    if deploy.mode != "docker" {
        return Vec::new();
    }
    let mut issues = Vec::new();
    for stage in stages.iter().filter(|stage| {
        stage
            .metadata
            .get("drone_step_kind")
            .and_then(Value::as_str)
            == Some("deploy")
            || drone_is_deploy_label(&stage.stage, deploy)
    }) {
        let stage_issues = drone_docker_deploy_validation_issues(stage, deploy, stages);
        if stage_issues.is_empty() {
            return Vec::new();
        }
        issues.extend(stage_issues);
    }
    dedup_strings(&mut issues);
    issues
}

fn drone_docker_deploy_validation_issues(
    stage: &DronePipelineStageResult,
    deploy: &DroneDeployConfig,
    stages: &[DronePipelineStageResult],
) -> Vec<String> {
    let output = drone_stage_output(stage).to_ascii_lowercase();
    let mut issues = Vec::new();
    if drone_docker_deploy_output_masks_failure(&output) {
        issues.push(
            "deploy output contains failure markers despite a successful Drone step".to_string(),
        );
    }
    if drone_docker_deploy_uses_forbidden_local_registry_pull(&output) {
        issues.push(
            "deploy step pulls or runs host.docker.internal/localhost local-registry images through the mounted host Docker daemon".to_string(),
        );
    }
    let missing_services = drone_missing_docker_deploy_required_services(&output, deploy);
    if !missing_services.is_empty() {
        issues.push(format!(
            "missing required deploy services: {}",
            missing_services.join(", ")
        ));
    }
    let missing_images = drone_missing_docker_deploy_built_images(&output, deploy, stages);
    if !missing_images.is_empty() {
        issues.push(format!(
            "missing built image deploy references: {}",
            missing_images.join(", ")
        ));
    }
    if !drone_docker_deploy_has_run_marker(&output) {
        issues.push("missing docker run/compose/stack/service deploy command".to_string());
    }
    dedup_strings(&mut issues);
    issues
}

fn drone_deploy_failure_reason(
    deploy: &DroneDeployConfig,
    external_id: &str,
    deploy_state: &str,
    validation_issues: &[String],
) -> String {
    match deploy_state {
        "missing" => format!(
            "Drone build {external_id} did not report deploy stage {}",
            deploy.stage
        ),
        "invalid" => {
            if validation_issues.is_empty() {
                format!(
                    "Drone build {external_id} deploy stage {} did not implement {} deployment semantics",
                    deploy.stage, deploy.mode
                )
            } else {
                format!(
                    "Drone build {external_id} deploy stage {} did not implement {} deployment semantics: {}",
                    deploy.stage,
                    deploy.mode,
                    validation_issues
                        .iter()
                        .take(4)
                        .cloned()
                        .collect::<Vec<_>>()
                        .join("; ")
                )
            }
        }
        _ => format!(
            "Drone build {external_id} deploy stage {} failed",
            deploy.stage
        ),
    }
}

fn drone_deploy_metadata(
    deploy: Option<&DroneDeployConfig>,
    deploy_state: Option<&str>,
    validation_issues: &[String],
) -> Map<String, Value> {
    let mut metadata = Map::new();
    let Some(deploy) = deploy else {
        return metadata;
    };
    metadata.insert("deploy_enabled".to_string(), json!(true));
    metadata.insert("deploy_mode".to_string(), json!(deploy.mode));
    metadata.insert("deploy_stage".to_string(), json!(deploy.stage));
    metadata.insert(
        "deployment_status".to_string(),
        match deploy_state {
            Some("passed") => json!("deployed"),
            Some(state @ ("failed" | "missing" | "invalid")) => json!(state),
            _ => Value::Null,
        },
    );
    if let Some(target) = &deploy.target {
        metadata.insert("deploy_target".to_string(), json!(target));
    }
    if deploy.mode == "docker" && deploy_state == Some("passed") {
        metadata.insert(
            "deploy_validation".to_string(),
            json!(DRONE_DOCKER_DEPLOY_VALIDATION),
        );
    }
    if !validation_issues.is_empty() {
        metadata.insert(
            "deploy_validation_failure".to_string(),
            json!(validation_issues
                .iter()
                .take(4)
                .cloned()
                .collect::<Vec<_>>()
                .join("; ")),
        );
        metadata.insert(
            "deploy_validation_issues".to_string(),
            json!(validation_issues
                .iter()
                .take(8)
                .cloned()
                .collect::<Vec<_>>()),
        );
    }
    metadata
}

fn drone_stage_output(stage: &DronePipelineStageResult) -> String {
    [stage.stdout_preview.as_str(), stage.stderr_preview.as_str()]
        .into_iter()
        .filter(|value| !value.trim().is_empty())
        .collect::<Vec<_>>()
        .join("\n")
}

fn drone_docker_deploy_output_masks_failure(output: &str) -> bool {
    if [
        "|| echo",
        "container start skipped",
        "health check skipped",
        "image may not exist yet",
        "deployment skipped",
        "deploy skipped",
    ]
    .iter()
    .any(|marker| output.contains(marker))
    {
        return true;
    }
    output.lines().any(|line| {
        line.contains("|| true")
            && !line.contains("docker rm")
            && !line.contains("docker container rm")
            && [
                "docker pull",
                "docker run",
                "docker container run",
                "docker compose up",
                "docker-compose up",
                "docker stack deploy",
                "docker service create",
                "docker service update",
                "wget ",
                "curl ",
            ]
            .iter()
            .any(|marker| line.contains(marker))
    })
}

fn drone_docker_deploy_uses_forbidden_local_registry_pull(output: &str) -> bool {
    output.lines().any(|line| {
        (line.contains("docker pull")
            || line.contains("docker run")
            || line.contains("docker container run"))
            && (line.contains("host.docker.internal/")
                || line.contains("localhost:")
                || line.contains("127.0.0.1:")
                || line.contains("[::1]:"))
    })
}

fn drone_docker_deploy_has_run_marker(output: &str) -> bool {
    [
        "docker run",
        "docker container run",
        "docker compose up",
        "docker-compose up",
        "docker stack deploy",
        "docker service create",
        "docker service update",
    ]
    .iter()
    .any(|marker| output.contains(marker))
        || (output.contains("container id") && output.contains("names") && output.contains(" up "))
}

fn drone_missing_docker_deploy_required_services(
    output: &str,
    deploy: &DroneDeployConfig,
) -> Vec<String> {
    drone_docker_deploy_service_requirements(deploy)
        .into_iter()
        .filter(|markers| !markers.iter().any(|marker| output.contains(marker)))
        .map(|markers| {
            markers
                .first()
                .cloned()
                .unwrap_or_else(|| "unknown".to_string())
        })
        .collect()
}

fn drone_missing_docker_deploy_built_images(
    output: &str,
    deploy: &DroneDeployConfig,
    stages: &[DronePipelineStageResult],
) -> Vec<String> {
    drone_docker_build_service_requirements(stages, deploy)
        .into_iter()
        .filter(|markers| !markers.iter().any(|marker| output.contains(marker)))
        .map(|markers| {
            markers
                .first()
                .cloned()
                .unwrap_or_else(|| "unknown".to_string())
        })
        .collect()
}

fn drone_docker_deploy_service_requirements(deploy: &DroneDeployConfig) -> Vec<Vec<String>> {
    let raw = deploy
        .docker
        .get("deploy_services")
        .or_else(|| deploy.docker.get("services"));
    raw.and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(|item| {
                    let item = item.as_object()?;
                    if item.get("required").and_then(Value::as_bool) == Some(false) {
                        return None;
                    }
                    let mut markers = [
                        "container_name",
                        "image_deploy_local",
                        "image_host_docker",
                        "image",
                        "service_id",
                        "id",
                    ]
                    .iter()
                    .filter_map(|key| string_from_map(item, key))
                    .map(|value| value.to_ascii_lowercase())
                    .collect::<Vec<_>>();
                    dedup_strings(&mut markers);
                    if markers.is_empty() {
                        None
                    } else {
                        Some(markers)
                    }
                })
                .collect()
        })
        .unwrap_or_default()
}

fn drone_docker_build_service_requirements(
    stages: &[DronePipelineStageResult],
    deploy: &DroneDeployConfig,
) -> Vec<Vec<String>> {
    let mut requirements = Vec::new();
    for stage in stages {
        if stage
            .metadata
            .get("drone_step_kind")
            .and_then(Value::as_str)
            == Some("deploy")
            || drone_is_deploy_label(&stage.stage, deploy)
        {
            continue;
        }
        let output = drone_stage_output(stage).to_ascii_lowercase();
        if !output.contains("docker build") && !output.contains("docker buildx build") {
            continue;
        }
        let identity = format!(
            "{}\n{}\n{}\n{}",
            stage.stage,
            stage.command,
            stage
                .metadata
                .get("drone_stage")
                .and_then(Value::as_str)
                .unwrap_or(""),
            stage
                .metadata
                .get("drone_step")
                .and_then(Value::as_str)
                .unwrap_or("")
        )
        .to_ascii_lowercase();
        let mut markers = Vec::new();
        for part in identity.split(|ch: char| ch.is_whitespace() || ch == ':' || ch == '/') {
            if let Some(service) = drone_docker_build_service_name(part) {
                markers.push(service);
            }
        }
        for image in drone_docker_build_tag_images(&output) {
            markers.extend(drone_docker_image_marker_candidates(&image));
        }
        dedup_strings(&mut markers);
        if !markers.is_empty() && !requirements.contains(&markers) {
            requirements.push(markers);
        }
    }
    requirements
}

fn drone_docker_build_service_name(value: &str) -> Option<String> {
    let lower = value.to_ascii_lowercase();
    for separator in [
        "docker-build-",
        "docker_build_",
        "docker-build/",
        "docker_build/",
    ] {
        if let Some(rest) = lower.split(separator).nth(1) {
            let service = rest
                .chars()
                .take_while(|ch| ch.is_ascii_alphanumeric() || matches!(ch, '_' | '.' | '-'))
                .collect::<String>();
            if !service.is_empty() {
                return Some(service);
            }
        }
    }
    None
}

fn drone_docker_build_tag_images(output: &str) -> Vec<String> {
    output
        .split_whitespace()
        .collect::<Vec<_>>()
        .windows(2)
        .filter_map(|window| {
            if matches!(window[0], "-t" | "--tag") {
                Some(window[1].trim_matches(|ch| matches!(ch, '\'' | '"' | ',')))
            } else {
                None
            }
        })
        .filter(|image| drone_docker_image_ref_is_named_artifact(image))
        .map(ToOwned::to_owned)
        .collect()
}

fn drone_docker_image_ref_is_named_artifact(image: &str) -> bool {
    let normalized = image.trim_matches(|ch| matches!(ch, '\'' | '"' | ','));
    if normalized.is_empty() {
        return false;
    }
    let without_digest = normalized.split('@').next().unwrap_or(normalized);
    let basename = without_digest.rsplit('/').next().unwrap_or(without_digest);
    without_digest.contains('/')
        || basename.contains(':')
        || basename.contains('-')
        || basename.contains('_')
        || basename.contains('.')
}

fn drone_docker_image_marker_candidates(image: &str) -> Vec<String> {
    let normalized = image.trim_matches(|ch| matches!(ch, '\'' | '"' | ','));
    if normalized.is_empty() {
        return Vec::new();
    }
    let without_digest = normalized.split('@').next().unwrap_or(normalized);
    let mut path_parts = without_digest.split('/').collect::<Vec<_>>();
    if path_parts.len() > 1
        && path_parts.first().is_some_and(|value| {
            value.contains('.') || value.contains(':') || *value == "localhost"
        })
    {
        path_parts.remove(0);
    }
    let mut repository = path_parts.join("/");
    if let Some((before_tag, _)) = repository.rsplit_once(':') {
        repository = before_tag.to_string();
    }
    let basename = repository.rsplit('/').next().unwrap_or(&repository);
    let mut markers = vec![
        normalized.to_ascii_lowercase(),
        repository.to_ascii_lowercase(),
        basename.to_ascii_lowercase(),
    ];
    for separator in ['-', '_', '.'] {
        if let Some((_, suffix)) = basename.rsplit_once(separator) {
            markers.push(suffix.to_ascii_lowercase());
        }
    }
    dedup_strings(&mut markers);
    markers
}

fn combine_failure_preview(error_text: &str, log_text: &str) -> String {
    let mut parts = Vec::new();
    for text in [error_text, log_text] {
        let value = text.trim();
        if !value.is_empty() && !parts.contains(&value) {
            parts.push(value);
        }
    }
    compact_text(&parts.join("\n"), 4_000)
}

fn first_failed_drone_stage(
    stages: &[DronePipelineStageResult],
) -> Option<&DronePipelineStageResult> {
    stages.iter().find(|stage| stage.status == "failed")
}

fn source_publish_stage_metadata(failure: &DroneSourcePublishFailure) -> Map<String, Value> {
    let mut metadata = Map::new();
    metadata.insert("provider".to_string(), json!(DRONE_PROVIDER));
    metadata.insert("external_provider".to_string(), json!(DRONE_PROVIDER));
    metadata.extend(failure.metadata.clone());
    metadata
}

fn drone_source_publish_run_metadata(
    contract: &PipelineContractFoundation,
    failure: &DroneSourcePublishFailure,
    completed_at: DateTime<Utc>,
) -> Map<String, Value> {
    let mut metadata = Map::new();
    metadata.insert("stage_count".to_string(), json!(1));
    metadata.insert(
        "service_count".to_string(),
        json!(contract.services_json.as_array().map_or(0, Vec::len)),
    );
    metadata.insert("external_provider".to_string(), json!(DRONE_PROVIDER));
    metadata.insert("pipeline_failed_stage".to_string(), json!("source_publish"));
    metadata.insert(
        "pipeline_failure_summary".to_string(),
        json!(failure.reason),
    );
    metadata.insert("pipeline_last_summary".to_string(), json!(failure.reason));
    metadata.insert(
        "pipeline_finished_at".to_string(),
        json!(completed_at.to_rfc3339()),
    );
    metadata.extend(failure.metadata.clone());
    metadata
}

fn pipeline_contract_metadata(
    contract: &PipelineContractFoundation,
    source_publish_outcome: Option<&DroneSourcePublishOutcome>,
) -> Value {
    source_publish_outcome.map_or_else(
        || contract.metadata_json.clone(),
        |outcome| {
            let mut metadata = object_or_empty(contract.metadata_json.clone());
            metadata.extend(outcome.metadata().clone());
            Value::Object(metadata)
        },
    )
}

fn pipeline_run_metadata(
    reason: &str,
    source_publish_outcome: Option<&DroneSourcePublishOutcome>,
) -> Value {
    let mut metadata = Map::new();
    metadata.insert("reason".to_string(), json!(reason));
    if let Some(outcome) = source_publish_outcome {
        metadata.extend(outcome.metadata().clone());
    }
    Value::Object(metadata)
}

fn source_publish_source_commit_ref(
    source_publish_outcome: Option<&DroneSourcePublishOutcome>,
) -> Option<String> {
    source_publish_outcome.and_then(|outcome| {
        outcome
            .metadata()
            .get("source_publish_source_commit_ref")
            .and_then(Value::as_str)
            .and_then(commit_ref_token)
    })
}

fn merge_object_values(left: &Value, right: &Value) -> Value {
    let mut merged = object_or_empty(left.clone());
    merged.extend(object_or_empty(right.clone()));
    Value::Object(merged)
}

async fn prepare_drone_source_publish(
    contract: &mut PipelineContractFoundation,
    workspace: &WorkspaceRecord,
    node: &WorkspacePlanNodeRecord,
    attempt_id: Option<&str>,
) -> CoreResult<Option<DroneSourcePublishOutcome>> {
    if contract.provider != DRONE_PROVIDER {
        return Ok(None);
    }
    let provider_config = object_or_empty(contract.provider_config_json.clone());
    let workspace_metadata = object_or_empty(workspace.metadata_json.clone());
    let source_control = drone_source_control_config(&workspace_metadata, &provider_config);
    let branch = drone_source_branch(&source_control, &provider_config);
    let token_env = source_control_token_env(&source_control);

    if attempt_id.is_none() {
        let metadata = source_publish_metadata(
            "skipped",
            Some("missing attempt_id; using remote branch head"),
            pipeline_contract_commit_ref(&provider_config).as_deref(),
            branch.as_deref(),
            None,
            token_env.as_deref(),
        );
        if let Some(branch) = branch.as_deref() {
            if string_from_map(&provider_config, "branch").is_none() {
                let mut patched = provider_config.clone();
                patched.insert("branch".to_string(), json!(branch));
                apply_drone_provider_config(contract, patched);
            }
        }
        return Ok(Some(DroneSourcePublishOutcome::Skipped(
            DroneSourcePublishSkipped { metadata },
        )));
    }

    let Some(commit_ref) = node_expected_commit_ref(node) else {
        let mut metadata = Map::new();
        metadata.insert("source_publish_status".to_string(), json!("skipped"));
        metadata.insert(
            "source_publish_reason".to_string(),
            json!("missing commit_ref"),
        );
        return Ok(Some(DroneSourcePublishOutcome::Skipped(
            DroneSourcePublishSkipped { metadata },
        )));
    };

    let Some(host_code_root) = host_code_root_from_workspace(&workspace.metadata_json) else {
        let reason = "host_code_root is not available for Drone source publish".to_string();
        return Ok(Some(DroneSourcePublishOutcome::Failed(
            DroneSourcePublishFailure {
                metadata: source_publish_metadata(
                    "failed",
                    Some(&reason),
                    Some(&commit_ref),
                    None,
                    Some(&commit_ref),
                    None,
                ),
                reason,
            },
        )));
    };

    let Some(branch) = branch else {
        let reason =
            "source_control.default_branch or delivery_cicd.drone.branch is required".to_string();
        return Ok(Some(DroneSourcePublishOutcome::Failed(
            DroneSourcePublishFailure {
                metadata: source_publish_metadata(
                    "failed",
                    Some(&reason),
                    Some(&commit_ref),
                    None,
                    Some(&commit_ref),
                    None,
                ),
                reason,
            },
        )));
    };

    let remote_url = source_control_remote_url(&source_control);
    let token = source_control_token(token_env.as_deref());
    let publish = publish_git_ref_to_source_control(
        Path::new(&host_code_root),
        &commit_ref,
        &branch,
        remote_url.as_deref(),
        token_env.as_deref(),
        token.as_deref(),
    )
    .await?;
    let metadata = source_publish_metadata(
        &publish.status,
        publish.reason.as_deref(),
        publish.published_commit.as_deref().or(Some(&commit_ref)),
        Some(&branch),
        Some(&commit_ref),
        token_env.as_deref(),
    );
    if publish.status != "published" {
        let reason = publish
            .reason
            .clone()
            .unwrap_or_else(|| "source publish failed".to_string());
        return Ok(Some(DroneSourcePublishOutcome::Failed(
            DroneSourcePublishFailure { reason, metadata },
        )));
    }

    let published_commit = publish
        .published_commit
        .clone()
        .unwrap_or_else(|| commit_ref.clone());
    let mut patched = provider_config.clone();
    patched.insert("branch".to_string(), json!(branch));
    patched.insert("commit".to_string(), json!(published_commit));
    let mut publish_config = Map::new();
    publish_config.insert("status".to_string(), json!("published"));
    publish_config.insert(
        "branch".to_string(),
        metadata
            .get("source_publish_branch")
            .cloned()
            .unwrap_or(Value::Null),
    );
    publish_config.insert(
        "commit".to_string(),
        metadata
            .get("source_publish_commit_ref")
            .cloned()
            .unwrap_or(Value::Null),
    );
    publish_config.insert(
        "source_commit_ref".to_string(),
        metadata
            .get("source_publish_source_commit_ref")
            .cloned()
            .unwrap_or(Value::Null),
    );
    if let Some(token_env) = metadata.get("source_publish_token_env") {
        publish_config.insert("token_env".to_string(), token_env.clone());
    }
    patched.insert("source_publish".to_string(), Value::Object(publish_config));
    apply_drone_provider_config(contract, patched);

    Ok(Some(DroneSourcePublishOutcome::Published(
        DroneSourcePublishSuccess { metadata },
    )))
}

fn source_publish_metadata(
    status: &str,
    reason: Option<&str>,
    commit_ref: Option<&str>,
    branch: Option<&str>,
    source_commit_ref: Option<&str>,
    token_env: Option<&str>,
) -> Map<String, Value> {
    let mut metadata = Map::new();
    metadata.insert("source_publish_status".to_string(), json!(status));
    metadata.insert("source_publish_provider".to_string(), json!("git"));
    if let Some(reason) = reason {
        metadata.insert("source_publish_reason".to_string(), json!(reason));
    }
    if let Some(commit_ref) = commit_ref {
        metadata.insert("source_publish_commit_ref".to_string(), json!(commit_ref));
    }
    if let Some(branch) = branch {
        metadata.insert("source_publish_branch".to_string(), json!(branch));
    }
    if let Some(source_commit_ref) = source_commit_ref {
        metadata.insert(
            "source_publish_source_commit_ref".to_string(),
            json!(source_commit_ref),
        );
    }
    if let Some(token_env) = token_env {
        metadata.insert("source_publish_token_env".to_string(), json!(token_env));
    }
    metadata
}

fn drone_source_control_config(
    workspace_metadata: &Map<String, Value>,
    provider_config: &Map<String, Value>,
) -> Map<String, Value> {
    let mut source_control = Map::new();
    if let Some(config) = provider_config
        .get("source_control")
        .and_then(Value::as_object)
    {
        source_control.extend(config.clone());
    }
    if let Some(config) = workspace_metadata
        .get("source_control")
        .and_then(Value::as_object)
    {
        source_control.extend(config.clone());
    }
    if !source_control.contains_key("repo") {
        if let Some(value) = provider_config
            .get("repo")
            .or_else(|| provider_config.get("repository"))
            .filter(|value| value.is_string())
        {
            source_control.insert("repo".to_string(), value.clone());
        }
    }
    if !source_control.contains_key("default_branch") {
        if let Some(value) = provider_config
            .get("branch")
            .filter(|value| value.is_string())
        {
            source_control.insert("default_branch".to_string(), value.clone());
        }
    }
    source_control
}

fn drone_source_branch(
    source_control: &Map<String, Value>,
    provider_config: &Map<String, Value>,
) -> Option<String> {
    string_from_map(provider_config, "branch")
        .or_else(|| string_from_map(source_control, "default_branch"))
        .filter(|branch| is_safe_git_branch(branch))
}

fn host_code_root_from_workspace(workspace_metadata: &Value) -> Option<String> {
    metadata_string_from_path(workspace_metadata, &["host_code_root"]).or_else(|| {
        metadata_string_from_path(workspace_metadata, &["code_context", "host_code_root"])
    })
}

fn is_safe_git_branch(value: &str) -> bool {
    let value = value.trim();
    if value.is_empty()
        || value.starts_with('-')
        || value.starts_with('/')
        || value.ends_with('/')
        || value.contains("..")
        || value.contains("//")
        || value.contains("@{")
        || value.contains('\\')
    {
        return false;
    }
    value
        .chars()
        .all(|ch| ch.is_ascii_alphanumeric() || matches!(ch, '.' | '_' | '/' | '-'))
}

fn pipeline_contract_commit_ref(provider_config: &Map<String, Value>) -> Option<String> {
    string_from_map(provider_config, "commit").and_then(|value| commit_ref_token(&value))
}

fn source_control_remote_url(source_control: &Map<String, Value>) -> Option<String> {
    if let Some(remote_url) = string_from_map(source_control, "clone_url") {
        return Some(remote_url);
    }
    let repo = string_from_map(source_control, "repo")?;
    let provider = string_from_map(source_control, "provider")
        .unwrap_or_else(|| "github".to_string())
        .to_ascii_lowercase();
    let server_url = string_from_map(source_control, "server_url");
    let base_url = if provider == "gitlab" {
        server_url.unwrap_or_else(|| "https://gitlab.com".to_string())
    } else {
        server_url.unwrap_or_else(|| "https://github.com".to_string())
    };
    let suffix = if repo.ends_with(".git") { "" } else { ".git" };
    Some(format!("{}/{repo}{suffix}", base_url.trim_end_matches('/')))
}

fn source_control_token_env(source_control: &Map<String, Value>) -> Option<String> {
    if let Some(configured) = string_from_map(source_control, "auth_token_env") {
        return Some(configured);
    }
    let provider = string_from_map(source_control, "provider")
        .unwrap_or_else(|| "github".to_string())
        .to_ascii_lowercase();
    Some(if provider == "gitlab" {
        "GITLAB_TOKEN".to_string()
    } else {
        "GITHUB_TOKEN".to_string()
    })
}

fn source_control_token(token_env: Option<&str>) -> Option<String> {
    let token_env = token_env?;
    std::env::var(token_env)
        .ok()
        .and_then(|value| metadata_string(Some(&Value::String(value))))
        .or_else(|| source_publish_dotenv_value(token_env))
}

fn source_publish_dotenv_value(token_env: &str) -> Option<String> {
    let path = std::env::var("MEMSTACK_DRONE_DOTENV_PATH").unwrap_or_else(|_| ".env".to_string());
    let content = std::fs::read_to_string(path).ok()?;
    for line in content.lines() {
        let trimmed = line.trim();
        if trimmed.is_empty() || trimmed.starts_with('#') {
            continue;
        }
        let Some((key, value)) = trimmed.split_once('=') else {
            continue;
        };
        if key.trim() == token_env {
            let value = value.trim().trim_matches('"').trim_matches('\'');
            if !value.is_empty() {
                return Some(value.to_string());
            }
        }
    }
    None
}

fn apply_drone_provider_config(
    contract: &mut PipelineContractFoundation,
    provider_config: Map<String, Value>,
) {
    contract.provider_config_json = Value::Object(provider_config.clone());
    let mut metadata = object_or_empty(contract.metadata_json.clone());
    metadata.insert(
        "provider_config".to_string(),
        Value::Object(provider_config),
    );
    contract.metadata_json = Value::Object(metadata);
}

async fn publish_git_ref_to_source_control(
    host_code_root: &Path,
    commit_ref: &str,
    branch: &str,
    remote_url: Option<&str>,
    token_env: Option<&str>,
    token: Option<&str>,
) -> CoreResult<GitPublishResult> {
    if !host_code_root.exists() {
        return Ok(GitPublishResult {
            status: "failed".to_string(),
            reason: Some(format!(
                "host_code_root does not exist: {}",
                host_code_root.display()
            )),
            published_commit: None,
        });
    }
    if !is_safe_git_branch(branch) {
        return Ok(GitPublishResult {
            status: "failed".to_string(),
            reason: Some("unsafe git branch name".to_string()),
            published_commit: None,
        });
    }

    let mut env = vec![("GIT_TERMINAL_PROMPT".to_string(), "0".to_string())];
    let askpass_path = if let Some(token) = token {
        let path = create_git_askpass_script()?;
        env.push((
            "GIT_ASKPASS".to_string(),
            path.to_string_lossy().to_string(),
        ));
        env.push(("GIT_TOKEN".to_string(), token.to_string()));
        env.push((
            "GIT_USERNAME".to_string(),
            if token_env == Some("GITLAB_TOKEN") {
                "oauth2".to_string()
            } else {
                "x-access-token".to_string()
            },
        ));
        Some(path)
    } else {
        None
    };

    let result = publish_git_ref_to_source_control_with_env(
        host_code_root,
        commit_ref,
        branch,
        remote_url,
        &env,
    )
    .await;
    if let Some(path) = askpass_path {
        let _ = std::fs::remove_file(path);
    }
    result
}

async fn publish_git_ref_to_source_control_with_env(
    host_code_root: &Path,
    commit_ref: &str,
    branch: &str,
    remote_url: Option<&str>,
    env: &[(String, String)],
) -> CoreResult<GitPublishResult> {
    let exists = run_git_command(
        host_code_root,
        &["cat-file", "-e", &format!("{commit_ref}^{{commit}}")],
        env,
        60,
    )
    .await?;
    if exists.exit_code != 0 {
        return Ok(GitPublishResult {
            status: "failed".to_string(),
            reason: Some(compact_git_error(&exists)),
            published_commit: None,
        });
    }

    let dirty = run_git_command(host_code_root, &["status", "--porcelain"], env, 60).await?;
    if !dirty.stdout.trim().is_empty() {
        return publish_git_ref_from_temporary_worktree(
            host_code_root,
            commit_ref,
            branch,
            remote_url,
            env,
            "published from temporary worktree because main checkout has uncommitted changes",
        )
        .await;
    }

    let already_ancestor = run_git_command(
        host_code_root,
        &["merge-base", "--is-ancestor", commit_ref, "HEAD"],
        env,
        60,
    )
    .await?;
    if already_ancestor.exit_code != 0 {
        let fast_forward = run_git_command(
            host_code_root,
            &["merge", "--ff-only", commit_ref],
            env,
            120,
        )
        .await?;
        if fast_forward.exit_code != 0 {
            if is_non_fast_forward_push_rejection(&fast_forward)
                || is_unrelated_history_merge_rejection(&fast_forward)
            {
                return publish_git_ref_from_temporary_worktree(
                    host_code_root,
                    commit_ref,
                    branch,
                    remote_url,
                    env,
                    "published from temporary worktree after local branch could not fast-forward to candidate",
                )
                .await;
            }
            return Ok(GitPublishResult {
                status: "failed".to_string(),
                reason: Some(compact_git_error(&fast_forward)),
                published_commit: None,
            });
        }
    }

    let head = run_git_command(host_code_root, &["rev-parse", "HEAD"], env, 60).await?;
    if head.exit_code != 0 {
        return Ok(GitPublishResult {
            status: "failed".to_string(),
            reason: Some(compact_git_error(&head)),
            published_commit: None,
        });
    }
    let published_commit = head.stdout.trim().to_string();
    push_git_head_to_source_branch(host_code_root, &published_commit, branch, remote_url, env).await
}

async fn push_git_head_to_source_branch(
    host_code_root: &Path,
    published_commit: &str,
    branch: &str,
    remote_url: Option<&str>,
    env: &[(String, String)],
) -> CoreResult<GitPublishResult> {
    let remote = remote_url.unwrap_or("origin");
    let refspec = format!("HEAD:refs/heads/{branch}");
    let push = run_git_command(host_code_root, &["push", remote, &refspec], env, 180).await?;
    if push.exit_code == 0 {
        return Ok(GitPublishResult {
            status: "published".to_string(),
            reason: None,
            published_commit: Some(published_commit.to_string()),
        });
    }
    if is_non_fast_forward_push_rejection(&push) {
        return publish_git_ref_from_temporary_worktree(
            host_code_root,
            published_commit,
            branch,
            remote_url,
            env,
            "published from temporary worktree after remote branch advanced",
        )
        .await;
    }
    Ok(GitPublishResult {
        status: "failed".to_string(),
        reason: Some(compact_git_error(&push)),
        published_commit: Some(published_commit.to_string()),
    })
}

async fn publish_git_ref_from_temporary_worktree(
    host_code_root: &Path,
    publish_ref: &str,
    branch: &str,
    remote_url: Option<&str>,
    env: &[(String, String)],
    default_reason: &str,
) -> CoreResult<GitPublishResult> {
    let temp_parent =
        std::env::temp_dir().join(format!("memstack-source-publish-{}", generate_uuid_v4()));
    let worktree_path = temp_parent.join("worktree");
    std::fs::create_dir_all(&temp_parent).map_err(|err| {
        CoreError::Storage(format!(
            "failed to create source publish temp dir {}: {err}",
            temp_parent.display()
        ))
    })?;
    let mut added = false;
    let result = async {
        let worktree_path_string = worktree_path.to_string_lossy().to_string();
        let add = run_git_command(
            host_code_root,
            &[
                "worktree",
                "add",
                "--detach",
                &worktree_path_string,
                publish_ref,
            ],
            env,
            120,
        )
        .await?;
        if add.exit_code != 0 {
            return Ok(GitPublishResult {
                status: "failed".to_string(),
                reason: Some(compact_git_error(&add)),
                published_commit: None,
            });
        }
        added = true;
        let remote = remote_url.unwrap_or("origin");
        let remote_merge =
            merge_remote_branch_for_publish(&worktree_path, publish_ref, remote, branch, env)
                .await?;
        if remote_merge.status == "failed" {
            return Ok(GitPublishResult {
                status: "failed".to_string(),
                reason: Some(
                    remote_merge
                        .reason
                        .unwrap_or_else(|| "remote branch merge failed".to_string()),
                ),
                published_commit: None,
            });
        }
        let head = run_git_command(&worktree_path, &["rev-parse", "HEAD"], env, 60).await?;
        if head.exit_code != 0 {
            return Ok(GitPublishResult {
                status: "failed".to_string(),
                reason: Some(compact_git_error(&head)),
                published_commit: None,
            });
        }
        let published_commit = head.stdout.trim().to_string();
        let refspec = format!("HEAD:refs/heads/{branch}");
        let push = run_git_command(&worktree_path, &["push", remote, &refspec], env, 180).await?;
        if push.exit_code != 0 {
            if is_non_fast_forward_push_rejection(&push) {
                if let Some(retried) = retry_temporary_worktree_push_after_non_fast_forward(
                    &worktree_path,
                    &published_commit,
                    remote,
                    branch,
                    env,
                    default_reason,
                )
                .await?
                {
                    return Ok(retried);
                }
            }
            return Ok(GitPublishResult {
                status: "failed".to_string(),
                reason: Some(compact_git_error(&push)),
                published_commit: Some(published_commit),
            });
        }
        Ok(GitPublishResult {
            status: "published".to_string(),
            reason: Some(
                remote_merge
                    .reason
                    .unwrap_or_else(|| default_reason.to_string()),
            ),
            published_commit: Some(published_commit),
        })
    }
    .await;

    if added {
        let worktree_path_string = worktree_path.to_string_lossy().to_string();
        let _ = run_git_command(
            host_code_root,
            &["worktree", "remove", "--force", &worktree_path_string],
            env,
            120,
        )
        .await;
    }
    let _ = std::fs::remove_dir_all(&temp_parent);
    result
}

async fn retry_temporary_worktree_push_after_non_fast_forward(
    worktree_path: &Path,
    candidate_ref: &str,
    remote: &str,
    branch: &str,
    env: &[(String, String)],
    default_reason: &str,
) -> CoreResult<Option<GitPublishResult>> {
    let retry_merge =
        merge_remote_branch_for_publish(worktree_path, candidate_ref, remote, branch, env).await?;
    if retry_merge.status == "failed" {
        return Ok(Some(GitPublishResult {
            status: "failed".to_string(),
            reason: Some(
                retry_merge.reason.unwrap_or_else(|| {
                    "remote branch merge failed after push rejection".to_string()
                }),
            ),
            published_commit: Some(candidate_ref.to_string()),
        }));
    }
    let retry_head = run_git_command(worktree_path, &["rev-parse", "HEAD"], env, 60).await?;
    if retry_head.exit_code != 0 {
        return Ok(Some(GitPublishResult {
            status: "failed".to_string(),
            reason: Some(compact_git_error(&retry_head)),
            published_commit: Some(candidate_ref.to_string()),
        }));
    }
    let retried_commit = retry_head.stdout.trim().to_string();
    let refspec = format!("HEAD:refs/heads/{branch}");
    let retry_push = run_git_command(worktree_path, &["push", remote, &refspec], env, 180).await?;
    if retry_push.exit_code == 0 {
        let retry_reason = retry_merge
            .reason
            .unwrap_or_else(|| default_reason.to_string());
        return Ok(Some(GitPublishResult {
            status: "published".to_string(),
            reason: Some(format!(
                "{retry_reason}; retried after non-fast-forward push"
            )),
            published_commit: Some(retried_commit),
        }));
    }
    Ok(None)
}

async fn merge_remote_branch_for_publish(
    worktree_path: &Path,
    candidate_ref: &str,
    remote: &str,
    branch: &str,
    env: &[(String, String)],
) -> CoreResult<GitRemoteMergeResult> {
    let remote_ref = format!("refs/remotes/memstack-source-publish/{branch}");
    let fetch_refspec = format!("+refs/heads/{branch}:{remote_ref}");
    let fetch = run_git_command(
        worktree_path,
        &["fetch", "--no-tags", remote, &fetch_refspec],
        env,
        180,
    )
    .await?;
    if fetch.exit_code != 0 {
        let reason = compact_git_error(&fetch);
        let normalized = reason.to_ascii_lowercase();
        if normalized.contains("couldn't find remote ref")
            || normalized.contains("could not find remote ref")
        {
            return Ok(GitRemoteMergeResult {
                status: "skipped".to_string(),
                reason: None,
            });
        }
        return Ok(GitRemoteMergeResult {
            status: "failed".to_string(),
            reason: Some(reason),
        });
    }

    let remote_ancestor = run_git_command(
        worktree_path,
        &["merge-base", "--is-ancestor", &remote_ref, "HEAD"],
        env,
        60,
    )
    .await?;
    if remote_ancestor.exit_code == 0 {
        return Ok(GitRemoteMergeResult {
            status: "skipped".to_string(),
            reason: None,
        });
    }

    let local_ancestor = run_git_command(
        worktree_path,
        &["merge-base", "--is-ancestor", "HEAD", &remote_ref],
        env,
        60,
    )
    .await?;
    if local_ancestor.exit_code == 0 {
        return merge_remote_branch_preserving_local_tree(worktree_path, &remote_ref, env).await;
    }

    let merge = run_git_command(
        worktree_path,
        &["merge", "--no-edit", &remote_ref],
        env,
        120,
    )
    .await?;
    if merge.exit_code == 0 {
        return restore_candidate_publish_paths_after_merge(
            worktree_path,
            candidate_ref,
            &remote_ref,
            env,
            "merged remote branch before publish",
        )
        .await;
    }

    let _ = run_git_command(worktree_path, &["merge", "--abort"], env, 60).await;
    let merged = merge_remote_branch_with_local_preference(worktree_path, &remote_ref, env).await?;
    if merged.status == "failed" {
        return Ok(merged);
    }
    let reason = merged
        .reason
        .clone()
        .unwrap_or_else(|| "merged remote branch before publish".to_string());
    restore_candidate_publish_paths_after_merge(
        worktree_path,
        candidate_ref,
        &remote_ref,
        env,
        &reason,
    )
    .await
}

async fn merge_remote_branch_preserving_local_tree(
    worktree_path: &Path,
    remote_ref: &str,
    env: &[(String, String)],
) -> CoreResult<GitRemoteMergeResult> {
    let merge_ours_strategy = run_git_command(
        worktree_path,
        &["merge", "--no-edit", "-s", "ours", remote_ref],
        env,
        120,
    )
    .await?;
    if merge_ours_strategy.exit_code == 0 {
        return Ok(GitRemoteMergeResult {
            status: "merged".to_string(),
            reason: Some(
                "merged remote branch history before publish preserving candidate tree".to_string(),
            ),
        });
    }
    Ok(GitRemoteMergeResult {
        status: "failed".to_string(),
        reason: Some(compact_git_error(&merge_ours_strategy)),
    })
}

async fn restore_candidate_publish_paths_after_merge(
    worktree_path: &Path,
    candidate_ref: &str,
    remote_ref: &str,
    env: &[(String, String)],
    reason: &str,
) -> CoreResult<GitRemoteMergeResult> {
    let paths =
        candidate_publish_restore_path_states(worktree_path, candidate_ref, remote_ref, env)
            .await?;
    if paths.is_empty() {
        return Ok(GitRemoteMergeResult {
            status: "merged".to_string(),
            reason: Some(reason.to_string()),
        });
    }

    let present_paths: Vec<String> = paths
        .iter()
        .filter_map(|(path, present)| present.then_some(path.clone()))
        .collect();
    let removed_paths: Vec<String> = paths
        .iter()
        .filter_map(|(path, present)| (!present).then_some(path.clone()))
        .collect();
    if !present_paths.is_empty() {
        let mut args = vec![
            "checkout".to_string(),
            candidate_ref.to_string(),
            "--".to_string(),
        ];
        args.extend(present_paths);
        let checkout = run_git_command_owned(worktree_path, args, env, 120).await?;
        if checkout.exit_code != 0 {
            return Ok(GitRemoteMergeResult {
                status: "failed".to_string(),
                reason: Some(compact_git_error(&checkout)),
            });
        }
    }
    if !removed_paths.is_empty() {
        let mut args = vec![
            "rm".to_string(),
            "-f".to_string(),
            "--ignore-unmatch".to_string(),
            "--".to_string(),
        ];
        args.extend(removed_paths);
        let remove = run_git_command_owned(worktree_path, args, env, 120).await?;
        if remove.exit_code != 0 {
            return Ok(GitRemoteMergeResult {
                status: "failed".to_string(),
                reason: Some(compact_git_error(&remove)),
            });
        }
    }

    let mut diff_args = vec![
        "diff".to_string(),
        "--cached".to_string(),
        "--quiet".to_string(),
        "--".to_string(),
    ];
    diff_args.extend(paths.iter().map(|(path, _)| path.clone()));
    let changed = run_git_command_owned(worktree_path, diff_args, env, 60).await?;
    if changed.exit_code == 0 {
        return Ok(GitRemoteMergeResult {
            status: "merged".to_string(),
            reason: Some(reason.to_string()),
        });
    }
    if changed.exit_code != 1 {
        return Ok(GitRemoteMergeResult {
            status: "failed".to_string(),
            reason: Some(compact_git_error(&changed)),
        });
    }

    let commit = run_git_command(
        worktree_path,
        &["commit", "-m", "Preserve candidate source publish paths"],
        env,
        120,
    )
    .await?;
    if commit.exit_code != 0 {
        return Ok(GitRemoteMergeResult {
            status: "failed".to_string(),
            reason: Some(compact_git_error(&commit)),
        });
    }
    Ok(GitRemoteMergeResult {
        status: "merged".to_string(),
        reason: Some(format!(
            "{reason}; restored candidate tree paths after merge"
        )),
    })
}

async fn candidate_publish_restore_path_states(
    worktree_path: &Path,
    candidate_ref: &str,
    remote_ref: &str,
    env: &[(String, String)],
) -> CoreResult<Vec<(String, bool)>> {
    candidate_publish_path_states(worktree_path, candidate_ref, remote_ref, env).await
}

async fn candidate_publish_path_states(
    worktree_path: &Path,
    candidate_ref: &str,
    remote_ref: &str,
    env: &[(String, String)],
) -> CoreResult<Vec<(String, bool)>> {
    let base = run_git_command(
        worktree_path,
        &["merge-base", candidate_ref, remote_ref],
        env,
        60,
    )
    .await?;
    if base.exit_code != 0 {
        return Ok(Vec::new());
    }
    let base_ref = base.stdout.trim().to_string();
    if base_ref.is_empty() {
        return Ok(Vec::new());
    }
    let diff = run_git_command(
        worktree_path,
        &["diff", "--name-status", "-z", &base_ref, candidate_ref],
        env,
        60,
    )
    .await?;
    if diff.exit_code != 0 {
        return Ok(Vec::new());
    }
    Ok(parse_git_name_status_path_states(&diff.stdout))
}

fn parse_git_name_status_path_states(raw: &str) -> Vec<(String, bool)> {
    let parts: Vec<&str> = raw.split('\0').filter(|part| !part.is_empty()).collect();
    let mut paths = Vec::new();
    let mut index = 0usize;
    while index < parts.len() {
        let status = parts[index];
        index += 1;
        let Some(code) = status.chars().next() else {
            continue;
        };
        if matches!(code, 'R' | 'C') {
            if index + 1 >= parts.len() {
                break;
            }
            let old_path = parts[index];
            let new_path = parts[index + 1];
            index += 2;
            if code == 'R' && !old_path.is_empty() {
                set_path_state(&mut paths, old_path.to_string(), false);
            }
            if !new_path.is_empty() {
                set_path_state(&mut paths, new_path.to_string(), true);
            }
            continue;
        }
        if index >= parts.len() {
            break;
        }
        let path = parts[index];
        index += 1;
        if !path.is_empty() {
            set_path_state(&mut paths, path.to_string(), code != 'D');
        }
    }
    paths
}

fn set_path_state(paths: &mut Vec<(String, bool)>, path: String, present: bool) {
    if let Some((_, existing_present)) = paths
        .iter_mut()
        .find(|(existing_path, _)| existing_path == &path)
    {
        *existing_present = present;
    } else {
        paths.push((path, present));
    }
}

async fn merge_remote_branch_with_local_preference(
    worktree_path: &Path,
    remote_ref: &str,
    env: &[(String, String)],
) -> CoreResult<GitRemoteMergeResult> {
    let merge_ours = run_git_command(
        worktree_path,
        &["merge", "--no-edit", "-X", "ours", remote_ref],
        env,
        120,
    )
    .await?;
    if merge_ours.exit_code == 0 {
        return Ok(GitRemoteMergeResult {
            status: "merged".to_string(),
            reason: Some(
                "merged remote branch before publish using local conflict preference".to_string(),
            ),
        });
    }
    if is_unrelated_history_merge_rejection(&merge_ours) {
        let _ = run_git_command(worktree_path, &["merge", "--abort"], env, 60).await;
        let merge_unrelated_ours = run_git_command(
            worktree_path,
            &[
                "merge",
                "--no-edit",
                "--allow-unrelated-histories",
                "-X",
                "ours",
                remote_ref,
            ],
            env,
            120,
        )
        .await?;
        if merge_unrelated_ours.exit_code == 0 {
            return Ok(GitRemoteMergeResult {
                status: "merged".to_string(),
                reason: Some(
                    "merged unrelated remote branch before publish using local conflict preference"
                        .to_string(),
                ),
            });
        }
        return Ok(GitRemoteMergeResult {
            status: "failed".to_string(),
            reason: Some(compact_git_error(&merge_unrelated_ours)),
        });
    }
    Ok(GitRemoteMergeResult {
        status: "failed".to_string(),
        reason: Some(compact_git_error(&merge_ours)),
    })
}

async fn run_git_command_owned(
    cwd: &Path,
    args: Vec<String>,
    env: &[(String, String)],
    timeout_seconds: u64,
) -> CoreResult<GitCommandOutput> {
    let arg_refs: Vec<&str> = args.iter().map(String::as_str).collect();
    run_git_command(cwd, &arg_refs, env, timeout_seconds).await
}

pub(super) async fn run_git_command(
    cwd: &Path,
    args: &[&str],
    env: &[(String, String)],
    timeout_seconds: u64,
) -> CoreResult<GitCommandOutput> {
    let mut command = tokio::process::Command::new("git");
    command
        .args(args)
        .current_dir(cwd)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    for (key, value) in env {
        command.env(key, value);
    }
    let output = tokio::time::timeout(Duration::from_secs(timeout_seconds), command.output())
        .await
        .map_err(|_| {
            CoreError::Storage(format!(
                "git {} timed out after {timeout_seconds}s",
                args.join(" ")
            ))
        })?
        .map_err(|err| {
            CoreError::Storage(format!("git {} failed to start: {err}", args.join(" ")))
        })?;
    Ok(GitCommandOutput {
        exit_code: output.status.code().unwrap_or(1),
        stdout: String::from_utf8_lossy(&output.stdout).into_owned(),
        stderr: String::from_utf8_lossy(&output.stderr).into_owned(),
    })
}

async fn run_git_command_with_stdin(
    cwd: &Path,
    args: &[&str],
    env: &[(String, String)],
    timeout_seconds: u64,
    stdin_text: &str,
) -> CoreResult<GitCommandOutput> {
    let mut command = tokio::process::Command::new("git");
    command
        .args(args)
        .current_dir(cwd)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    for (key, value) in env {
        command.env(key, value);
    }
    let mut child = command.spawn().map_err(|err| {
        CoreError::Storage(format!("git {} failed to start: {err}", args.join(" ")))
    })?;
    if let Some(mut stdin) = child.stdin.take() {
        stdin
            .write_all(stdin_text.as_bytes())
            .await
            .map_err(|err| {
                CoreError::Storage(format!("git {} stdin failed: {err}", args.join(" ")))
            })?;
    }
    let output = tokio::time::timeout(
        Duration::from_secs(timeout_seconds),
        child.wait_with_output(),
    )
    .await
    .map_err(|_| {
        CoreError::Storage(format!(
            "git {} timed out after {timeout_seconds}s",
            args.join(" ")
        ))
    })?
    .map_err(|err| CoreError::Storage(format!("git {} failed: {err}", args.join(" "))))?;
    Ok(GitCommandOutput {
        exit_code: output.status.code().unwrap_or(1),
        stdout: String::from_utf8_lossy(&output.stdout).into_owned(),
        stderr: String::from_utf8_lossy(&output.stderr).into_owned(),
    })
}

pub(super) async fn integrate_accepted_attempt_worktree_with_git(
    sandbox_code_root: &Path,
    worktree_path: &Path,
    commit_ref: &str,
) -> CoreResult<AcceptedWorktreeIntegrationResult> {
    let env = vec![("GIT_TERMINAL_PROMPT".to_string(), "0".to_string())];
    if !sandbox_code_root.exists() {
        return Ok(AcceptedWorktreeIntegrationResult {
            status: "failed".to_string(),
            summary: format!(
                "sandbox_code_root does not exist: {}",
                sandbox_code_root.display()
            ),
            commit_ref: commit_ref.to_string(),
            dirty_signature: None,
        });
    }
    if !worktree_path.exists() {
        return Ok(AcceptedWorktreeIntegrationResult {
            status: "failed".to_string(),
            summary: format!(
                "accepted worktree does not exist: {}",
                worktree_path.display()
            ),
            commit_ref: commit_ref.to_string(),
            dirty_signature: None,
        });
    }

    let resolved_commit = resolve_accepted_worktree_commit(worktree_path, commit_ref, &env).await?;
    let Some(resolved_commit) = resolved_commit else {
        return Ok(AcceptedWorktreeIntegrationResult {
            status: "failed".to_string(),
            summary: "status=failed\nreason=commit_ref not found in attempt worktree".to_string(),
            commit_ref: commit_ref.to_string(),
            dirty_signature: None,
        });
    };

    let already_merged = run_git_command(
        sandbox_code_root,
        &["merge-base", "--is-ancestor", &resolved_commit, "HEAD"],
        &env,
        60,
    )
    .await?;
    if already_merged.exit_code == 0 {
        let git_head = short_git_head(sandbox_code_root, &env).await?;
        return Ok(AcceptedWorktreeIntegrationResult {
            status: "already_merged".to_string(),
            summary: format!(
                "resolved_commit_ref={resolved_commit}\nstatus=already_merged\ngit_head={git_head}"
            ),
            commit_ref: resolved_commit,
            dirty_signature: None,
        });
    }

    let dirty = run_git_command(sandbox_code_root, &["status", "--porcelain"], &env, 60).await?;
    if dirty.exit_code != 0 {
        return Ok(AcceptedWorktreeIntegrationResult {
            status: "failed".to_string(),
            summary: compact_git_error(&dirty),
            commit_ref: resolved_commit,
            dirty_signature: None,
        });
    }
    if !dirty.stdout.trim().is_empty() {
        let signature = git_blob_hash(sandbox_code_root, &dirty.stdout, &env).await?;
        return Ok(AcceptedWorktreeIntegrationResult {
            status: "blocked_dirty_main".to_string(),
            summary: compact_text(
                &format!(
                    "status=blocked_dirty_main\nreason=sandbox_code_root has uncommitted changes\ndirty_signature={}\n{}",
                    signature,
                    dirty.stdout.trim()
                ),
                1200,
            ),
            commit_ref: resolved_commit,
            dirty_signature: Some(signature),
        });
    }

    let merge = run_git_command(
        sandbox_code_root,
        &["merge", "--no-edit", &resolved_commit],
        &env,
        120,
    )
    .await?;
    let merge = if merge.exit_code != 0 && is_unrelated_history_merge_rejection(&merge) {
        let _ = run_git_command(sandbox_code_root, &["merge", "--abort"], &env, 60).await;
        run_git_command(
            sandbox_code_root,
            &[
                "merge",
                "--no-edit",
                "--allow-unrelated-histories",
                "-X",
                "theirs",
                &resolved_commit,
            ],
            &env,
            120,
        )
        .await?
    } else {
        merge
    };
    if merge.exit_code != 0 {
        let summary = compact_text(
            &format!(
                "{}\nstatus=failed\nreason=merge_failed_aborted",
                compact_git_error(&merge)
            ),
            1200,
        );
        let _ = run_git_command(sandbox_code_root, &["merge", "--abort"], &env, 60).await;
        return Ok(AcceptedWorktreeIntegrationResult {
            status: "failed".to_string(),
            summary,
            commit_ref: resolved_commit,
            dirty_signature: None,
        });
    }

    let git_head = short_git_head(sandbox_code_root, &env).await?;
    Ok(AcceptedWorktreeIntegrationResult {
        status: "merged".to_string(),
        summary: compact_text(
            &format!(
                "resolved_commit_ref={resolved_commit}\n{}\nstatus=merged\ngit_head={git_head}",
                merge.stdout.trim()
            ),
            1200,
        ),
        commit_ref: resolved_commit,
        dirty_signature: None,
    })
}

async fn resolve_accepted_worktree_commit(
    worktree_path: &Path,
    commit_ref: &str,
    env: &[(String, String)],
) -> CoreResult<Option<String>> {
    let exists = run_git_command(
        worktree_path,
        &["cat-file", "-e", &format!("{commit_ref}^{{commit}}")],
        env,
        60,
    )
    .await?;
    if exists.exit_code == 0 {
        let resolved = run_git_command(
            worktree_path,
            &["rev-parse", &format!("{commit_ref}^{{commit}}")],
            env,
            60,
        )
        .await?;
        if resolved.exit_code == 0 {
            return Ok(Some(resolved.stdout.trim().to_string()));
        }
    }
    let short_commit = commit_ref.chars().take(12).collect::<String>();
    let repaired = run_git_command(
        worktree_path,
        &[
            "rev-parse",
            "--verify",
            "--quiet",
            &format!("{short_commit}^{{commit}}"),
        ],
        env,
        60,
    )
    .await?;
    if repaired.exit_code == 0 {
        let value = repaired.stdout.trim();
        if !value.is_empty() {
            return Ok(Some(value.to_string()));
        }
    }
    Ok(None)
}

pub(super) async fn short_git_head(cwd: &Path, env: &[(String, String)]) -> CoreResult<String> {
    let head = run_git_command(cwd, &["rev-parse", "--short", "HEAD"], env, 60).await?;
    if head.exit_code == 0 {
        Ok(head.stdout.trim().to_string())
    } else {
        Ok("unknown".to_string())
    }
}

async fn git_blob_hash(cwd: &Path, text: &str, env: &[(String, String)]) -> CoreResult<String> {
    let hash = run_git_command_with_stdin(cwd, &["hash-object", "--stdin"], env, 60, text).await?;
    if hash.exit_code == 0 {
        Ok(hash.stdout.trim().to_string())
    } else {
        Ok(format!("git_hash_failed:{}", compact_git_error(&hash)))
    }
}

pub(super) async fn current_worktree_dirty_signature(cwd: &Path) -> CoreResult<Option<String>> {
    if !cwd.exists() {
        return Ok(None);
    }
    let env = vec![("GIT_TERMINAL_PROMPT".to_string(), "0".to_string())];
    let dirty = run_git_command(cwd, &["status", "--porcelain"], &env, 60).await?;
    if dirty.exit_code != 0 || dirty.stdout.trim().is_empty() {
        return Ok(None);
    }
    git_blob_hash(cwd, &dirty.stdout, &env).await.map(Some)
}

fn create_git_askpass_script() -> CoreResult<PathBuf> {
    let path = std::env::temp_dir().join(format!("memstack-git-askpass-{}.sh", generate_uuid_v4()));
    std::fs::write(
        &path,
        "#!/bin/sh\ncase \"$1\" in\n*Username*) printf '%s\\n' \"${GIT_USERNAME:-x-access-token}\" ;;\n*) printf '%s\\n' \"$GIT_TOKEN\" ;;\nesac\n",
    )
    .map_err(|err| {
        CoreError::Storage(format!(
            "failed to write git askpass script {}: {err}",
            path.display()
        ))
    })?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut permissions = std::fs::metadata(&path)
            .map_err(|err| {
                CoreError::Storage(format!(
                    "failed to stat git askpass script {}: {err}",
                    path.display()
                ))
            })?
            .permissions();
        permissions.set_mode(0o700);
        std::fs::set_permissions(&path, permissions).map_err(|err| {
            CoreError::Storage(format!(
                "failed to chmod git askpass script {}: {err}",
                path.display()
            ))
        })?;
    }
    Ok(path)
}

pub(super) fn compact_git_error(result: &GitCommandOutput) -> String {
    let text = if result.stderr.trim().is_empty() {
        result.stdout.trim()
    } else {
        result.stderr.trim()
    };
    if text.is_empty() {
        return format!("git exited with {}", result.exit_code);
    }
    compact_text(text, 1200)
}

fn is_non_fast_forward_push_rejection(result: &GitCommandOutput) -> bool {
    let text = format!("{}\n{}", result.stdout, result.stderr).to_ascii_lowercase();
    text.contains("non-fast-forward")
        || text.contains("fetch first")
        || text.contains("updates were rejected")
        || text.contains("tip of your current branch is behind")
        || text.contains("not possible to fast-forward")
}

fn is_unrelated_history_merge_rejection(result: &GitCommandOutput) -> bool {
    let text = format!("{}\n{}", result.stdout, result.stderr);
    text.to_ascii_lowercase()
        .contains("refusing to merge unrelated histories")
        || text.contains("拒绝合并无关的历史")
}

fn pipeline_stage_specs_from_json(
    commands_json: &Value,
    default_timeout: i32,
) -> Vec<PipelineStageSpec> {
    commands_json
        .as_array()
        .map(|stages| {
            stages
                .iter()
                .filter_map(|stage| {
                    let map = stage.as_object()?;
                    let stage_name =
                        string_from_map(map, "stage").or_else(|| string_from_map(map, "id"))?;
                    let command = string_from_map(map, "command")?;
                    Some(PipelineStageSpec {
                        stage: stage_name,
                        command,
                        required: bool_from_map_default(map, "required", true),
                        timeout_seconds: positive_i32_from_map(
                            map,
                            "timeout_seconds",
                            default_timeout,
                        ),
                        service_id: string_from_map(map, "service_id"),
                    })
                })
                .collect()
        })
        .unwrap_or_default()
}

fn wrapped_pipeline_command(command: &str, code_root: Option<&str>, env_json: &Value) -> String {
    let mut lines = vec!["set +e".to_string()];
    if let Some(code_root) = code_root.filter(|value| !value.trim().is_empty()) {
        let quoted = shell_quote(code_root);
        lines.push(format!("cd {quoted}"));
        lines.push("code=$?".to_string());
        lines.push("if [ \"$code\" -ne 0 ]; then".to_string());
        lines.push(format!(
            "  printf 'workspace pipeline code_root is not accessible: %s\\n' {quoted} >&2"
        ));
        lines.push(format!(
            "  printf \"\\n{PIPELINE_EXIT_MARKER}%s\\n\" \"$code\""
        ));
        lines.push("  exit 0".to_string());
        lines.push("fi".to_string());
    }
    for (key, value) in sorted_pipeline_env(env_json) {
        lines.push(format!("export {key}={}", shell_quote(&value)));
    }
    lines.push("(".to_string());
    lines.push(command.to_string());
    lines.push(")".to_string());
    lines.push("code=$?".to_string());
    lines.push(format!(
        "printf \"\\n{PIPELINE_EXIT_MARKER}%s\\n\" \"$code\""
    ));
    lines.push("exit 0".to_string());
    lines.join("\n")
}

fn sorted_pipeline_env(env_json: &Value) -> Vec<(String, String)> {
    let mut values = env_json
        .as_object()
        .into_iter()
        .flat_map(|env| env.iter())
        .filter_map(|(key, value)| {
            if key
                .replace('_', "")
                .chars()
                .all(|ch| ch.is_ascii_alphanumeric())
            {
                value.as_str().map(|value| (key.clone(), value.to_string()))
            } else {
                None
            }
        })
        .collect::<Vec<_>>();
    values.sort_by(|left, right| left.0.cmp(&right.0));
    values
}

fn shell_quote(value: &str) -> String {
    if value.is_empty() {
        return "''".to_string();
    }
    format!("'{}'", value.replace('\'', "'\\''"))
}

fn pipeline_stage_result_from_tool_response(
    stage: &PipelineStageSpec,
    response: ExecuteToolResponse,
    duration_ms: i32,
) -> PipelineStageResult {
    let text = tool_response_text(&response);
    let stdout = if response.is_error {
        String::new()
    } else {
        text.clone()
    };
    let stderr = if response.is_error {
        text.clone()
    } else {
        String::new()
    };
    let combined = format!("{stdout}\n{stderr}").trim().to_string();
    let exit_code =
        exit_code_from_pipeline_output(&combined).unwrap_or(if response.is_error { 1 } else { 0 });
    let cleaned = strip_pipeline_exit_markers(&combined);
    let status = if exit_code == 0 { "success" } else { "failed" }.to_string();
    let log_ref = format!(
        "sandbox://pipeline/{}/{}.log",
        generate_uuid_v4(),
        stage.stage
    );
    PipelineStageResult {
        stage: stage.stage.clone(),
        status,
        command: stage.command.clone(),
        exit_code: Some(exit_code),
        stdout_preview: compact_text(&cleaned, 4_000),
        stderr_preview: if exit_code == 0 {
            String::new()
        } else {
            compact_text(&stderr, 4_000)
        },
        duration_ms,
        log_ref: Some(log_ref.clone()),
        artifact_refs: vec![format!("pipeline_log:{}:{log_ref}", stage.stage)],
        service_id: stage.service_id.clone(),
        required: stage.required,
    }
}

fn tool_response_text(response: &ExecuteToolResponse) -> String {
    response
        .content
        .iter()
        .filter_map(|item| {
            item.get("text")
                .and_then(Value::as_str)
                .or_else(|| item.as_str())
        })
        .collect::<Vec<_>>()
        .join("\n")
}

fn exit_code_from_pipeline_output(output: &str) -> Option<i32> {
    let start = output.find(PIPELINE_EXIT_MARKER)? + PIPELINE_EXIT_MARKER.len();
    let digits = output[start..]
        .chars()
        .take_while(|ch| ch.is_ascii_digit())
        .collect::<String>();
    digits.parse().ok()
}

fn strip_pipeline_exit_markers(output: &str) -> String {
    output
        .lines()
        .filter(|line| !line.contains(PIPELINE_EXIT_MARKER))
        .collect::<Vec<_>>()
        .join("\n")
        .trim()
        .to_string()
}

pub(super) fn compact_text(value: &str, limit: usize) -> String {
    let compacted = value.trim();
    if compacted.len() <= limit {
        return compacted.to_string();
    }
    let prefix = compacted
        .chars()
        .take(limit.saturating_sub(15))
        .collect::<String>();
    format!("{prefix}...[truncated]")
}

fn saturating_duration_ms(duration_ms: u128) -> i32 {
    i32::try_from(duration_ms).unwrap_or(i32::MAX)
}

fn pipeline_contract_foundation(workspace: &WorkspaceRecord) -> PipelineContractFoundation {
    let workspace_metadata = object_or_empty(workspace.metadata_json.clone());
    let delivery = workspace_metadata
        .get("delivery_cicd")
        .cloned()
        .map(object_or_empty)
        .unwrap_or_default();
    let provider = normalize_pipeline_provider(
        string_from_map(&delivery, "provider")
            .unwrap_or_else(|| SANDBOX_NATIVE_PROVIDER.to_string())
            .as_str(),
    );
    let timeout_seconds = positive_i32_from_map(
        &delivery,
        "timeout_seconds",
        DEFAULT_PIPELINE_TIMEOUT_SECONDS,
    );
    let auto_deploy = bool_from_map_default(&delivery, "auto_deploy", true);
    let preview_port = Some(positive_i32_from_map(
        &delivery,
        "preview_port",
        DEFAULT_PREVIEW_PORT,
    ));
    let health_url = string_from_map(&delivery, "health_url");
    let deploy_command = string_from_map(&delivery, "deploy_command");
    let agent_managed = bool_from_map_default(&delivery, "agent_managed", true);
    let contract_source = string_from_map(&delivery, "contract_source").unwrap_or_else(|| {
        if delivery.get("agent_proposal").is_some_and(Value::is_object) {
            "agent_proposal".to_string()
        } else {
            "metadata".to_string()
        }
    });
    let contract_confidence = delivery
        .get("contract_confidence")
        .and_then(Value::as_f64)
        .filter(|value| (0.0..=1.0).contains(value))
        .unwrap_or(1.0);
    let host_code_root = host_code_root_from_workspace(&workspace.metadata_json);
    let code_root = string_from_map(&delivery, "code_root")
        .or_else(|| string_from_map(&workspace_metadata, "sandbox_code_root"))
        .or_else(|| {
            workspace_metadata
                .get("code_context")
                .and_then(Value::as_object)
                .and_then(|code_context| string_from_map(code_context, "sandbox_code_root"))
        });
    let commands_json = pipeline_stage_specs_json(&delivery, timeout_seconds);
    let env_json = string_map_json(delivery.get("env"));
    let services_json = delivery
        .get("services")
        .filter(|value| value.is_array())
        .cloned()
        .unwrap_or_else(|| json!([]));
    let provider_config = pipeline_provider_config_json(&delivery, &provider);
    let metadata_json = json!({
        "source": "workspace_plan.pipeline_run_requested",
        "agent_managed": agent_managed,
        "contract_source": contract_source,
        "contract_confidence": contract_confidence,
        "services": services_json.clone(),
        "provider_config": provider_config.clone()
    });
    PipelineContractFoundation {
        provider,
        host_code_root,
        code_root,
        commands_json,
        env_json,
        timeout_seconds,
        auto_deploy,
        preview_port,
        health_url,
        services_json,
        deploy_command,
        agent_managed,
        contract_source,
        provider_config_json: provider_config,
        metadata_json,
    }
}

fn normalize_pipeline_provider(value: &str) -> String {
    match value.trim() {
        "memstack-sandbox" | "sandbox_native" | "" => SANDBOX_NATIVE_PROVIDER.to_string(),
        other => other.to_string(),
    }
}

fn pipeline_provider_config_json(delivery: &Map<String, Value>, provider: &str) -> Value {
    let mut provider_config = Map::new();
    if let Some(raw) = delivery.get("provider_config").and_then(Value::as_object) {
        if let Some(scoped) = raw.get(provider).and_then(Value::as_object) {
            provider_config.extend(scoped.clone());
        } else {
            provider_config.extend(raw.clone());
        }
    }
    if let Some(scoped) = delivery.get(provider).and_then(Value::as_object) {
        provider_config.extend(scoped.clone());
    }
    for key in [
        "repo",
        "repository",
        "branch",
        "commit",
        "target",
        "params",
        "build_params",
        "server_url",
        "server_url_env",
        "token_env",
        "poll_interval_seconds",
        "deploy",
    ] {
        if !provider_config.contains_key(key) {
            if let Some(value) = delivery.get(key) {
                provider_config.insert(key.to_string(), value.clone());
            }
        }
    }
    Value::Object(provider_config)
}

fn pipeline_stage_specs_json(delivery: &Map<String, Value>, timeout_seconds: i32) -> Value {
    if let Some(stages) = delivery.get("stages").and_then(Value::as_array) {
        let normalized = stages
            .iter()
            .filter_map(|stage| pipeline_stage_from_value(stage, timeout_seconds))
            .collect::<Vec<_>>();
        return Value::Array(normalized);
    }
    let command_keys = [
        ("install", "install_command"),
        ("lint", "lint_command"),
        ("test", "test_command"),
        ("build", "build_command"),
    ];
    let configured = command_keys
        .iter()
        .filter_map(|(stage, key)| {
            string_from_map(delivery, key).map(|command| {
                json!({
                    "stage": stage,
                    "command": command,
                    "required": true,
                    "timeout_seconds": timeout_seconds
                })
            })
        })
        .collect::<Vec<_>>();
    if !configured.is_empty() {
        return Value::Array(configured);
    }
    Value::Array(default_pipeline_stage_specs(timeout_seconds))
}

fn pipeline_stage_from_value(stage: &Value, default_timeout: i32) -> Option<Value> {
    let map = stage.as_object()?;
    let stage_name = string_from_map(map, "stage").or_else(|| string_from_map(map, "id"))?;
    let command = string_from_map(map, "command")?;
    let mut payload = Map::new();
    payload.insert("stage".to_string(), json!(stage_name));
    payload.insert("command".to_string(), json!(command));
    payload.insert(
        "required".to_string(),
        json!(bool_from_map_default(map, "required", true)),
    );
    payload.insert(
        "timeout_seconds".to_string(),
        json!(positive_i32_from_map(
            map,
            "timeout_seconds",
            default_timeout
        )),
    );
    if let Some(service_id) = string_from_map(map, "service_id") {
        payload.insert("service_id".to_string(), json!(service_id));
    }
    Some(Value::Object(payload))
}

fn default_pipeline_stage_specs(timeout_seconds: i32) -> Vec<Value> {
    vec![
        json!({
            "stage": "install",
            "command": default_install_command(),
            "required": true,
            "timeout_seconds": timeout_seconds
        }),
        json!({
            "stage": "lint",
            "command": default_lint_command(),
            "required": false,
            "timeout_seconds": timeout_seconds
        }),
        json!({
            "stage": "test",
            "command": default_test_command(),
            "required": true,
            "timeout_seconds": timeout_seconds
        }),
        json!({
            "stage": "build",
            "command": default_build_command(),
            "required": true,
            "timeout_seconds": timeout_seconds
        }),
    ]
}

fn default_install_command() -> &'static str {
    "if [ -f package.json ]; then if [ -f pnpm-lock.yaml ] && command -v pnpm >/dev/null 2>&1; then pnpm install --frozen-lockfile || pnpm install; elif [ -f package-lock.json ]; then npm ci || npm install; else npm install; fi; elif [ -f pyproject.toml ] && command -v uv >/dev/null 2>&1; then uv sync; else echo 'no install step'; fi"
}

fn default_lint_command() -> &'static str {
    "if [ -f Makefile ] && grep -qE '^lint:' Makefile; then make lint; elif [ -f package.json ]; then npm run lint --if-present; else echo 'no lint step'; fi"
}

fn default_test_command() -> &'static str {
    "if [ -f Makefile ] && grep -qE '^test:' Makefile; then make test; elif [ -f package.json ]; then if node -e \"const p=require('./package.json');process.exit(p.scripts&&p.scripts.test?0:1)\"; then npm test -- --runInBand=false 2>/dev/null || npm test; else echo 'no npm test script'; fi; elif [ -d tests ]; then pytest; else echo 'no test step'; fi"
}

fn default_build_command() -> &'static str {
    "if [ -f Makefile ] && grep -qE '^build:' Makefile; then make build; elif [ -f package.json ]; then npm run build --if-present; else echo 'no build step'; fi"
}

fn string_map_json(value: Option<&Value>) -> Value {
    let Some(map) = value.and_then(Value::as_object) else {
        return json!({});
    };
    let normalized = map
        .iter()
        .filter_map(|(key, value)| {
            if value.is_null() {
                None
            } else {
                Some((
                    key.clone(),
                    json!(value
                        .as_str()
                        .map_or_else(|| value.to_string(), ToOwned::to_owned)),
                ))
            }
        })
        .collect::<Map<_, _>>();
    Value::Object(normalized)
}

fn bool_from_map_default(map: &Map<String, Value>, key: &str, default: bool) -> bool {
    map.get(key).and_then(Value::as_bool).unwrap_or(default)
}

fn positive_i32_from_map(map: &Map<String, Value>, key: &str, default: i32) -> i32 {
    let parsed = map
        .get(key)
        .and_then(Value::as_i64)
        .and_then(|value| i32::try_from(value).ok())
        .unwrap_or(default);
    if parsed > 0 {
        parsed
    } else {
        default
    }
}

fn mark_pipeline_requested(
    node: &mut WorkspacePlanNodeRecord,
    item: &WorkspacePlanOutboxRecord,
    reason: &str,
    attempt_id: Option<&str>,
    now: DateTime<Utc>,
    runtime_state: &str,
) {
    let mut metadata = object_or_empty(node.metadata_json.clone());
    metadata.insert("pipeline_status".to_string(), json!("requested"));
    metadata.insert("pipeline_gate_status".to_string(), json!("requested"));
    metadata.insert("pipeline_requested_at".to_string(), json!(now.to_rfc3339()));
    metadata.insert("pipeline_request_outbox_id".to_string(), json!(item.id));
    metadata.insert("pipeline_request_reason".to_string(), json!(reason));
    metadata.insert("pipeline_runtime_state".to_string(), json!(runtime_state));
    if let Some(attempt_id) = attempt_id {
        metadata.insert(
            "pipeline_requested_attempt_id".to_string(),
            json!(attempt_id),
        );
    }
    node.execution = "idle".to_string();
    node.metadata_json = Value::Object(metadata);
    node.updated_at = Some(now);
}

fn can_reflect_existing_pipeline_run(
    run: &WorkspacePipelineRunRecord,
    node: &WorkspacePlanNodeRecord,
) -> bool {
    if run.status != "success" {
        return false;
    }
    pipeline_run_matches_node_expected_commit(run, node)
}

fn pipeline_run_matches_node_expected_commit(
    run: &WorkspacePipelineRunRecord,
    node: &WorkspacePlanNodeRecord,
) -> bool {
    let Some(expected) = node_expected_commit_ref(node) else {
        return true;
    };
    pipeline_run_source_commit_ref(run)
        .is_some_and(|actual| git_commit_refs_match(&actual, &expected))
}

fn pipeline_run_source_commit_ref(run: &WorkspacePipelineRunRecord) -> Option<String> {
    let metadata = object_or_empty(run.metadata_json.clone());
    metadata
        .get("source_publish_source_commit_ref")
        .and_then(Value::as_str)
        .and_then(commit_ref_token)
        .or_else(|| run.commit_ref.as_deref().and_then(commit_ref_token))
}

fn stale_pipeline_run_failure_metadata(
    run: &WorkspacePipelineRunRecord,
    node: &WorkspacePlanNodeRecord,
) -> (String, Value) {
    let stale_source_commit_ref = pipeline_run_source_commit_ref(run);
    let requested_source_commit_ref = node_expected_commit_ref(node);
    let stale = stale_source_commit_ref.as_deref().unwrap_or("unknown");
    let requested = requested_source_commit_ref.as_deref().unwrap_or("unknown");
    (
        format!("stale pipeline run source commit {stale} superseded by {requested}"),
        json!({
            "stale_pipeline_run": true,
            "stale_source_commit_ref": stale_source_commit_ref,
            "superseded_by_source_commit_ref": requested_source_commit_ref
        }),
    )
}

fn mark_existing_pipeline_run_running(
    node: &mut WorkspacePlanNodeRecord,
    run: &WorkspacePipelineRunRecord,
    now: DateTime<Utc>,
) {
    let mut metadata = object_or_empty(node.metadata_json.clone());
    metadata.insert("pipeline_run_id".to_string(), json!(run.id));
    metadata.insert("pipeline_status".to_string(), json!("running"));
    metadata.insert("pipeline_gate_status".to_string(), json!("running"));
    metadata.insert("pipeline_started_at".to_string(), json!(now.to_rfc3339()));
    node.execution = "idle".to_string();
    node.metadata_json = Value::Object(metadata);
    node.updated_at = Some(now);
}

fn reflect_existing_pipeline_run_to_node(
    node: &mut WorkspacePlanNodeRecord,
    run: &WorkspacePipelineRunRecord,
    now: DateTime<Utc>,
) {
    let mut metadata = object_or_empty(node.metadata_json.clone());
    for (key, value) in pipeline_node_metadata_projection(&run.metadata_json) {
        metadata.insert(key, value);
    }
    metadata.insert("pipeline_run_id".to_string(), json!(run.id));
    metadata.insert("pipeline_status".to_string(), json!(run.status));
    metadata.insert("pipeline_gate_status".to_string(), json!(run.status));

    if run.status == "success" {
        let evidence_refs = merge_string_values(
            metadata.get("pipeline_evidence_refs"),
            &[
                "ci_pipeline:passed".to_string(),
                format!("pipeline_run:success:{}", run.id),
            ],
        );
        metadata.insert("pipeline_evidence_refs".to_string(), json!(evidence_refs));
        metadata.insert(
            "last_verification_summary".to_string(),
            json!("harness-native CI/CD pipeline passed"),
        );
        metadata.insert("last_verification_passed".to_string(), json!(true));
        metadata.insert("last_verification_hard_fail".to_string(), json!(false));
        metadata.insert(
            "last_verification_ran_at".to_string(),
            json!(now.to_rfc3339()),
        );
        let (intent, execution) = pipeline_completion_node_state(node, &metadata, &run.status);
        node.intent = intent;
        node.execution = execution;
    }

    node.metadata_json = Value::Object(metadata);
    node.updated_at = Some(now);
}

#[allow(clippy::too_many_arguments)]
fn finish_pipeline_on_node(
    node: &mut WorkspacePlanNodeRecord,
    run: &WorkspacePipelineRunRecord,
    status: &str,
    reason: Option<&str>,
    evidence_refs: &[String],
    preview_url: Option<&str>,
    health_url: Option<&str>,
    now: DateTime<Utc>,
) {
    let mut metadata = object_or_empty(node.metadata_json.clone());
    for (key, value) in pipeline_node_metadata_projection(&run.metadata_json) {
        metadata.insert(key, value);
    }
    let summary = reason.unwrap_or("harness-native CI/CD pipeline passed");
    metadata.insert("pipeline_run_id".to_string(), json!(run.id));
    metadata.insert("pipeline_status".to_string(), json!(status));
    metadata.insert("pipeline_gate_status".to_string(), json!(status));
    metadata.insert("pipeline_finished_at".to_string(), json!(now.to_rfc3339()));
    metadata.insert("pipeline_last_summary".to_string(), json!(summary));
    let pipeline_evidence_refs =
        merge_string_values(metadata.get("pipeline_evidence_refs"), evidence_refs);
    metadata.insert(
        "pipeline_evidence_refs".to_string(),
        json!(pipeline_evidence_refs),
    );
    let execution_verifications =
        merge_string_values(metadata.get("execution_verifications"), evidence_refs);
    metadata.insert(
        "execution_verifications".to_string(),
        json!(execution_verifications),
    );
    let merged_evidence_refs = merge_string_values(metadata.get("evidence_refs"), evidence_refs);
    metadata.insert("evidence_refs".to_string(), json!(merged_evidence_refs));
    if let Some(preview_url) = preview_url {
        metadata.insert("preview_url".to_string(), json!(preview_url));
    }
    if let Some(health_url) = health_url {
        metadata.insert("health_url".to_string(), json!(health_url));
    }
    if status == "success" {
        metadata.insert("last_verification_summary".to_string(), json!(summary));
        metadata.insert("last_verification_passed".to_string(), json!(true));
        metadata.insert("last_verification_hard_fail".to_string(), json!(false));
        metadata.insert(
            "last_verification_ran_at".to_string(),
            json!(now.to_rfc3339()),
        );
        metadata.remove("pipeline_stop_reason");
    }
    let (intent, execution) = pipeline_completion_node_state(node, &metadata, status);
    node.intent = intent;
    node.execution = execution;
    node.metadata_json = Value::Object(metadata);
    node.updated_at = Some(now);
}

fn pipeline_completed_supervisor_tick(
    workspace_id: &str,
    plan_id: &str,
    node_id: &str,
    pipeline_run_id: &str,
    pipeline_status: &str,
    now: DateTime<Utc>,
) -> WorkspacePlanOutboxRecord {
    pipeline_completed_supervisor_tick_with_source(
        workspace_id,
        plan_id,
        node_id,
        pipeline_run_id,
        pipeline_status,
        "workspace_plan.pipeline_run_completed",
        now,
    )
}

fn pipeline_completed_supervisor_tick_with_source(
    workspace_id: &str,
    plan_id: &str,
    node_id: &str,
    pipeline_run_id: &str,
    pipeline_status: &str,
    source: &str,
    now: DateTime<Utc>,
) -> WorkspacePlanOutboxRecord {
    WorkspacePlanOutboxRecord {
        id: generate_uuid_v4(),
        plan_id: Some(plan_id.to_string()),
        workspace_id: workspace_id.to_string(),
        event_type: SUPERVISOR_TICK_EVENT.to_string(),
        payload_json: json!({
            "workspace_id": workspace_id,
            "plan_id": plan_id,
            "node_id": node_id,
            "pipeline_run_id": pipeline_run_id,
            "pipeline_status": pipeline_status
        }),
        status: "pending".to_string(),
        attempt_count: 0,
        max_attempts: 3,
        lease_owner: None,
        lease_expires_at: None,
        last_error: None,
        next_attempt_at: None,
        processed_at: None,
        metadata_json: json!({"source": source}),
        created_at: now,
        updated_at: None,
    }
}

fn pipeline_node_metadata_projection(run_metadata: &Value) -> Map<String, Value> {
    let mut projected = Map::new();
    let Some(run_metadata) = run_metadata.as_object() else {
        return projected;
    };
    for (key, value) in run_metadata {
        if key.starts_with("source_publish_") {
            projected.insert(key.clone(), value.clone());
        }
    }
    for key in [
        "deploy_mode",
        "deploy_validation",
        "deployment_status",
        "external_id",
        "external_provider",
        "external_url",
        "pipeline_failed_stage",
        "pipeline_failure_summary",
        "pipeline_last_summary",
    ] {
        if let Some(value) = run_metadata.get(key) {
            projected.insert(key.to_string(), value.clone());
        }
    }
    projected
}

fn merge_string_values(existing: Option<&Value>, additions: &[String]) -> Vec<String> {
    let mut values = metadata_string_values(existing);
    for value in additions {
        let value = value.trim();
        if !value.is_empty() {
            values.push(value.to_string());
        }
    }
    dedup_strings(&mut values);
    values
}

pub(super) fn build_worker_report_payload(
    task_metadata: &Map<String, Value>,
    report_type: &str,
    summary: &str,
    artifacts: &[String],
    report_id: Option<&str>,
) -> WorkerReportPayload {
    let (normalized_summary, mut report_artifacts, mut report_verifications) =
        parse_worker_report_payload(report_type, summary, artifacts);
    let mut merged_artifacts = metadata_string_values(task_metadata.get("evidence_refs"));
    let mut report_artifacts_for_merge = report_artifacts.clone();
    merged_artifacts.append(&mut report_artifacts_for_merge);
    dedup_strings(&mut merged_artifacts);
    let mut merged_verifications =
        metadata_string_values(task_metadata.get("execution_verifications"));
    let mut report_verifications_for_merge = report_verifications.clone();
    merged_verifications.append(&mut report_verifications_for_merge);
    dedup_strings(&mut merged_verifications);
    let fingerprint = worker_report_fingerprint(
        report_type,
        &normalized_summary,
        &merged_artifacts,
        &report_verifications,
        report_id,
    );
    dedup_strings(&mut report_artifacts);
    dedup_strings(&mut report_verifications);
    WorkerReportPayload {
        normalized_summary,
        report_artifacts,
        merged_artifacts,
        report_verifications,
        merged_verifications,
        fingerprint,
    }
}

fn parse_worker_report_payload(
    report_type: &str,
    summary: &str,
    artifacts: &[String],
) -> (String, Vec<String>, Vec<String>) {
    let mut normalized_summary = summary.trim().to_string();
    if normalized_summary.is_empty() {
        normalized_summary = format!("worker_report:{report_type}");
    }
    let mut merged_artifacts = artifacts
        .iter()
        .map(|artifact| artifact.trim())
        .filter(|artifact| !artifact.is_empty())
        .map(ToOwned::to_owned)
        .collect::<Vec<_>>();
    let mut verifications = Vec::new();

    if let Ok(Value::Object(payload)) = serde_json::from_str::<Value>(summary) {
        if let Some(payload_summary) = metadata_string(payload.get("summary")) {
            normalized_summary = payload_summary;
        }
        for item in metadata_string_values(payload.get("artifacts")) {
            merged_artifacts.push(item);
        }
        for item in metadata_string_values(payload.get("verifications")) {
            verifications.push(item);
        }
        if let Some(commit_ref) = metadata_string(payload.get("commit_ref")) {
            merged_artifacts.push(format!("commit_ref:{commit_ref}"));
        }
        if let Some(git_diff_summary) = metadata_string(payload.get("git_diff_summary")) {
            merged_artifacts.push(format!("git_diff_summary:{git_diff_summary}"));
        }
        for path in metadata_string_values(payload.get("changed_files")) {
            merged_artifacts.push(format!("changed_file:{path}"));
        }
        for command in metadata_string_values(payload.get("test_commands")) {
            verifications.push(format!("test_run:{command}"));
        }
        if let Some(verdict) = metadata_string(payload.get("verdict"))
            .or_else(|| metadata_string(payload.get("outcome")))
        {
            verifications.push(format!("worker_verdict:{verdict}"));
        }
        if let Some(grade) = metadata_string(payload.get("verification_grade")) {
            verifications.push(format!("verification_grade:{grade}"));
        }
    }

    if report_type == "completed" && verifications.is_empty() {
        verifications.push("worker_report:completed".to_string());
    }
    dedup_strings(&mut merged_artifacts);
    dedup_strings(&mut verifications);
    (normalized_summary, merged_artifacts, verifications)
}

fn worker_report_fingerprint(
    report_type: &str,
    summary: &str,
    artifacts: &[String],
    verifications: &[String],
    report_id: Option<&str>,
) -> String {
    let serialized = format!(
        "{{\"artifacts\": {}, \"report_id\": {}, \"report_type\": {}, \"summary\": {}, \"verifications\": {}}}",
        python_json_string_array(artifacts),
        python_json_string(report_id.unwrap_or("")),
        python_json_string(report_type),
        python_json_string(summary),
        python_json_string_array(verifications)
    );
    let mut hasher = Sha256::new();
    hasher.update(serialized.as_bytes());
    format!("{:x}", hasher.finalize())
}

fn python_json_string(value: &str) -> String {
    serde_json::to_string(value).unwrap_or_else(|_| "\"\"".to_string())
}

fn python_json_string_array(values: &[String]) -> String {
    if values.is_empty() {
        return "[]".to_string();
    }
    format!(
        "[{}]",
        values
            .iter()
            .map(|value| python_json_string(value))
            .collect::<Vec<_>>()
            .join(", ")
    )
}

pub(super) fn is_stale_terminal_worker_report(
    task_metadata: &Map<String, Value>,
    attempt_id: &str,
) -> bool {
    string_from_map(task_metadata, CURRENT_ATTEMPT_ID)
        .as_deref()
        .is_some_and(|current_attempt_id| {
            !current_attempt_id.is_empty() && current_attempt_id != attempt_id
        })
}

pub(super) fn worker_execution_state(
    phase: &str,
    reason: &str,
    action: &str,
    actor_id: &str,
    now: DateTime<Utc>,
) -> Value {
    json!({
        "phase": phase,
        "last_agent_reason": reason,
        "last_agent_action": action,
        "updated_by_actor_type": "agent",
        "updated_by_actor_id": actor_id,
        "updated_at": now.to_rfc3339()
    })
}

fn pipeline_completion_node_state(
    node: &WorkspacePlanNodeRecord,
    metadata: &Map<String, Value>,
    status: &str,
) -> (String, String) {
    if status != "success" {
        return ("in_progress".to_string(), "reported".to_string());
    }
    let phase = metadata_string(metadata.get("iteration_phase"));
    if node.current_attempt_id.is_some()
        || matches!(phase.as_deref(), Some("test" | "deploy" | "review"))
    {
        return ("done".to_string(), "idle".to_string());
    }
    ("in_progress".to_string(), "reported".to_string())
}
