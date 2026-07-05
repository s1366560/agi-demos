use super::*;

pub(super) fn drone_docker_deploy_validation_issues(
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

pub(in crate::workspace_outbox_worker::pipeline_drone) fn drone_docker_deploy_uses_forbidden_local_registry_pull(
    output: &str,
) -> bool {
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

pub(in crate::workspace_outbox_worker::pipeline_drone) fn drone_docker_deploy_has_run_marker(
    output: &str,
) -> bool {
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

pub(in crate::workspace_outbox_worker::pipeline_drone) fn drone_missing_docker_deploy_required_services(
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
