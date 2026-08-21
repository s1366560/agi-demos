use super::*;
use agistack_core::ports::ContainerSpec;
use sha2::{Digest, Sha256};

const DEFAULT_SANDBOX_SHM_SIZE_BYTES: i64 = 1_073_741_824;
const CHROMIUM_SECCOMP_PROFILE: &str = include_str!(
    "../../../../../src/infrastructure/adapters/secondary/sandbox/chromium_seccomp_profile.json"
);
const CHROMIUM_PROFILE_TARGET: &str = "/home/sandbox/.config/chromium";
const CHROMIUM_VOLUME_PREFIX: &str = "memstack-sky-cua-chromium-";
const CHROMIUM_RESOURCE_TYPE: &str = "sky-cua-chromium-profile";

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

pub(super) fn sandbox_container_spec(
    image: &str,
    project_id: &str,
    tenant_id: &str,
    profile: SandboxProfile,
    runtime_auth_token: &SandboxRuntimeToken,
) -> ContainerSpec {
    let interactive_enabled = !matches!(profile, SandboxProfile::Lite);
    let volume_name = sky_cua_chromium_volume_name(tenant_id, project_id);
    ContainerSpec {
        image: image.to_string(),
        cmd: None,
        env: vec![
            ("AGISTACK_PROJECT_ID".to_string(), project_id.to_string()),
            ("AGISTACK_TENANT_ID".to_string(), tenant_id.to_string()),
            (
                "AGISTACK_SANDBOX_PROFILE".to_string(),
                profile.as_str().to_string(),
            ),
            ("MCP_AUTH_ENABLED".to_string(), "true".to_string()),
            ("MCP_ALLOW_LOCALHOST".to_string(), "false".to_string()),
            (
                "MCP_STATIC_TOKEN".to_string(),
                runtime_auth_token.expose().to_string(),
            ),
            (
                "DESKTOP_ENABLED".to_string(),
                interactive_enabled.to_string(),
            ),
            (
                "TERMINAL_ENABLED".to_string(),
                interactive_enabled.to_string(),
            ),
        ],
        labels: vec![
            (PROJECT_LABEL.to_string(), project_id.to_string()),
            (TENANT_LABEL.to_string(), tenant_id.to_string()),
            (KIND_LABEL.to_string(), KIND_PROJECT.to_string()),
            (MEMSTACK_SANDBOX_LABEL.to_string(), "true".to_string()),
            (MEMSTACK_PROJECT_LABEL.to_string(), project_id.to_string()),
            (MEMSTACK_TENANT_LABEL.to_string(), tenant_id.to_string()),
        ],
        ports: sandbox_port_bindings(profile),
        shm_size_bytes: Some(sandbox_shm_size_bytes()),
        seccomp_profile: Some(CHROMIUM_SECCOMP_PROFILE.to_string()),
        named_volumes: vec![NamedVolumeMount {
            name: volume_name,
            container_path: CHROMIUM_PROFILE_TARGET.to_string(),
            read_only: false,
            labels: sky_cua_chromium_volume_labels(tenant_id, project_id),
        }],
    }
}

pub(super) fn sky_cua_chromium_volume_name(tenant_id: &str, project_id: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(tenant_id.as_bytes());
    hasher.update([0]);
    hasher.update(project_id.as_bytes());
    let digest = format!("{:x}", hasher.finalize());
    format!("{CHROMIUM_VOLUME_PREFIX}{}", &digest[..32])
}

pub(super) fn sky_cua_chromium_volume_labels(
    tenant_id: &str,
    project_id: &str,
) -> Vec<(String, String)> {
    vec![
        ("memstack.managed".to_string(), "true".to_string()),
        (
            "memstack.resource.type".to_string(),
            CHROMIUM_RESOURCE_TYPE.to_string(),
        ),
        (MEMSTACK_TENANT_LABEL.to_string(), tenant_id.to_string()),
        (MEMSTACK_PROJECT_LABEL.to_string(), project_id.to_string()),
    ]
}

fn sandbox_shm_size_bytes() -> i64 {
    std::env::var("SANDBOX_SHM_SIZE")
        .ok()
        .and_then(|raw| parse_shm_size_bytes(&raw))
        .unwrap_or(DEFAULT_SANDBOX_SHM_SIZE_BYTES)
}

pub(super) fn parse_shm_size_bytes(raw: &str) -> Option<i64> {
    let normalized = raw.trim().to_ascii_lowercase();
    let (number, multiplier) = match normalized.as_bytes().last().copied() {
        Some(b'k') => (&normalized[..normalized.len() - 1], 1_024_i64),
        Some(b'm') => (&normalized[..normalized.len() - 1], 1_048_576_i64),
        Some(b'g') => (&normalized[..normalized.len() - 1], 1_073_741_824_i64),
        _ => (normalized.as_str(), 1_i64),
    };
    number
        .parse::<i64>()
        .ok()
        .filter(|value| *value > 0)
        .and_then(|value| value.checked_mul(multiplier))
}

pub(super) fn python_utc_offset_string(ms: i64) -> String {
    datetime_from_ms(ms).to_rfc3339_opts(chrono::SecondsFormat::Millis, false)
}

pub(super) fn http_service_not_found() -> SandboxApiError {
    SandboxApiError::not_found("HTTP service not found")
}
