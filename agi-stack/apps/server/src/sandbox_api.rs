//! P5 project sandbox lifecycle foundation.
//!
//! This module wires the already-portable [`ContainerRuntime`] port into the
//! Rust `/api/v1/projects/{id}/sandbox*` surface without pulling Docker/bollard
//! into `core`. It covers lifecycle, tool execution, desktop/terminal/http
//! proxies, and the browser MCP WebSocket proxy as vertical P5 strangler slices
//! while keeping the heavy runtime concerns server-only.

#[cfg(test)]
use std::collections::BTreeMap;
use std::sync::Arc;
#[cfg(test)]
use std::sync::Mutex;

#[cfg(test)]
use async_trait::async_trait;
use axum::{
    body::{to_bytes, Body},
    extract::{
        ws::{CloseFrame as AxumCloseFrame, Message as AxumWsMessage, WebSocket, WebSocketUpgrade},
        Path, Query, RawQuery, State,
    },
    http::{
        header::{
            ACCEPT, ACCEPT_ENCODING, ACCEPT_LANGUAGE, CACHE_CONTROL, CONTENT_TYPE, LOCATION,
            SET_COOKIE,
        },
        HeaderMap, HeaderValue, Method, Request, StatusCode, Uri,
    },
    response::{IntoResponse, Response},
    routing::{any, delete, get, post},
    Extension, Json, Router,
};
#[cfg(test)]
use futures_util::{SinkExt, StreamExt};
use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};
#[cfg(test)]
use tokio_tungstenite::tungstenite::protocol::Message as TungsteniteMessage;
#[cfg(test)]
use tokio_tungstenite::{connect_async, tungstenite::client::IntoClientRequest};

use agistack_adapters_postgres::{PgProjectSandboxRepository, ProjectReadRecord};
use agistack_core::ports::{
    ContainerRuntime, ContainerState, ContainerStatus, PortBinding, ToolHost,
};

use crate::auth::{Identity, RawApiKey};
use crate::AppState;

mod handlers;
mod http_proxy;
mod http_registry;
mod service_http;
mod service_lifecycle;
mod service_state;
mod views;
mod ws_proxy;
mod ws_urls;

use handlers::*;
pub(crate) use http_proxy::preview_host_proxy;
#[cfg(test)]
use http_proxy::{
    proxy_http_service_preview_host_response, proxy_http_service_preview_host_ws_response,
};
use http_proxy::{
    proxy_http_service_response, proxy_project_desktop_response, HttpServiceProxyResponseInput,
};
pub(crate) use http_registry::{in_memory_http_service_registry, SharedHttpServiceRegistry};
pub(crate) use service_state::PgProjectSandboxConfigSource;
use service_state::{
    InMemorySandboxRegistry, PgSandboxRegistry, ProjectSandboxConfig, ProjectSandboxConfigSource,
    SandboxRecord, SandboxRegistry, SandboxToolConnector, WsMcpToolConnector,
};

use ws_urls::{
    append_mcp_upstream_token, build_desktop_websocket_target, build_mcp_websocket_target,
    build_terminal_websocket_target, build_upstream_preview_ws_url, build_upstream_ws_url,
    desktop_websocket_origin, normalize_mcp_resource_mime_type, terminal_websocket_origin,
};

pub(crate) use views::ExecuteToolResponse;
use views::{
    DesktopServiceResponse, EnsureSandboxRequest, ExecuteToolRequest, HealthCheckResponse,
    HttpServiceActionResponse, HttpServicePreviewSessionResponse, HttpServiceResponse,
    ListHttpServicesResponse, ListProjectSandboxesQuery, ListProjectSandboxesResponse,
    ProjectSandboxResponse, SandboxActionResponse, SandboxProxyAuthCookieResponse,
    SandboxServiceStopResponse, SandboxStatsResponse, StartDesktopQuery, TerminalServiceResponse,
    TerminalWsQuery,
};
use ws_proxy::{
    new_terminal_session_id, proxy_desktop_ws_session, proxy_http_service_ws_session,
    proxy_mcp_ws_session, proxy_terminal_ws_session, terminal_error_message, TerminalSessionRecord,
    TerminalSessionRecorder, TerminalSize,
};

const SANDBOX_NOT_FOUND: &str = "Sandbox not found";
const SANDBOX_NOT_FOUND_WITH_CREATE_HINT: &str = "Sandbox not found. Use POST to create one.";
const DESKTOP_SERVICE_NOT_RUNNING: &str = "Desktop service is not running";
const TERMINAL_SERVICE_NOT_RUNNING: &str = "Terminal service is not running";
const MCP_SERVICE_NOT_RUNNING: &str = "MCP service is not running";
const MCP_APP_MIME_TYPE: &str = "text/html;profile=mcp-app";
const SANDBOX_PROXY_TOKEN_COOKIE_NAME: &str = "sandbox_proxy_token";
const SANDBOX_PROXY_AUTH_COOKIE_MAX_AGE_SECONDS: i64 = 3_600;
const PREVIEW_SESSION_QUERY_PARAM: &str = "ms_preview_session";
const PREVIEW_SESSION_COOKIE_NAME: &str = "memstack_preview_session";
const PROXY_TOKEN_QUERY_PARAM: &str = "token";
const MCP_UPSTREAM_TOKEN_QUERY_PARAM: &str = "token";
const PREVIEW_HOST_SUFFIX_ENV: &str = "WORKSPACE_HTTP_PREVIEW_HOST_SUFFIX";
const PREVIEW_SCHEME_ENV: &str = "WORKSPACE_HTTP_PREVIEW_SCHEME";
const PREVIEW_SESSION_TTL_ENV: &str = "WORKSPACE_HTTP_PREVIEW_SESSION_TTL_SECONDS";
const TERMINAL_SESSION_TTL_ENV: &str = "WORKSPACE_TERMINAL_SESSION_TTL_SECONDS";
const MCP_UPSTREAM_TOKEN_TTL_ENV: &str = "WORKSPACE_MCP_TOKEN_TTL_SECONDS";
const HTTP_PROXY_BODY_LIMIT_BYTES: usize = 16 * 1024 * 1024;
const DESKTOP_TOKEN_COOKIE_NAME: &str = "desktop_token";
const DESKTOP_TOKEN_COOKIE_MAX_AGE_SECONDS: i64 = 86_400;
const MCP_CONTAINER_PORT: u16 = 8_765;
const DESKTOP_CONTAINER_PORT: u16 = 6_080;
const TERMINAL_CONTAINER_PORT: u16 = 7_681;
const DESKTOP_DEFAULT_DISPLAY: &str = ":1";
const DESKTOP_DEFAULT_RESOLUTION: &str = "1920x1080";
const DESKTOP_DEFAULT_ENCODING: &str = "webp";
const WEBSOCKET_AUTH_SUBPROTOCOL: &str = "memstack.auth";
const DESKTOP_WEBSOCKET_SUBPROTOCOL: &str = "binary";
const TTYD_INPUT_COMMAND: u8 = b'0';
const TTYD_RESIZE_COMMAND: u8 = b'1';
const TTYD_PREFERENCES_COMMAND: u8 = b'2';
const TERMINAL_DEFAULT_COLS: u16 = 80;
const TERMINAL_DEFAULT_ROWS: u16 = 24;
const PROJECT_LABEL: &str = "agistack.project_id";
const TENANT_LABEL: &str = "agistack.tenant_id";
const KIND_LABEL: &str = "agistack.sandbox_kind";
const KIND_PROJECT: &str = "project";

#[derive(Debug)]
pub(crate) struct SandboxApiError {
    status: StatusCode,
    detail: String,
}

impl SandboxApiError {
    fn new(status: StatusCode, detail: impl Into<String>) -> Self {
        Self {
            status,
            detail: detail.into(),
        }
    }

    fn bad_request(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::BAD_REQUEST, detail)
    }

    fn forbidden(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::FORBIDDEN, detail)
    }

    fn not_found(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::NOT_FOUND, detail)
    }

    fn bad_gateway(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::BAD_GATEWAY, detail)
    }

    fn internal(detail: impl std::fmt::Display) -> Self {
        Self::new(StatusCode::INTERNAL_SERVER_ERROR, detail.to_string())
    }
}

impl IntoResponse for SandboxApiError {
    fn into_response(self) -> Response {
        (self.status, Json(json!({ "detail": self.detail }))).into_response()
    }
}

pub(crate) type SandboxApiResult<T> = Result<T, SandboxApiError>;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum SandboxProfile {
    Lite,
    Standard,
    Full,
}

impl SandboxProfile {
    fn parse(raw: Option<&str>) -> SandboxApiResult<Option<Self>> {
        match raw {
            None => Ok(None),
            Some(value) => match value.to_ascii_lowercase().as_str() {
                "lite" => Ok(Some(Self::Lite)),
                "standard" => Ok(Some(Self::Standard)),
                "full" => Ok(Some(Self::Full)),
                _ => Err(SandboxApiError::bad_request("Invalid sandbox profile")),
            },
        }
    }

    fn as_str(self) -> &'static str {
        match self {
            Self::Lite => "lite",
            Self::Standard => "standard",
            Self::Full => "full",
        }
    }
}

fn parse_status_filter(raw: Option<&str>) -> SandboxApiResult<Option<String>> {
    let Some(raw) = raw else {
        return Ok(None);
    };
    let status = raw.to_ascii_lowercase();
    match status.as_str() {
        "starting" | "running" | "error" | "terminated" | "pending" | "creating" | "unhealthy"
        | "stopped" | "connecting" | "disconnected" | "orphan" => Ok(Some(status)),
        _ => Err(SandboxApiError::bad_request("Invalid sandbox status")),
    }
}

/// Project sandbox lifecycle service over the shared `ContainerRuntime` port.
/// The registry is in-memory for offline dev/tests and Postgres-backed in
/// production so Python and Rust share the same durable `project_sandboxes`
/// association table during strangler rollout.
pub(crate) struct ProjectSandboxService {
    runtime: Arc<dyn ContainerRuntime>,
    tool_host: Option<Arc<dyn ToolHost>>,
    tool_connector: Option<Arc<dyn SandboxToolConnector>>,
    image: String,
    registry: Arc<dyn SandboxRegistry>,
    http_registry: SharedHttpServiceRegistry,
    config_source: Option<Arc<dyn ProjectSandboxConfigSource>>,
}

pub(crate) type SharedProjectSandboxes = Arc<ProjectSandboxService>;

#[derive(Debug, Clone)]
struct ProjectSandboxInfo {
    sandbox_id: String,
    project_id: String,
    tenant_id: String,
    sandbox_type: String,
    profile: SandboxProfile,
    state: ContainerState,
    exit_code: Option<i64>,
    created_at_ms: i64,
    started_at_ms: Option<i64>,
    last_accessed_at_ms: i64,
    metadata_json: Value,
    local_config: Value,
    endpoint: Option<String>,
    websocket_url: Option<String>,
    mcp_port: Option<u16>,
    desktop_port: Option<u16>,
    terminal_port: Option<u16>,
    desktop_url: Option<String>,
    terminal_url: Option<String>,
}

impl ProjectSandboxInfo {
    fn from_record(mut record: SandboxRecord, status: ContainerStatus) -> Self {
        record.apply_runtime_ports(&status.ports);
        let endpoint = record.endpoint();
        let websocket_url = record.websocket_url();
        let mcp_port = record.mcp_port();
        let desktop_port = record.desktop_port();
        let terminal_port = record.terminal_port();
        let desktop_url = record.desktop_url();
        let terminal_url = record.terminal_url();
        Self {
            sandbox_id: record.sandbox_id,
            project_id: record.project_id,
            tenant_id: record.tenant_id,
            sandbox_type: record.sandbox_type,
            profile: record.profile,
            state: status.state,
            exit_code: status.exit_code,
            created_at_ms: record.created_at_ms,
            started_at_ms: record.started_at_ms,
            last_accessed_at_ms: record.last_accessed_at_ms,
            metadata_json: record.metadata_json,
            local_config: record.local_config,
            endpoint,
            websocket_url,
            mcp_port,
            desktop_port,
            terminal_port,
            desktop_url,
            terminal_url,
        }
    }

    fn to_record(&self) -> SandboxRecord {
        SandboxRecord {
            association_id: format!("agistack_sandbox_{}", self.project_id),
            sandbox_id: self.sandbox_id.clone(),
            project_id: self.project_id.clone(),
            tenant_id: self.tenant_id.clone(),
            sandbox_type: self.sandbox_type.clone(),
            profile: self.profile,
            status: self.status_str().to_string(),
            created_at_ms: self.created_at_ms,
            started_at_ms: self.started_at_ms,
            last_accessed_at_ms: self.last_accessed_at_ms,
            metadata_json: self.metadata_json.clone(),
            local_config: self.local_config.clone(),
        }
    }

    fn status_str(&self) -> &'static str {
        match self.state {
            ContainerState::Created => "creating",
            ContainerState::Running => "running",
            ContainerState::Exited => "stopped",
            ContainerState::Unknown => "error",
        }
    }

    fn healthy(&self) -> bool {
        matches!(self.state, ContainerState::Running)
    }

    fn is_local(&self) -> bool {
        self.sandbox_type.eq_ignore_ascii_case("local")
    }

    fn error_message(&self) -> Option<String> {
        match self.state {
            ContainerState::Unknown => Some("Sandbox status is unknown".to_string()),
            ContainerState::Exited if self.exit_code.unwrap_or(0) != 0 => Some(format!(
                "Sandbox exited with code {}",
                self.exit_code.unwrap_or(-1)
            )),
            _ => None,
        }
    }
}

#[derive(Debug, Clone, Copy, Default, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
enum HttpServiceSourceType {
    #[default]
    SandboxInternal,
    ExternalUrl,
}

#[derive(Debug, Deserialize)]
struct RegisterHttpServiceRequest {
    service_id: Option<String>,
    name: String,
    #[serde(default)]
    source_type: HttpServiceSourceType,
    internal_port: Option<u16>,
    #[serde(default = "default_internal_scheme")]
    internal_scheme: String,
    #[serde(default = "default_path_prefix")]
    path_prefix: String,
    external_url: Option<String>,
    #[serde(default = "default_auto_open")]
    auto_open: bool,
}

fn default_internal_scheme() -> String {
    "http".to_string()
}

fn default_path_prefix() -> String {
    "/".to_string()
}

fn default_auto_open() -> bool {
    true
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct HttpServiceProxyInfo {
    service_id: String,
    name: String,
    source_type: HttpServiceSourceType,
    status: String,
    service_url: String,
    preview_url: String,
    ws_preview_url: Option<String>,
    sandbox_id: Option<String>,
    auto_open: bool,
    restart_token: Option<String>,
    updated_at: String,
}

#[derive(Debug, Clone)]
pub(crate) struct PreviewSessionRecord {
    project_id: String,
    service_id: String,
    expires_at_ms: i64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct McpUpstreamTokenRecord {
    token: String,
    project_id: String,
    sandbox_id: String,
    issued_at_ms: i64,
    expires_at_ms: i64,
}

impl McpUpstreamTokenRecord {
    fn new(project_id: String, sandbox_id: String, now_ms: i64, ttl_seconds: i64) -> Self {
        Self {
            token: agistack_adapters_secrets::generate_urlsafe_token(32),
            project_id,
            sandbox_id,
            issued_at_ms: now_ms,
            expires_at_ms: now_ms + ttl_seconds.max(1) * 1000,
        }
    }
}

fn http_service_source_type_wire(source_type: HttpServiceSourceType) -> &'static str {
    match source_type {
        HttpServiceSourceType::SandboxInternal => "sandbox_internal",
        HttpServiceSourceType::ExternalUrl => "external_url",
    }
}

fn parse_http_service_source_type(raw: &str) -> SandboxApiResult<HttpServiceSourceType> {
    match raw {
        "sandbox_internal" => Ok(HttpServiceSourceType::SandboxInternal),
        "external_url" => Ok(HttpServiceSourceType::ExternalUrl),
        _ => Err(SandboxApiError::internal(
            "Invalid stored HTTP service source_type",
        )),
    }
}

fn redis_service_record_from_info(
    info: &HttpServiceProxyInfo,
) -> agistack_adapters_redis::SandboxHttpServiceRecord {
    agistack_adapters_redis::SandboxHttpServiceRecord {
        service_id: info.service_id.clone(),
        name: info.name.clone(),
        source_type: http_service_source_type_wire(info.source_type).to_string(),
        status: info.status.clone(),
        service_url: info.service_url.clone(),
        preview_url: info.preview_url.clone(),
        ws_preview_url: info.ws_preview_url.clone(),
        sandbox_id: info.sandbox_id.clone(),
        auto_open: info.auto_open,
        restart_token: info.restart_token.clone(),
        updated_at: info.updated_at.clone(),
    }
}

fn info_from_redis_service_record(
    record: agistack_adapters_redis::SandboxHttpServiceRecord,
) -> SandboxApiResult<HttpServiceProxyInfo> {
    Ok(HttpServiceProxyInfo {
        service_id: record.service_id,
        name: record.name,
        source_type: parse_http_service_source_type(&record.source_type)?,
        status: record.status,
        service_url: record.service_url,
        preview_url: record.preview_url,
        ws_preview_url: record.ws_preview_url,
        sandbox_id: record.sandbox_id,
        auto_open: record.auto_open,
        restart_token: record.restart_token,
        updated_at: record.updated_at,
    })
}

fn rfc3339(ms: i64) -> String {
    chrono::DateTime::<chrono::Utc>::from_timestamp_millis(ms)
        .unwrap_or(chrono::DateTime::<chrono::Utc>::UNIX_EPOCH)
        .to_rfc3339_opts(chrono::SecondsFormat::Secs, true)
}

fn now_ms() -> i64 {
    chrono::Utc::now().timestamp_millis()
}

fn terminal_session_storage_key(project_id: &str, session_id: &str) -> String {
    format!("{project_id}:{session_id}")
}

fn sandbox_public_host() -> String {
    std::env::var("AGISTACK_SANDBOX_PUBLIC_HOST")
        .ok()
        .map(|host| host.trim().to_string())
        .filter(|host| !host.is_empty())
        .unwrap_or_else(|| "localhost".to_string())
}

fn sandbox_port_bindings() -> Vec<PortBinding> {
    let host_ip = Some(
        std::env::var("AGISTACK_SANDBOX_BIND_HOST")
            .ok()
            .map(|host| host.trim().to_string())
            .filter(|host| !host.is_empty())
            .unwrap_or_else(|| "127.0.0.1".to_string()),
    );
    [
        MCP_CONTAINER_PORT,
        DESKTOP_CONTAINER_PORT,
        TERMINAL_CONTAINER_PORT,
    ]
    .into_iter()
    .map(|container_port| PortBinding {
        container_port,
        host_port: 0,
        host_ip: host_ip.clone(),
    })
    .collect()
}

fn proxy_auth_cookie_secure(headers: &HeaderMap) -> bool {
    headers
        .get("x-forwarded-proto")
        .and_then(|value| value.to_str().ok())
        .map(|value| {
            value
                .split(',')
                .next()
                .map(str::trim)
                .is_some_and(|proto| proto.eq_ignore_ascii_case("https"))
        })
        .unwrap_or(false)
        || headers
            .get("forwarded")
            .and_then(|value| value.to_str().ok())
            .map(|value| {
                value
                    .split(';')
                    .map(str::trim)
                    .any(|part| part.eq_ignore_ascii_case("proto=https"))
            })
            .unwrap_or(false)
}

fn sandbox_proxy_auth_cookie(
    project_id: &str,
    api_key: &str,
    secure: bool,
) -> SandboxApiResult<HeaderValue> {
    let mut cookie = format!(
        "{SANDBOX_PROXY_TOKEN_COOKIE_NAME}={api_key}; HttpOnly; SameSite=Strict; Max-Age={SANDBOX_PROXY_AUTH_COOKIE_MAX_AGE_SECONDS}; Path=/api/v1/projects/{project_id}/sandbox"
    );
    if secure {
        cookie.push_str("; Secure");
    }
    HeaderValue::from_str(&cookie)
        .map_err(|_| SandboxApiError::internal("Failed to set sandbox proxy auth cookie"))
}

fn desktop_token_cookie(
    project_id: &str,
    service_id: &str,
    api_key: &str,
) -> SandboxApiResult<HeaderValue> {
    let cookie = format!(
        "{DESKTOP_TOKEN_COOKIE_NAME}={api_key}; HttpOnly; SameSite=Strict; Max-Age={DESKTOP_TOKEN_COOKIE_MAX_AGE_SECONDS}; Path=/api/v1/projects/{project_id}/sandbox/http-services/{service_id}/proxy"
    );
    HeaderValue::from_str(&cookie)
        .map_err(|_| SandboxApiError::internal("Failed to set sandbox proxy auth cookie"))
}

fn desktop_proxy_token_cookie(project_id: &str, api_key: &str) -> SandboxApiResult<HeaderValue> {
    let cookie = format!(
        "{DESKTOP_TOKEN_COOKIE_NAME}={api_key}; HttpOnly; SameSite=Strict; Max-Age={DESKTOP_TOKEN_COOKIE_MAX_AGE_SECONDS}; Path=/api/v1/projects/{project_id}/sandbox/desktop/proxy"
    );
    HeaderValue::from_str(&cookie)
        .map_err(|_| SandboxApiError::internal("Failed to set sandbox proxy auth cookie"))
}

fn filter_proxy_headers(headers: &HeaderMap) -> HeaderMap {
    const BLOCKED: &[&str] = &[
        "host",
        "content-length",
        "connection",
        "authorization",
        "accept-encoding",
        "cookie",
        "proxy-authorization",
        "x-forwarded-for",
        "x-forwarded-proto",
    ];

    let mut out = HeaderMap::new();
    for (name, value) in headers {
        if BLOCKED
            .iter()
            .any(|blocked| name.as_str().eq_ignore_ascii_case(blocked))
        {
            continue;
        }
        out.append(name.clone(), value.clone());
    }
    out
}

fn filter_desktop_proxy_headers(headers: &HeaderMap) -> HeaderMap {
    let mut out = HeaderMap::new();
    for name in [ACCEPT, ACCEPT_ENCODING, ACCEPT_LANGUAGE, CACHE_CONTROL] {
        if let Some(value) = headers.get(&name) {
            out.insert(name, value.clone());
        }
    }
    out
}

fn filter_proxy_query(raw_query: Option<&str>) -> Option<String> {
    let raw_query = raw_query?;
    let mut serializer = url::form_urlencoded::Serializer::new(String::new());
    for (key, value) in url::form_urlencoded::parse(raw_query.as_bytes()) {
        if key != "token" {
            serializer.append_pair(&key, &value);
        }
    }
    let query = serializer.finish();
    if query.is_empty() {
        None
    } else {
        Some(query)
    }
}

fn filter_preview_host_query(raw_query: Option<&str>) -> Option<String> {
    let raw_query = raw_query?;
    let mut serializer = url::form_urlencoded::Serializer::new(String::new());
    for (key, value) in url::form_urlencoded::parse(raw_query.as_bytes()) {
        if key != PREVIEW_SESSION_QUERY_PARAM {
            serializer.append_pair(&key, &value);
        }
    }
    let query = serializer.finish();
    if query.is_empty() {
        None
    } else {
        Some(query)
    }
}

fn build_upstream_http_url(
    base_url: &str,
    path: &str,
    raw_query: Option<&str>,
) -> SandboxApiResult<String> {
    let mut url = url::Url::parse(base_url)
        .map_err(|_| SandboxApiError::bad_request("Invalid HTTP service URL"))?;
    let base_path = url.path().trim_end_matches('/');
    let extra_path = path.trim_start_matches('/');
    let final_path = match (
        base_path.is_empty() || base_path == "/",
        extra_path.is_empty(),
    ) {
        (true, true) => "/".to_string(),
        (true, false) => format!("/{extra_path}"),
        (false, true) => base_path.to_string(),
        (false, false) => format!("{base_path}/{extra_path}"),
    };
    url.set_path(&final_path);
    url.set_query(filter_proxy_query(raw_query).as_deref());
    Ok(url.to_string())
}

fn build_upstream_preview_http_url(
    base_url: &str,
    path: &str,
    raw_query: Option<&str>,
) -> SandboxApiResult<String> {
    let mut url = url::Url::parse(base_url)
        .map_err(|_| SandboxApiError::bad_request("Invalid HTTP service URL"))?;
    let base_path = url.path().trim_end_matches('/');
    let extra_path = path.trim_start_matches('/');
    let final_path = match (
        base_path.is_empty() || base_path == "/",
        extra_path.is_empty(),
    ) {
        (true, true) => "/".to_string(),
        (true, false) => format!("/{extra_path}"),
        (false, true) => base_path.to_string(),
        (false, false) => format!("{base_path}/{extra_path}"),
    };
    url.set_path(&final_path);
    url.set_query(filter_preview_host_query(raw_query).as_deref());
    Ok(url.to_string())
}

fn normalize_desktop_upstream_base(desktop_url: &str) -> String {
    desktop_url
        .strip_prefix("http://")
        .map(|rest| format!("https://{rest}"))
        .unwrap_or_else(|| desktop_url.to_string())
}

fn build_upstream_desktop_http_url(
    desktop_url: &str,
    path: &str,
    raw_query: Option<&str>,
) -> SandboxApiResult<String> {
    let desktop_base = normalize_desktop_upstream_base(desktop_url);
    let mut url = url::Url::parse(&desktop_base)
        .map_err(|_| SandboxApiError::bad_request("Invalid desktop service URL"))?;
    let base_path = url.path().trim_end_matches('/');
    let extra_path = path.trim_start_matches('/');
    let final_path = match (
        base_path.is_empty() || base_path == "/",
        extra_path.is_empty(),
    ) {
        (true, true) => "/".to_string(),
        (true, false) => format!("/{extra_path}"),
        (false, true) => base_path.to_string(),
        (false, false) => format!("{base_path}/{extra_path}"),
    };
    url.set_path(&final_path);
    url.set_query(filter_proxy_query(raw_query).as_deref());
    Ok(url.to_string())
}

fn build_http_path_preview_proxy_url(project_id: &str, service_id: &str) -> String {
    format!("/api/v1/projects/{project_id}/sandbox/http-services/{service_id}/proxy/")
}

fn build_http_path_preview_ws_proxy_url(project_id: &str, service_id: &str) -> String {
    format!("/api/v1/projects/{project_id}/sandbox/http-services/{service_id}/proxy/ws/")
}

fn should_rewrite_http_service_content(content_type: &str) -> bool {
    let content_type = content_type.to_ascii_lowercase();
    content_type.starts_with("text/html")
        || content_type.starts_with("application/javascript")
        || content_type.starts_with("text/javascript")
        || content_type.starts_with("text/css")
}

fn rewrite_http_service_content(
    content: &[u8],
    content_type: &str,
    project_id: &str,
    service_id: &str,
    token_param: &str,
) -> Vec<u8> {
    if !should_rewrite_http_service_content(content_type) {
        return content.to_vec();
    }

    let proxy_prefix = build_http_path_preview_proxy_url(project_id, service_id);
    let ws_proxy_prefix = build_http_path_preview_ws_proxy_url(project_id, service_id);
    let mut content = String::from_utf8_lossy(content).into_owned();

    let attr_re = regex::Regex::new(r#"(href|src|action)=(["'])/([^/"'][^"']*)"#)
        .expect("BUG: static http service attribute rewrite regex must compile");
    content = attr_re
        .replace_all(&content, |caps: &regex::Captures<'_>| {
            let proxied = append_proxy_token(&format!("{}{}", proxy_prefix, &caps[3]), token_param);
            format!("{}={}{}", &caps[1], &caps[2], proxied)
        })
        .into_owned();

    let url_re = regex::Regex::new(r#"url\((['"]?)/([^/'")][^)'"]*)['"]?\)"#)
        .expect("BUG: static http service url() rewrite regex must compile");
    content = url_re
        .replace_all(&content, |caps: &regex::Captures<'_>| {
            let quote = caps.get(1).map(|m| m.as_str()).unwrap_or_default();
            let proxied = append_proxy_token(&format!("{}{}", proxy_prefix, &caps[2]), token_param);
            format!("url({quote}{proxied}{quote})")
        })
        .into_owned();

    let browser_call_re = regex::Regex::new(r#"\b(fetch|EventSource)\((['"])/([^/'"][^'"]*)"#)
        .expect("BUG: static http service browser call rewrite regex must compile");
    content = browser_call_re
        .replace_all(&content, |caps: &regex::Captures<'_>| {
            let proxied = append_proxy_token(&format!("{}{}", proxy_prefix, &caps[3]), token_param);
            format!("{}({}{proxied}", &caps[1], &caps[2])
        })
        .into_owned();

    content = content.replace(
        "ws://\" + location.host + \"/",
        &format!("ws://\" + location.host + \"{ws_proxy_prefix}"),
    );
    content = content.replace(
        "wss://\" + location.host + \"/",
        &format!("wss://\" + location.host + \"{ws_proxy_prefix}"),
    );

    let websocket_re = regex::Regex::new(r#"new WebSocket\((['"])/([^/'"][^'"]*)"#)
        .expect("BUG: static http service websocket rewrite regex must compile");
    content = websocket_re
        .replace_all(&content, |caps: &regex::Captures<'_>| {
            let proxied =
                append_proxy_token(&format!("{}{}", ws_proxy_prefix, &caps[2]), token_param);
            format!("new WebSocket({}{proxied}", &caps[1])
        })
        .into_owned();

    content.into_bytes()
}

fn build_desktop_path_proxy_url(project_id: &str) -> String {
    format!("/api/v1/projects/{project_id}/sandbox/desktop/proxy/")
}

fn build_desktop_websockify_proxy_url(project_id: &str) -> String {
    format!("/api/v1/projects/{project_id}/sandbox/desktop/proxy/websockify")
}

fn should_rewrite_desktop_content(content_type: &str) -> bool {
    let content_type = content_type.to_ascii_lowercase();
    content_type.starts_with("text/html") || content_type.starts_with("application/javascript")
}

fn rewrite_desktop_content(
    content: &[u8],
    content_type: &str,
    project_id: &str,
    token_param: &str,
) -> Vec<u8> {
    if !should_rewrite_desktop_content(content_type) {
        return content.to_vec();
    }

    let proxy_prefix = build_desktop_path_proxy_url(project_id);
    let mut content = String::from_utf8_lossy(content).into_owned();
    let attr_re = regex::Regex::new(r#"(href|src)=(["'])/([^"']*)"#)
        .expect("BUG: static desktop attribute rewrite regex must compile");
    content = attr_re
        .replace_all(&content, |caps: &regex::Captures<'_>| {
            let proxied = append_proxy_token(&format!("{}{}", proxy_prefix, &caps[3]), token_param);
            format!("{}={}{}", &caps[1], &caps[2], proxied)
        })
        .into_owned();

    let mut ws_proxy_url = build_desktop_websockify_proxy_url(project_id);
    ws_proxy_url = append_proxy_token(&ws_proxy_url, token_param);
    content = content.replace(
        "ws://\" + location.host + \"/",
        &format!("ws://\" + location.host + \"{ws_proxy_url}"),
    );
    content = content.replace(
        "wss://\" + location.host + \"/",
        &format!("wss://\" + location.host + \"{ws_proxy_url}"),
    );

    content.into_bytes()
}

fn url_authority(url: &url::Url) -> Option<String> {
    Some(match url.port() {
        Some(port) => format!("{}:{port}", url.host_str()?),
        None => url.host_str()?.to_string(),
    })
}

fn rewrite_http_service_location(
    location: &str,
    project_id: &str,
    service_id: &str,
    token_param: &str,
    upstream_base_url: &str,
) -> String {
    if location.is_empty() {
        return location.to_string();
    }

    let proxy_prefix = build_http_path_preview_proxy_url(project_id, service_id);
    if let Ok(parsed_location) = url::Url::parse(location) {
        let Ok(upstream) = url::Url::parse(upstream_base_url) else {
            return location.to_string();
        };
        if url_authority(&parsed_location) != url_authority(&upstream) {
            return location.to_string();
        }
        let mut target = format!(
            "{}{}",
            proxy_prefix,
            parsed_location.path().trim_start_matches('/')
        );
        if let Some(query) = parsed_location.query() {
            target.push('?');
            target.push_str(query);
        }
        return append_proxy_token(&target, token_param);
    }

    if location.starts_with("//") {
        return location.to_string();
    }
    if location.starts_with('/') {
        return append_proxy_token(
            &format!("{}{}", proxy_prefix, location.trim_start_matches('/')),
            token_param,
        );
    }
    append_proxy_token(&format!("{proxy_prefix}{location}"), token_param)
}

fn datetime_from_ms(ms: i64) -> chrono::DateTime<chrono::Utc> {
    chrono::DateTime::<chrono::Utc>::from_timestamp_millis(ms)
        .unwrap_or(chrono::DateTime::<chrono::Utc>::UNIX_EPOCH)
}

fn profile_from_metadata(metadata: &serde_json::Value) -> SandboxProfile {
    metadata
        .get("profile")
        .and_then(serde_json::Value::as_str)
        .and_then(|raw| SandboxProfile::parse(Some(raw)).ok().flatten())
        .unwrap_or(SandboxProfile::Standard)
}

fn normalize_sandbox_type(raw: &str) -> String {
    match raw.trim().to_ascii_lowercase().as_str() {
        "local" => "local".to_string(),
        _ => "cloud".to_string(),
    }
}

fn project_sandbox_config_from_record(record: ProjectReadRecord) -> ProjectSandboxConfig {
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

fn initial_metadata(profile: SandboxProfile) -> Value {
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

fn local_metadata(profile: SandboxProfile, local_config: &Value) -> Value {
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

fn string_field(value: &Value, key: &str) -> Option<String> {
    value
        .get(key)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
}

fn port_field(value: &Value, key: &str) -> Option<u16> {
    value.get(key).and_then(|value| {
        value
            .as_u64()
            .and_then(|port| u16::try_from(port).ok())
            .or_else(|| value.as_str()?.trim().parse::<u16>().ok())
    })
}

fn normalize_local_config(raw: Value) -> Value {
    let raw = match raw {
        Value::Object(map) => Value::Object(map),
        _ => json!({}),
    };
    let mut map = match raw {
        Value::Object(map) => map,
        _ => unreachable!("raw normalized to object"),
    };
    map.entry("workspace_path".to_string())
        .or_insert_with(|| Value::String("/workspace".to_string()));
    map.entry("host".to_string())
        .or_insert_with(|| Value::String("localhost".to_string()));
    map.entry("port".to_string())
        .or_insert_with(|| Value::from(8_765));
    Value::Object(map)
}

fn local_config_websocket_url(local_config: &Value) -> Option<String> {
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

fn append_local_auth_token(url: &str, token: &str) -> String {
    if token.is_empty() || url.contains(&format!("{MCP_UPSTREAM_TOKEN_QUERY_PARAM}=")) {
        return url.to_string();
    }
    append_query_param(url, MCP_UPSTREAM_TOKEN_QUERY_PARAM, token)
}

fn connection_url(metadata: &Value, local_config: &Value) -> Option<String> {
    string_field(metadata, "endpoint")
        .or_else(|| string_field(metadata, "websocket_url"))
        .or_else(|| string_field(metadata, "mcp_url"))
        .or_else(|| local_config_websocket_url(local_config))
}

fn normalize_tool_result(raw: &str, execution_time_ms: i64) -> ExecuteToolResponse {
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

fn validate_http_service_name(name: &str) -> SandboxApiResult<()> {
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

fn normalize_http_service_id(service_id: Option<&str>) -> SandboxApiResult<String> {
    let Some(service_id) = service_id else {
        let uuid = agistack_adapters_secrets::generate_uuid_v4();
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

fn normalize_internal_scheme(scheme: &str) -> SandboxApiResult<String> {
    let scheme = scheme.trim().to_ascii_lowercase();
    match scheme.as_str() {
        "http" | "https" => Ok(scheme),
        _ => Err(SandboxApiError::bad_request(
            "internal_scheme must be http or https",
        )),
    }
}

fn normalize_path_prefix(path_prefix: &str) -> String {
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

fn validate_external_http_url(url: &str) -> SandboxApiResult<String> {
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

fn sandbox_internal_service_host(info: &ProjectSandboxInfo) -> String {
    string_field(&info.metadata_json, "container_ip")
        .or_else(|| string_field(&info.local_config, "container_ip"))
        .or_else(|| std::env::var("AGISTACK_SANDBOX_INTERNAL_HOST").ok())
        .map(|host| host.trim().to_string())
        .filter(|host| !host.is_empty())
        .unwrap_or_else(|| "127.0.0.1".to_string())
}

fn preview_public_scheme() -> &'static str {
    match std::env::var(PREVIEW_SCHEME_ENV)
        .ok()
        .map(|scheme| scheme.trim().to_ascii_lowercase())
        .as_deref()
    {
        Some("https") => "https",
        _ => "http",
    }
}

fn preview_host_suffix() -> String {
    let raw = std::env::var(PREVIEW_HOST_SUFFIX_ENV)
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "preview.localhost:8000".to_string());
    raw.strip_prefix("http://")
        .or_else(|| raw.strip_prefix("https://"))
        .unwrap_or(raw.as_str())
        .trim_matches('/')
        .to_string()
}

fn preview_host_suffix_hostname() -> String {
    let suffix = preview_host_suffix();
    url::Url::parse(&format!("http://{suffix}"))
        .ok()
        .and_then(|url| url.host_str().map(|host| host.to_ascii_lowercase()))
        .unwrap_or_else(|| {
            suffix
                .split(':')
                .next()
                .unwrap_or(suffix.as_str())
                .to_ascii_lowercase()
        })
        .trim_matches('.')
        .to_string()
}

fn preview_service_host_label(service_id: &str) -> String {
    let mut label = String::new();
    let mut last_dash = false;
    for ch in service_id.chars().flat_map(char::to_lowercase) {
        let next = if ch.is_ascii_alphanumeric() { ch } else { '-' };
        if next == '-' {
            if !last_dash {
                label.push(next);
                last_dash = true;
            }
        } else {
            label.push(next);
            last_dash = false;
        }
    }
    let label = label.trim_matches('-');
    let label = label.chars().take(63).collect::<String>();
    let label = label.trim_matches('-').to_string();
    if label.is_empty() {
        "service".to_string()
    } else {
        label
    }
}

fn is_preview_host_label(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 63
        && value
            .chars()
            .all(|ch| ch.is_ascii_lowercase() || ch.is_ascii_digit() || ch == '-')
}

fn parse_http_preview_host(host_header: &str) -> Option<(String, String)> {
    let parsed = url::Url::parse(&format!("http://{}", host_header.trim())).ok()?;
    let hostname = parsed.host_str()?.to_ascii_lowercase();
    let hostname = hostname.trim_matches('.');
    let suffix = preview_host_suffix_hostname();
    let expected_tail = format!(".{suffix}");
    if !hostname.ends_with(&expected_tail) {
        return None;
    }
    let preview_prefix = &hostname[..hostname.len() - expected_tail.len()];
    let mut labels = preview_prefix.split('.');
    let service_label = labels.next()?;
    let project_id = labels.next()?;
    if labels.next().is_some()
        || !is_preview_host_label(service_label)
        || !is_preview_host_label(project_id)
    {
        return None;
    }
    Some((project_id.to_string(), service_label.to_string()))
}

fn build_http_preview_proxy_url(project_id: &str, service_id: &str) -> String {
    format!(
        "{}://{}.{}.{}/",
        preview_public_scheme(),
        preview_service_host_label(service_id),
        project_id.to_ascii_lowercase(),
        preview_host_suffix()
    )
}

fn build_http_preview_ws_proxy_url(project_id: &str, service_id: &str) -> String {
    let preview_url = build_http_preview_proxy_url(project_id, service_id);
    if let Some(rest) = preview_url.strip_prefix("https://") {
        format!("wss://{rest}")
    } else if let Some(rest) = preview_url.strip_prefix("http://") {
        format!("ws://{rest}")
    } else {
        preview_url
    }
}

fn preview_session_ttl_seconds() -> i64 {
    std::env::var(PREVIEW_SESSION_TTL_ENV)
        .ok()
        .and_then(|raw| raw.trim().parse::<i64>().ok())
        .map(|ttl| ttl.clamp(60, 7 * 86_400))
        .unwrap_or(86_400)
}

fn terminal_session_ttl_seconds() -> i64 {
    std::env::var(TERMINAL_SESSION_TTL_ENV)
        .ok()
        .and_then(|raw| raw.trim().parse::<i64>().ok())
        .map(|ttl| ttl.clamp(60, 7 * 86_400))
        .unwrap_or(86_400)
}

fn mcp_upstream_token_ttl_seconds() -> i64 {
    std::env::var(MCP_UPSTREAM_TOKEN_TTL_ENV)
        .ok()
        .and_then(|raw| raw.trim().parse::<i64>().ok())
        .map(|ttl| ttl.clamp(60, 86_400))
        .unwrap_or(600)
}

fn append_query_param(url: &str, key: &str, value: &str) -> String {
    let sep = if url.contains('?') { '&' } else { '?' };
    format!("{url}{sep}{key}={value}")
}

fn append_proxy_token(url: &str, token_param: &str) -> String {
    if token_param.is_empty() || url.contains(&format!("{PROXY_TOKEN_QUERY_PARAM}=")) {
        return url.to_string();
    }
    append_query_param(url, PROXY_TOKEN_QUERY_PARAM, token_param)
}

fn proxy_token_from_query(raw_query: Option<&str>) -> String {
    raw_query
        .and_then(|query| {
            url::form_urlencoded::parse(query.as_bytes())
                .find(|(key, _)| key == PROXY_TOKEN_QUERY_PARAM)
                .map(|(_, value)| value.into_owned())
        })
        .unwrap_or_default()
}

fn extract_cookie_value(headers: &HeaderMap, name: &str) -> Option<String> {
    let cookie_header = headers.get("cookie")?.to_str().ok()?;
    cookie_header.split(';').find_map(|part| {
        let (key, value) = part.trim().split_once('=')?;
        (key == name).then(|| value.to_string())
    })
}

fn preview_session_token_from_query(raw_query: Option<&str>) -> Option<String> {
    let raw_query = raw_query?;
    url::form_urlencoded::parse(raw_query.as_bytes())
        .find(|(key, _)| key == PREVIEW_SESSION_QUERY_PARAM)
        .map(|(_, value)| value.into_owned())
}

fn clean_preview_session_path(path: &str, raw_query: Option<&str>) -> String {
    let mut clean = if path.is_empty() {
        "/".to_string()
    } else {
        path.to_string()
    };
    if let Some(query) = filter_preview_host_query(raw_query) {
        clean.push('?');
        clean.push_str(&query);
    }
    clean
}

fn preview_session_cookie(
    token: &str,
    session: &PreviewSessionRecord,
    secure: bool,
) -> SandboxApiResult<HeaderValue> {
    let max_age_seconds = ((session.expires_at_ms - now_ms()) / 1000).max(1);
    let mut cookie = format!(
        "{PREVIEW_SESSION_COOKIE_NAME}={token}; HttpOnly; SameSite=Lax; Max-Age={max_age_seconds}; Path=/"
    );
    if secure {
        cookie.push_str("; Secure");
    }
    HeaderValue::from_str(&cookie)
        .map_err(|_| SandboxApiError::internal("Failed to set preview session cookie"))
}

fn request_scheme_from_headers(headers: &HeaderMap) -> &'static str {
    if proxy_auth_cookie_secure(headers) {
        "https"
    } else {
        "http"
    }
}

fn request_origin_from_headers(headers: &HeaderMap, fallback_origin: &str) -> String {
    headers
        .get("origin")
        .and_then(|value| value.to_str().ok())
        .map(str::trim)
        .filter(|origin| !origin.is_empty())
        .map(str::to_string)
        .unwrap_or_else(|| fallback_origin.to_string())
}

fn rewrite_http_service_host_location(
    location: &str,
    request_scheme: &str,
    request_host: &str,
    upstream_base_url: &str,
) -> String {
    if location.is_empty() {
        return location.to_string();
    }
    let Ok(parsed_location) = url::Url::parse(location) else {
        return location.to_string();
    };
    let Ok(upstream) = url::Url::parse(upstream_base_url) else {
        return location.to_string();
    };
    if url_authority(&parsed_location) != url_authority(&upstream) {
        return location.to_string();
    }
    let mut rewritten = parsed_location;
    let _ = rewritten.set_scheme(request_scheme);
    if let Some((host, port)) = request_host.rsplit_once(':') {
        if let Ok(port) = port.parse::<u16>() {
            let _ = rewritten.set_host(Some(host));
            let _ = rewritten.set_port(Some(port));
            return rewritten.to_string();
        }
    }
    let _ = rewritten.set_host(Some(request_host));
    let _ = rewritten.set_port(None);
    rewritten.to_string()
}

fn python_utc_offset_string(ms: i64) -> String {
    datetime_from_ms(ms).to_rfc3339_opts(chrono::SecondsFormat::Millis, false)
}

fn http_service_not_found() -> SandboxApiError {
    SandboxApiError::not_found("HTTP service not found")
}

fn select_websocket_auth_subprotocol(headers: &HeaderMap) -> Option<&'static str> {
    let protocols = headers
        .get("sec-websocket-protocol")
        .and_then(|value| value.to_str().ok())?;
    protocols
        .split(',')
        .map(str::trim)
        .any(|protocol| protocol == WEBSOCKET_AUTH_SUBPROTOCOL)
        .then_some(WEBSOCKET_AUTH_SUBPROTOCOL)
}

pub(crate) fn router() -> Router<AppState> {
    Router::new()
        .route("/api/v1/projects/sandboxes", get(list_project_sandboxes))
        .route(
            "/api/v1/projects/:project_id/sandbox",
            get(get_project_sandbox),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox",
            post(ensure_project_sandbox),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox",
            delete(terminate_project_sandbox),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/health",
            get(check_project_sandbox_health),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/stats",
            get(get_project_sandbox_stats),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/execute",
            post(execute_project_sandbox_tool),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/proxy-auth-cookie",
            post(seed_project_sandbox_proxy_auth_cookie),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/desktop",
            post(start_project_desktop).delete(stop_project_desktop),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/desktop/proxy",
            get(proxy_project_desktop_root),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/desktop/proxy/websockify",
            get(proxy_project_desktop_websockify),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/desktop/proxy/*path",
            get(proxy_project_desktop_path),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/terminal",
            post(start_project_terminal).delete(stop_project_terminal),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/terminal/proxy/ws",
            get(proxy_project_terminal_websocket),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/mcp/proxy",
            get(proxy_project_mcp_websocket),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/http-services",
            get(list_project_http_services).post(register_project_http_service),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/http-services/:service_id/preview-session",
            post(create_project_http_service_preview_session),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/http-services/:service_id/proxy/ws",
            get(proxy_project_http_service_ws_root),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/http-services/:service_id/proxy/ws/*path",
            get(proxy_project_http_service_ws_path),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/http-services/:service_id/proxy",
            any(proxy_project_http_service_root),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/http-services/:service_id/proxy/*path",
            any(proxy_project_http_service_path),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/http-services/:service_id",
            delete(stop_project_http_service),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/restart",
            post(restart_project_sandbox),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/sync",
            get(sync_project_sandbox_status),
        )
}

#[cfg(test)]
mod tests;
