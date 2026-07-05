use super::*;

mod cli;
mod config;
mod deploy;
mod http;
mod preflight;
mod result;

use cli::*;
use config::{drone_pipeline_config, DroneDeployConfig, DronePipelineConfig};
use deploy::*;
use http::*;
use preflight::*;
pub(super) use result::finish_drone_pipeline_result;
use result::{
    drone_api_failure_result, drone_build_matches_commit, drone_configuration_failure_result,
    drone_logs_text, drone_path_segment, drone_pipeline_stage_result,
    drone_result_from_build_and_stages, drone_status, is_drone_running_status,
    is_drone_terminal_status, log_part, looks_like_drone_not_found, optional_i32, required_i64,
    DronePipelineStageInput,
};

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
