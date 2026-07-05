use super::*;

pub(super) fn drone_source_control_config(
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

pub(super) fn drone_source_branch(
    source_control: &Map<String, Value>,
    provider_config: &Map<String, Value>,
) -> Option<String> {
    string_from_map(provider_config, "branch")
        .or_else(|| string_from_map(source_control, "default_branch"))
        .filter(|branch| is_safe_git_branch(branch))
}

pub(in crate::workspace_outbox_worker) fn host_code_root_from_workspace(
    workspace_metadata: &Value,
) -> Option<String> {
    metadata_string_from_path(workspace_metadata, &["host_code_root"]).or_else(|| {
        metadata_string_from_path(workspace_metadata, &["code_context", "host_code_root"])
    })
}

pub(super) fn pipeline_contract_commit_ref(provider_config: &Map<String, Value>) -> Option<String> {
    string_from_map(provider_config, "commit").and_then(|value| commit_ref_token(&value))
}

pub(super) fn source_control_remote_url(source_control: &Map<String, Value>) -> Option<String> {
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

pub(super) fn source_control_token_env(source_control: &Map<String, Value>) -> Option<String> {
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

pub(super) async fn source_control_token(token_env: Option<&str>) -> Option<String> {
    let token_env = token_env?;
    if let Some(value) = std::env::var(token_env)
        .ok()
        .and_then(|value| metadata_string(Some(&Value::String(value))))
    {
        return Some(value);
    }
    source_publish_dotenv_value(token_env).await
}

pub(super) fn apply_drone_provider_config(
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
