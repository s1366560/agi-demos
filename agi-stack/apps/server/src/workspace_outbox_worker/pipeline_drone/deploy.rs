use super::*;

mod docker;

use self::docker::drone_docker_deploy_validation_issues;
pub(super) use self::docker::{
    drone_docker_deploy_has_run_marker, drone_docker_deploy_uses_forbidden_local_registry_pull,
    drone_missing_docker_deploy_required_services,
};

pub(super) fn drone_is_deploy_stage(
    stage_name: &str,
    step_name: &str,
    deploy: Option<&DroneDeployConfig>,
) -> bool {
    let Some(deploy) = deploy else {
        return false;
    };
    drone_is_deploy_label(stage_name, deploy) || drone_is_deploy_label(step_name, deploy)
}

pub(super) fn drone_is_deploy_label(value: &str, deploy: &DroneDeployConfig) -> bool {
    let normalized = value.trim().to_ascii_lowercase();
    let configured = deploy.stage.trim().to_ascii_lowercase();
    normalized == configured
        || normalized.ends_with(&format!("/{configured}"))
        || normalized.starts_with("deploy-")
        || normalized.ends_with("-deploy")
        || normalized == "deployment"
}

pub(super) fn drone_deploy_state(
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

pub(super) fn drone_deploy_validation_issues(
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

pub(super) fn drone_deploy_failure_reason(
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

pub(super) fn drone_deploy_metadata(
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

pub(super) fn combine_failure_preview(error_text: &str, log_text: &str) -> String {
    let mut parts = Vec::new();
    for text in [error_text, log_text] {
        let value = text.trim();
        if !value.is_empty() && !parts.contains(&value) {
            parts.push(value);
        }
    }
    compact_text(&parts.join("\n"), 4_000)
}

pub(super) fn first_failed_drone_stage(
    stages: &[DronePipelineStageResult],
) -> Option<&DronePipelineStageResult> {
    stages.iter().find(|stage| stage.status == "failed")
}
