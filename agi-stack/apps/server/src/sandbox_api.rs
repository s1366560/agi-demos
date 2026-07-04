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
mod proxy_helpers;
mod service_helpers;
mod service_http;
mod service_lifecycle;
mod service_state;
mod views;
mod ws_handlers;
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
use proxy_helpers::*;
use service_helpers::*;
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
use ws_handlers::*;
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
