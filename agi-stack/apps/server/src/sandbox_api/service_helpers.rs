use super::*;

pub(super) fn datetime_from_ms(ms: i64) -> chrono::DateTime<chrono::Utc> {
    chrono::DateTime::<chrono::Utc>::from_timestamp_millis(ms)
        .unwrap_or(chrono::DateTime::<chrono::Utc>::UNIX_EPOCH)
}

pub(super) fn profile_from_metadata(metadata: &serde_json::Value) -> SandboxProfile {
    metadata
        .get("profile")
        .and_then(serde_json::Value::as_str)
        .and_then(|raw| SandboxProfile::parse(Some(raw)).ok().flatten())
        .unwrap_or(SandboxProfile::Standard)
}

pub(super) fn normalize_sandbox_type(raw: &str) -> String {
    match raw.trim().to_ascii_lowercase().as_str() {
        "local" => "local".to_string(),
        _ => "cloud".to_string(),
    }
}

pub(super) fn project_sandbox_config_from_record(
    record: ProjectReadRecord,
) -> ProjectSandboxConfig {
    let mut sandbox_type = normalize_sandbox_type(&record.sandbox_type);
    if let Some(raw_type) = string_field(&record.sandbox_config, "sandbox_type") {
        sandbox_type = normalize_sandbox_type(&raw_type);
    }
    let local_config = record
        .sandbox_config
        .get("local_config")
        .filter(|value| !value.is_null())
        .cloned()
        .unwrap_or_else(|| json!({}));
    ProjectSandboxConfig {
        sandbox_type,
        local_config,
    }
}

pub(super) fn initial_metadata(profile: SandboxProfile) -> Value {
    let mut map = Map::new();
    map.insert(
        "profile".to_string(),
        Value::String(profile.as_str().to_string()),
    );
    if let Ok(url) = std::env::var("AGISTACK_SANDBOX_MCP_URL") {
        let url = url.trim();
        if !url.is_empty() {
            map.insert("endpoint".to_string(), Value::String(url.to_string()));
            map.insert("websocket_url".to_string(), Value::String(url.to_string()));
        }
    }
    if let Ok(port) = std::env::var("AGISTACK_SANDBOX_MCP_PORT") {
        if let Ok(port) = port.trim().parse::<u16>() {
            map.insert("mcp_port".to_string(), Value::from(port));
            map.entry("endpoint".to_string())
                .or_insert_with(|| Value::String(format!("ws://127.0.0.1:{port}")));
            map.entry("websocket_url".to_string())
                .or_insert_with(|| Value::String(format!("ws://127.0.0.1:{port}")));
        }
    }
    Value::Object(map)
}

pub(super) fn local_metadata(profile: SandboxProfile, local_config: &Value) -> Value {
    let mut map = Map::new();
    map.insert(
        "profile".to_string(),
        Value::String(profile.as_str().to_string()),
    );
    map.insert(
        "sandbox_type".to_string(),
        Value::String("local".to_string()),
    );
    if let Some(url) = local_config_websocket_url(local_config) {
        map.insert("endpoint".to_string(), Value::String(url.clone()));
        map.insert("websocket_url".to_string(), Value::String(url.clone()));
        map.insert("mcp_url".to_string(), Value::String(url));
    }
    if let Some(port) = port_field(local_config, "port") {
        map.insert("mcp_port".to_string(), Value::from(port));
    }
    Value::Object(map)
}

pub(super) fn string_field(value: &Value, key: &str) -> Option<String> {
    value
        .get(key)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
}

pub(super) fn port_field(value: &Value, key: &str) -> Option<u16> {
    value.get(key).and_then(|value| {
        value
            .as_u64()
            .and_then(|port| u16::try_from(port).ok())
            .or_else(|| value.as_str()?.trim().parse::<u16>().ok())
    })
}

pub(super) fn normalize_local_config(raw: Value) -> Value {
    let mut map = match raw {
        Value::Object(map) => map,
        _ => Map::new(),
    };
    map.entry("workspace_path".to_string())
        .or_insert_with(|| Value::String("/workspace".to_string()));
    map.entry("host".to_string())
        .or_insert_with(|| Value::String("localhost".to_string()));
    map.entry("port".to_string())
        .or_insert_with(|| Value::from(8_765));
    Value::Object(map)
}

pub(super) fn local_config_websocket_url(local_config: &Value) -> Option<String> {
    let mut url = if let Some(tunnel_url) = string_field(local_config, "tunnel_url") {
        tunnel_url
    } else {
        let port = port_field(local_config, "port")?;
        let host = string_field(local_config, "host").unwrap_or_else(|| "localhost".to_string());
        let protocol = if host == "localhost" || host == "127.0.0.1" {
            "ws"
        } else {
            "wss"
        };
        format!("{protocol}://{host}:{port}")
    };
    if let Some(token) = string_field(local_config, "auth_token") {
        url = append_local_auth_token(&url, &token);
    }
    Some(url)
}

pub(super) fn append_local_auth_token(url: &str, token: &str) -> String {
    if token.is_empty() || url.contains(&format!("{MCP_UPSTREAM_TOKEN_QUERY_PARAM}=")) {
        return url.to_string();
    }
    append_query_param(url, MCP_UPSTREAM_TOKEN_QUERY_PARAM, token)
}

pub(super) fn connection_url(metadata: &Value, local_config: &Value) -> Option<String> {
    string_field(metadata, "endpoint")
        .or_else(|| string_field(metadata, "websocket_url"))
        .or_else(|| string_field(metadata, "mcp_url"))
        .or_else(|| local_config_websocket_url(local_config))
}

pub(super) fn normalize_tool_result(raw: &str, execution_time_ms: i64) -> ExecuteToolResponse {
    let parsed = serde_json::from_str::<Value>(raw).unwrap_or_else(|_| {
        json!({
            "content": [{ "type": "text", "text": raw }],
            "is_error": false,
        })
    });
    let is_error = parsed
        .get("is_error")
        .or_else(|| parsed.get("isError"))
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let content = parsed
        .get("content")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    ExecuteToolResponse {
        success: !is_error,
        content,
        is_error,
        execution_time_ms: Some(execution_time_ms),
    }
}

pub(super) fn validate_http_service_name(name: &str) -> SandboxApiResult<()> {
    let len = name.chars().count();
    if len == 0 {
        return Err(SandboxApiError::bad_request(
            "name must contain at least 1 character",
        ));
    }
    if len > 120 {
        return Err(SandboxApiError::bad_request(
            "name must contain at most 120 characters",
        ));
    }
    Ok(())
}

pub(super) fn normalize_http_service_id(service_id: Option<&str>) -> SandboxApiResult<String> {
    let Some(service_id) = service_id else {
        let uuid =
            agistack_adapters_secrets::try_generate_uuid_v4().map_err(SandboxApiError::internal)?;
        return Ok(format!(
            "http-{}",
            uuid.replace('-', "").chars().take(12).collect::<String>()
        ));
    };
    let normalized = service_id.trim();
    if normalized.is_empty() {
        return Err(SandboxApiError::bad_request("service_id cannot be empty"));
    }
    if normalized.len() > 128
        || !normalized
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '.' | '_' | ':' | '-'))
    {
        return Err(SandboxApiError::bad_request(
            "service_id contains invalid characters",
        ));
    }
    Ok(normalized.to_string())
}

pub(super) fn normalize_internal_scheme(scheme: &str) -> SandboxApiResult<String> {
    let scheme = scheme.trim().to_ascii_lowercase();
    match scheme.as_str() {
        "http" | "https" => Ok(scheme),
        _ => Err(SandboxApiError::bad_request(
            "internal_scheme must be http or https",
        )),
    }
}

pub(super) fn normalize_path_prefix(path_prefix: &str) -> String {
    let normalized = path_prefix.trim();
    if normalized.is_empty() {
        return "/".to_string();
    }
    if normalized.starts_with('/') {
        normalized.to_string()
    } else {
        format!("/{normalized}")
    }
}

pub(super) fn validate_external_http_url(url: &str) -> SandboxApiResult<String> {
    let trimmed = url.trim();
    let rest = trimmed
        .strip_prefix("http://")
        .or_else(|| trimmed.strip_prefix("https://"))
        .ok_or_else(|| {
            SandboxApiError::bad_request("external_url must be a valid http/https URL")
        })?;
    let host = rest
        .split(['/', '?', '#'])
        .next()
        .unwrap_or_default()
        .trim();
    if host.is_empty() || host == ":" {
        return Err(SandboxApiError::bad_request(
            "external_url must be a valid http/https URL",
        ));
    }
    Ok(trimmed.to_string())
}

pub(super) fn sandbox_internal_service_host(info: &ProjectSandboxInfo) -> String {
    string_field(&info.metadata_json, "container_ip")
        .or_else(|| string_field(&info.local_config, "container_ip"))
        .or_else(|| std::env::var("AGISTACK_SANDBOX_INTERNAL_HOST").ok())
        .map(|host| host.trim().to_string())
        .filter(|host| !host.is_empty())
        .unwrap_or_else(|| "127.0.0.1".to_string())
}

pub(super) fn python_utc_offset_string(ms: i64) -> String {
    datetime_from_ms(ms).to_rfc3339_opts(chrono::SecondsFormat::Millis, false)
}

pub(super) fn http_service_not_found() -> SandboxApiError {
    SandboxApiError::not_found("HTTP service not found")
}
