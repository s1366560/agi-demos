use super::*;

pub(super) async fn drone_yaml_preflight_failure_result(
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
