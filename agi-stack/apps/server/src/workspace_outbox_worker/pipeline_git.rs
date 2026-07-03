use super::*;

mod accepted;
mod commands;

pub(super) use self::accepted::integrate_accepted_attempt_worktree_with_git;
use self::commands::{
    compact_git_error as compact_git_error_for_publish, create_git_askpass_script,
    is_non_fast_forward_push_rejection, is_unrelated_history_merge_rejection,
    run_git_command_owned,
};
pub(super) use self::commands::{
    compact_git_error, current_worktree_dirty_signature, run_git_command, short_git_head,
};

#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) struct DroneSourcePublishFailure {
    pub(super) reason: String,
    metadata: Map<String, Value>,
}

impl DroneSourcePublishFailure {
    pub(super) fn evidence_refs(&self, run_id: &str) -> Vec<String> {
        vec![
            "ci_pipeline:failed".to_string(),
            "source_publish:failed".to_string(),
            format!("pipeline_run:failed:{run_id}"),
        ]
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) struct DroneSourcePublishSuccess {
    metadata: Map<String, Value>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) struct DroneSourcePublishSkipped {
    metadata: Map<String, Value>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) enum DroneSourcePublishOutcome {
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

    pub(super) fn failure(&self) -> Option<&DroneSourcePublishFailure> {
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

pub(super) async fn finish_drone_source_publish_failure(
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

pub(super) async fn finish_drone_provider_unavailable(
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

pub(super) fn pipeline_contract_metadata(
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

pub(super) fn pipeline_run_metadata(
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

pub(super) fn source_publish_source_commit_ref(
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

pub(super) async fn prepare_drone_source_publish(
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
    let token = source_control_token(token_env.as_deref()).await;
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

pub(super) fn host_code_root_from_workspace(workspace_metadata: &Value) -> Option<String> {
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

async fn source_control_token(token_env: Option<&str>) -> Option<String> {
    let token_env = token_env?;
    if let Some(value) = std::env::var(token_env)
        .ok()
        .and_then(|value| metadata_string(Some(&Value::String(value))))
    {
        return Some(value);
    }
    source_publish_dotenv_value(token_env).await
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
        let path = create_git_askpass_script().await?;
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
        let _ = tokio::fs::remove_file(path).await;
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
            reason: Some(compact_git_error_for_publish(&exists)),
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
                reason: Some(compact_git_error_for_publish(&fast_forward)),
                published_commit: None,
            });
        }
    }

    let head = run_git_command(host_code_root, &["rev-parse", "HEAD"], env, 60).await?;
    if head.exit_code != 0 {
        return Ok(GitPublishResult {
            status: "failed".to_string(),
            reason: Some(compact_git_error_for_publish(&head)),
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
        reason: Some(compact_git_error_for_publish(&push)),
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
    tokio::fs::create_dir_all(&temp_parent)
        .await
        .map_err(|err| {
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
                reason: Some(compact_git_error_for_publish(&add)),
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
                reason: Some(compact_git_error_for_publish(&head)),
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
                reason: Some(compact_git_error_for_publish(&push)),
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
    let _ = tokio::fs::remove_dir_all(&temp_parent).await;
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
            reason: Some(compact_git_error_for_publish(&retry_head)),
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
        let reason = compact_git_error_for_publish(&fetch);
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
        reason: Some(compact_git_error_for_publish(&merge_ours_strategy)),
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
                reason: Some(compact_git_error_for_publish(&checkout)),
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
                reason: Some(compact_git_error_for_publish(&remove)),
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
            reason: Some(compact_git_error_for_publish(&changed)),
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
            reason: Some(compact_git_error_for_publish(&commit)),
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
            reason: Some(compact_git_error_for_publish(&merge_unrelated_ours)),
        });
    }
    Ok(GitRemoteMergeResult {
        status: "failed".to_string(),
        reason: Some(compact_git_error_for_publish(&merge_ours)),
    })
}
