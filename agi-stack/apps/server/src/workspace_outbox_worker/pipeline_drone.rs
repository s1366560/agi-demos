use super::*;

mod deploy;

use deploy::*;

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
pub(super) struct DronePipelineResult {
    pub(super) status: String,
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

pub(super) async fn run_drone_pipeline_if_configured(
    contract: &PipelineContractFoundation,
) -> CoreResult<Option<DronePipelineResult>> {
    let Some(config) = drone_pipeline_config(contract).await? else {
        return Ok(None);
    };
    let result = match run_drone_pipeline(&config).await {
        Ok(result) => result,
        Err(err) => drone_api_failure_result(&err.to_string()),
    };
    Ok(Some(result))
}

async fn drone_pipeline_config(
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
    let server_url = if let Some(server_url) = string_from_map(&provider_config, "server_url") {
        Some(server_url)
    } else if let Some(server_url) = drone_config_value_env(&server_env).await {
        Some(server_url)
    } else if server_env == DRONE_SERVER_URL_ENV {
        None
    } else {
        drone_config_value_env(DRONE_SERVER_URL_ENV).await
    };
    let Some(server_url) = server_url else {
        return Ok(None);
    };

    let token_env = string_from_map(&provider_config, "drone_token_env")
        .or_else(|| string_from_map(&provider_config, "token_env"))
        .unwrap_or_else(|| DRONE_TOKEN_ENV.to_string());
    let Some(token) = drone_config_value_env(&token_env).await else {
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
        cli_command: drone_cli_command_from_config(&provider_config).await,
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

async fn drone_cli_command_from_config(provider_config: &Map<String, Value>) -> String {
    if let Some(command) = string_from_map(provider_config, "drone_command")
        .or_else(|| string_from_map(provider_config, "cli_command"))
        .or_else(|| string_from_map(provider_config, "command"))
    {
        return command;
    }
    drone_config_value_env("DRONE_CLI")
        .await
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

async fn drone_yaml_preflight_failure_result(
    config: &DronePipelineConfig,
) -> Option<DronePipelineResult> {
    let host_code_root = config.host_code_root.as_ref()?;
    let path = host_code_root.join(".drone.yml");
    let content = match tokio::fs::read_to_string(&path).await {
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
    if let Some(result) = drone_yaml_preflight_failure_result(config).await {
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

pub(super) async fn finish_drone_pipeline_result(
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

async fn drone_config_value_env(name: &str) -> Option<String> {
    if let Some(value) = std::env::var(name)
        .ok()
        .and_then(|value| metadata_string(Some(&Value::String(value))))
    {
        return Some(value);
    }
    source_publish_dotenv_value(name).await
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
