use super::*;

pub(super) async fn run_drone_pipeline_http(
    config: &DronePipelineConfig,
) -> CoreResult<DronePipelineResult> {
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
