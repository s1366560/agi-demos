//! P5 project sandbox lifecycle foundation.
//!
//! This module wires the already-portable [`ContainerRuntime`] port into the
//! Rust `/api/v1/projects/{id}/sandbox*` surface without pulling Docker/bollard
//! into `core`. It covers lifecycle, tool execution, desktop/terminal/http
//! proxies, and the browser MCP WebSocket proxy as vertical P5 strangler slices
//! while keeping the heavy runtime concerns server-only.

use std::collections::BTreeMap;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

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

use agistack_adapters_postgres::{
    PgProjectReadRepository, PgProjectSandboxRepository, ProjectReadRecord, ProjectSandboxRecord,
};
use agistack_core::ports::{
    ContainerRuntime, ContainerSpec, ContainerState, ContainerStatus, PortBinding, ToolHost,
};

use crate::auth::{Identity, RawApiKey};
use crate::AppState;

mod http_proxy;
mod ws_proxy;
mod ws_urls;

pub(crate) use http_proxy::preview_host_proxy;
#[cfg(test)]
use http_proxy::{
    proxy_http_service_preview_host_response, proxy_http_service_preview_host_ws_response,
};
use http_proxy::{
    proxy_http_service_response, proxy_project_desktop_response, HttpServiceProxyResponseInput,
};

use ws_urls::{
    append_mcp_upstream_token, build_desktop_websocket_target, build_mcp_websocket_target,
    build_terminal_websocket_target, build_upstream_preview_ws_url, build_upstream_ws_url,
    desktop_websocket_origin, normalize_mcp_resource_mime_type, terminal_websocket_origin,
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

#[derive(Debug, Clone)]
struct SandboxRecord {
    association_id: String,
    sandbox_id: String,
    project_id: String,
    tenant_id: String,
    sandbox_type: String,
    profile: SandboxProfile,
    status: String,
    created_at_ms: i64,
    started_at_ms: Option<i64>,
    last_accessed_at_ms: i64,
    metadata_json: Value,
    local_config: Value,
}

#[derive(Debug, Clone, PartialEq)]
pub(crate) struct ProjectSandboxConfig {
    sandbox_type: String,
    local_config: Value,
}

impl ProjectSandboxConfig {
    fn cloud() -> Self {
        Self {
            sandbox_type: "cloud".to_string(),
            local_config: json!({}),
        }
    }

    fn is_local(&self) -> bool {
        self.sandbox_type.eq_ignore_ascii_case("local")
    }
}

#[async_trait]
pub(crate) trait ProjectSandboxConfigSource: Send + Sync {
    async fn get_project_sandbox_config(
        &self,
        project_id: &str,
    ) -> SandboxApiResult<Option<ProjectSandboxConfig>>;
}

pub(crate) struct PgProjectSandboxConfigSource {
    projects: PgProjectReadRepository,
}

impl PgProjectSandboxConfigSource {
    pub(crate) fn new(projects: PgProjectReadRepository) -> Self {
        Self { projects }
    }
}

#[async_trait]
impl ProjectSandboxConfigSource for PgProjectSandboxConfigSource {
    async fn get_project_sandbox_config(
        &self,
        project_id: &str,
    ) -> SandboxApiResult<Option<ProjectSandboxConfig>> {
        self.projects
            .get_by_id(project_id)
            .await
            .map_err(SandboxApiError::internal)
            .map(|record| record.map(project_sandbox_config_from_record))
    }
}

#[async_trait]
trait SandboxToolConnector: Send + Sync {
    async fn connect_tool_host(&self, url: &str) -> SandboxApiResult<Arc<dyn ToolHost>>;
}

pub(crate) struct WsMcpToolConnector;

#[async_trait]
impl SandboxToolConnector for WsMcpToolConnector {
    async fn connect_tool_host(&self, url: &str) -> SandboxApiResult<Arc<dyn ToolHost>> {
        let host = agistack_adapters_mcp::connect(url)
            .await
            .map_err(|_| SandboxApiError::internal("Execution failed"))?;
        Ok(Arc::new(host))
    }
}

#[async_trait]
trait SandboxRegistry: Send + Sync {
    async fn get(&self, project_id: &str) -> SandboxApiResult<Option<SandboxRecord>>;
    async fn list(
        &self,
        tenant_id: &str,
        status: Option<&str>,
        limit: i64,
        offset: i64,
    ) -> SandboxApiResult<Vec<SandboxRecord>>;
    async fn save(
        &self,
        record: &SandboxRecord,
        status: &str,
        error_message: Option<&str>,
    ) -> SandboxApiResult<()>;
    async fn delete(&self, project_id: &str) -> SandboxApiResult<bool>;
}

pub(crate) type SharedHttpServiceRegistry = Arc<dyn HttpServiceRegistry>;

#[async_trait]
pub(crate) trait HttpServiceRegistry: Send + Sync {
    async fn upsert(
        &self,
        project_id: &str,
        info: HttpServiceProxyInfo,
    ) -> SandboxApiResult<HttpServiceProxyInfo>;
    async fn list(&self, project_id: &str) -> SandboxApiResult<Vec<HttpServiceProxyInfo>>;
    async fn get(
        &self,
        project_id: &str,
        service_id: &str,
    ) -> SandboxApiResult<Option<HttpServiceProxyInfo>>;
    async fn remove(
        &self,
        project_id: &str,
        service_id: &str,
    ) -> SandboxApiResult<Option<HttpServiceProxyInfo>>;
    async fn create_preview_session(
        &self,
        token: &str,
        record: PreviewSessionRecord,
        ttl_seconds: i64,
    ) -> SandboxApiResult<()>;
    async fn get_preview_session(
        &self,
        token: &str,
    ) -> SandboxApiResult<Option<PreviewSessionRecord>>;
    async fn upsert_terminal_session(
        &self,
        record: TerminalSessionRecord,
        ttl_seconds: i64,
    ) -> SandboxApiResult<()>;
    async fn get_terminal_session(
        &self,
        project_id: &str,
        session_id: &str,
    ) -> SandboxApiResult<Option<TerminalSessionRecord>>;
    async fn create_mcp_upstream_token(
        &self,
        record: McpUpstreamTokenRecord,
        ttl_seconds: i64,
    ) -> SandboxApiResult<()>;
}

struct InMemoryHttpServiceRegistry {
    services: Mutex<BTreeMap<String, BTreeMap<String, HttpServiceProxyInfo>>>,
    preview_sessions: Mutex<BTreeMap<String, PreviewSessionRecord>>,
    terminal_sessions: Mutex<BTreeMap<String, TerminalSessionRecord>>,
    mcp_upstream_tokens: Mutex<BTreeMap<String, McpUpstreamTokenRecord>>,
}

impl InMemoryHttpServiceRegistry {
    fn new() -> Self {
        Self {
            services: Mutex::new(BTreeMap::new()),
            preview_sessions: Mutex::new(BTreeMap::new()),
            terminal_sessions: Mutex::new(BTreeMap::new()),
            mcp_upstream_tokens: Mutex::new(BTreeMap::new()),
        }
    }
}

pub(crate) fn in_memory_http_service_registry() -> SharedHttpServiceRegistry {
    Arc::new(InMemoryHttpServiceRegistry::new())
}

#[async_trait]
impl HttpServiceRegistry for InMemoryHttpServiceRegistry {
    async fn upsert(
        &self,
        project_id: &str,
        info: HttpServiceProxyInfo,
    ) -> SandboxApiResult<HttpServiceProxyInfo> {
        let mut services = self
            .services
            .lock()
            .map_err(|_| SandboxApiError::internal("http service registry mutex poisoned"))?;
        services
            .entry(project_id.to_string())
            .or_default()
            .insert(info.service_id.clone(), info.clone());
        Ok(info)
    }

    async fn list(&self, project_id: &str) -> SandboxApiResult<Vec<HttpServiceProxyInfo>> {
        let services = self
            .services
            .lock()
            .map_err(|_| SandboxApiError::internal("http service registry mutex poisoned"))?;
        Ok(services
            .get(project_id)
            .map(|project_services| project_services.values().cloned().collect())
            .unwrap_or_default())
    }

    async fn get(
        &self,
        project_id: &str,
        service_id: &str,
    ) -> SandboxApiResult<Option<HttpServiceProxyInfo>> {
        let services = self
            .services
            .lock()
            .map_err(|_| SandboxApiError::internal("http service registry mutex poisoned"))?;
        Ok(services
            .get(project_id)
            .and_then(|project_services| project_services.get(service_id))
            .cloned())
    }

    async fn remove(
        &self,
        project_id: &str,
        service_id: &str,
    ) -> SandboxApiResult<Option<HttpServiceProxyInfo>> {
        let mut services = self
            .services
            .lock()
            .map_err(|_| SandboxApiError::internal("http service registry mutex poisoned"))?;
        let Some(project_services) = services.get_mut(project_id) else {
            return Ok(None);
        };
        let removed = project_services.remove(service_id);
        if project_services.is_empty() {
            services.remove(project_id);
        }
        Ok(removed)
    }

    async fn create_preview_session(
        &self,
        token: &str,
        record: PreviewSessionRecord,
        _ttl_seconds: i64,
    ) -> SandboxApiResult<()> {
        self.preview_sessions
            .lock()
            .map_err(|_| SandboxApiError::internal("preview session mutex poisoned"))?
            .insert(token.to_string(), record);
        Ok(())
    }

    async fn get_preview_session(
        &self,
        token: &str,
    ) -> SandboxApiResult<Option<PreviewSessionRecord>> {
        let now = now_ms();
        let mut sessions = self
            .preview_sessions
            .lock()
            .map_err(|_| SandboxApiError::internal("preview session mutex poisoned"))?;
        sessions.retain(|_, session| session.expires_at_ms > now);
        Ok(sessions.get(token).cloned())
    }

    async fn upsert_terminal_session(
        &self,
        record: TerminalSessionRecord,
        _ttl_seconds: i64,
    ) -> SandboxApiResult<()> {
        let key = terminal_session_storage_key(&record.project_id, &record.session_id);
        self.terminal_sessions
            .lock()
            .map_err(|_| SandboxApiError::internal("terminal session mutex poisoned"))?
            .insert(key, record);
        Ok(())
    }

    async fn get_terminal_session(
        &self,
        project_id: &str,
        session_id: &str,
    ) -> SandboxApiResult<Option<TerminalSessionRecord>> {
        let now = now_ms();
        let mut sessions = self
            .terminal_sessions
            .lock()
            .map_err(|_| SandboxApiError::internal("terminal session mutex poisoned"))?;
        sessions.retain(|_, session| session.expires_at_ms > now);
        Ok(sessions
            .get(&terminal_session_storage_key(project_id, session_id))
            .cloned())
    }

    async fn create_mcp_upstream_token(
        &self,
        record: McpUpstreamTokenRecord,
        _ttl_seconds: i64,
    ) -> SandboxApiResult<()> {
        let now = now_ms();
        let mut tokens = self
            .mcp_upstream_tokens
            .lock()
            .map_err(|_| SandboxApiError::internal("mcp upstream token mutex poisoned"))?;
        tokens.retain(|_, token| token.expires_at_ms > now);
        tokens.insert(record.token.clone(), record);
        Ok(())
    }
}

#[async_trait]
impl HttpServiceRegistry for agistack_adapters_redis::RedisSandboxHttpRegistry {
    async fn upsert(
        &self,
        project_id: &str,
        info: HttpServiceProxyInfo,
    ) -> SandboxApiResult<HttpServiceProxyInfo> {
        let record = redis_service_record_from_info(&info);
        agistack_adapters_redis::RedisSandboxHttpRegistry::upsert_http_service(
            self, project_id, &record,
        )
        .await
        .map_err(SandboxApiError::internal)?;
        Ok(info)
    }

    async fn list(&self, project_id: &str) -> SandboxApiResult<Vec<HttpServiceProxyInfo>> {
        agistack_adapters_redis::RedisSandboxHttpRegistry::list_http_services(self, project_id)
            .await
            .map_err(SandboxApiError::internal)?
            .into_iter()
            .map(info_from_redis_service_record)
            .collect()
    }

    async fn get(
        &self,
        project_id: &str,
        service_id: &str,
    ) -> SandboxApiResult<Option<HttpServiceProxyInfo>> {
        agistack_adapters_redis::RedisSandboxHttpRegistry::get_http_service(
            self, project_id, service_id,
        )
        .await
        .map_err(SandboxApiError::internal)?
        .map(info_from_redis_service_record)
        .transpose()
    }

    async fn remove(
        &self,
        project_id: &str,
        service_id: &str,
    ) -> SandboxApiResult<Option<HttpServiceProxyInfo>> {
        let existing = self.get(project_id, service_id).await?;
        if existing.is_some() {
            agistack_adapters_redis::RedisSandboxHttpRegistry::remove_http_service(
                self, project_id, service_id,
            )
            .await
            .map_err(SandboxApiError::internal)?;
        }
        Ok(existing)
    }

    async fn create_preview_session(
        &self,
        token: &str,
        record: PreviewSessionRecord,
        ttl_seconds: i64,
    ) -> SandboxApiResult<()> {
        let record = agistack_adapters_redis::SandboxPreviewSessionRecord {
            project_id: record.project_id,
            service_id: record.service_id,
            expires_at_ms: record.expires_at_ms,
        };
        agistack_adapters_redis::RedisSandboxHttpRegistry::create_preview_session(
            self,
            token,
            &record,
            ttl_seconds.max(1) as u64,
        )
        .await
        .map_err(SandboxApiError::internal)
    }

    async fn get_preview_session(
        &self,
        token: &str,
    ) -> SandboxApiResult<Option<PreviewSessionRecord>> {
        let record =
            agistack_adapters_redis::RedisSandboxHttpRegistry::get_preview_session(self, token)
                .await
                .map_err(SandboxApiError::internal)?;
        Ok(record.map(|record| PreviewSessionRecord {
            project_id: record.project_id,
            service_id: record.service_id,
            expires_at_ms: record.expires_at_ms,
        }))
    }

    async fn upsert_terminal_session(
        &self,
        record: TerminalSessionRecord,
        ttl_seconds: i64,
    ) -> SandboxApiResult<()> {
        let record = agistack_adapters_redis::SandboxTerminalSessionRecord {
            project_id: record.project_id,
            session_id: record.session_id,
            cols: record.cols,
            rows: record.rows,
            connected: record.connected,
            last_seen_at_ms: record.last_seen_at_ms,
            expires_at_ms: record.expires_at_ms,
        };
        agistack_adapters_redis::RedisSandboxHttpRegistry::upsert_terminal_session(
            self,
            &record,
            ttl_seconds.max(1) as u64,
        )
        .await
        .map_err(SandboxApiError::internal)
    }

    async fn get_terminal_session(
        &self,
        project_id: &str,
        session_id: &str,
    ) -> SandboxApiResult<Option<TerminalSessionRecord>> {
        let record = agistack_adapters_redis::RedisSandboxHttpRegistry::get_terminal_session(
            self, project_id, session_id,
        )
        .await
        .map_err(SandboxApiError::internal)?;
        Ok(record.map(|record| TerminalSessionRecord {
            project_id: record.project_id,
            session_id: record.session_id,
            cols: record.cols,
            rows: record.rows,
            connected: record.connected,
            last_seen_at_ms: record.last_seen_at_ms,
            expires_at_ms: record.expires_at_ms,
        }))
    }

    async fn create_mcp_upstream_token(
        &self,
        record: McpUpstreamTokenRecord,
        ttl_seconds: i64,
    ) -> SandboxApiResult<()> {
        let record = agistack_adapters_redis::SandboxMcpUpstreamTokenRecord {
            token: record.token,
            project_id: record.project_id,
            sandbox_id: record.sandbox_id,
            issued_at_ms: record.issued_at_ms,
            expires_at_ms: record.expires_at_ms,
        };
        agistack_adapters_redis::RedisSandboxHttpRegistry::create_mcp_upstream_token(
            self,
            &record,
            ttl_seconds.max(1) as u64,
        )
        .await
        .map_err(SandboxApiError::internal)
    }
}

struct InMemorySandboxRegistry {
    records: Mutex<BTreeMap<String, SandboxRecord>>,
}

impl InMemorySandboxRegistry {
    fn new() -> Self {
        Self {
            records: Mutex::new(BTreeMap::new()),
        }
    }
}

#[async_trait]
impl SandboxRegistry for InMemorySandboxRegistry {
    async fn get(&self, project_id: &str) -> SandboxApiResult<Option<SandboxRecord>> {
        Ok(self
            .records
            .lock()
            .map_err(|_| SandboxApiError::internal("sandbox registry mutex poisoned"))?
            .get(project_id)
            .cloned())
    }

    async fn list(
        &self,
        tenant_id: &str,
        status: Option<&str>,
        limit: i64,
        offset: i64,
    ) -> SandboxApiResult<Vec<SandboxRecord>> {
        let rows = self
            .records
            .lock()
            .map_err(|_| SandboxApiError::internal("sandbox registry mutex poisoned"))?
            .values()
            .filter(|record| record.tenant_id == tenant_id)
            .filter(|record| status.map(|s| record.status == s).unwrap_or(true))
            .cloned()
            .collect::<Vec<_>>();
        Ok(rows
            .into_iter()
            .skip(offset.max(0) as usize)
            .take(limit.max(0) as usize)
            .collect())
    }

    async fn save(
        &self,
        record: &SandboxRecord,
        status: &str,
        _error_message: Option<&str>,
    ) -> SandboxApiResult<()> {
        let mut record = record.clone();
        record.status = status.to_string();
        self.records
            .lock()
            .map_err(|_| SandboxApiError::internal("sandbox registry mutex poisoned"))?
            .insert(record.project_id.clone(), record);
        Ok(())
    }

    async fn delete(&self, project_id: &str) -> SandboxApiResult<bool> {
        Ok(self
            .records
            .lock()
            .map_err(|_| SandboxApiError::internal("sandbox registry mutex poisoned"))?
            .remove(project_id)
            .is_some())
    }
}

struct PgSandboxRegistry {
    repo: PgProjectSandboxRepository,
}

impl PgSandboxRegistry {
    fn new(repo: PgProjectSandboxRepository) -> Self {
        Self { repo }
    }
}

#[async_trait]
impl SandboxRegistry for PgSandboxRegistry {
    async fn get(&self, project_id: &str) -> SandboxApiResult<Option<SandboxRecord>> {
        self.repo
            .find_by_project(project_id)
            .await
            .map_err(SandboxApiError::internal)?
            .map(SandboxRecord::from_pg_record)
            .transpose()
    }

    async fn list(
        &self,
        tenant_id: &str,
        status: Option<&str>,
        limit: i64,
        offset: i64,
    ) -> SandboxApiResult<Vec<SandboxRecord>> {
        self.repo
            .list_by_tenant(tenant_id, status, limit, offset)
            .await
            .map_err(SandboxApiError::internal)?
            .into_iter()
            .map(SandboxRecord::from_pg_record)
            .collect()
    }

    async fn save(
        &self,
        record: &SandboxRecord,
        status: &str,
        error_message: Option<&str>,
    ) -> SandboxApiResult<()> {
        let started_at = if status == "running" {
            Some(datetime_from_ms(
                record.started_at_ms.unwrap_or(record.last_accessed_at_ms),
            ))
        } else {
            record.started_at_ms.map(datetime_from_ms)
        };
        let db_record = ProjectSandboxRecord {
            id: record.association_id.clone(),
            project_id: record.project_id.clone(),
            tenant_id: record.tenant_id.clone(),
            sandbox_id: record.sandbox_id.clone(),
            sandbox_type: record.sandbox_type.clone(),
            status: status.to_string(),
            created_at: datetime_from_ms(record.created_at_ms),
            started_at,
            last_accessed_at: datetime_from_ms(record.last_accessed_at_ms),
            health_checked_at: Some(datetime_from_ms(now_ms())),
            error_message: error_message.map(str::to_string),
            metadata_json: record.metadata_with_profile(),
            local_config: record.local_config.clone(),
        };
        self.repo
            .upsert(db_record)
            .await
            .map_err(SandboxApiError::internal)?;
        Ok(())
    }

    async fn delete(&self, project_id: &str) -> SandboxApiResult<bool> {
        self.repo
            .delete_by_project(project_id)
            .await
            .map_err(SandboxApiError::internal)
    }
}

impl SandboxRecord {
    fn new(
        sandbox_id: String,
        project_id: String,
        tenant_id: String,
        profile: SandboxProfile,
        now: i64,
    ) -> Self {
        Self {
            association_id: format!("agistack_sandbox_{project_id}"),
            sandbox_id,
            project_id,
            tenant_id,
            sandbox_type: "cloud".to_string(),
            profile,
            status: "creating".to_string(),
            created_at_ms: now,
            started_at_ms: None,
            last_accessed_at_ms: now,
            metadata_json: initial_metadata(profile),
            local_config: json!({}),
        }
    }

    fn from_pg_record(record: ProjectSandboxRecord) -> SandboxApiResult<Self> {
        let profile = profile_from_metadata(&record.metadata_json);
        Ok(Self {
            association_id: record.id,
            sandbox_id: record.sandbox_id,
            project_id: record.project_id,
            tenant_id: record.tenant_id,
            sandbox_type: normalize_sandbox_type(&record.sandbox_type),
            profile,
            status: record.status,
            created_at_ms: record.created_at.timestamp_millis(),
            started_at_ms: record.started_at.map(|value| value.timestamp_millis()),
            last_accessed_at_ms: record.last_accessed_at.timestamp_millis(),
            metadata_json: record.metadata_json,
            local_config: record.local_config,
        })
    }

    fn metadata_with_profile(&self) -> Value {
        let mut metadata = match self.metadata_json.clone() {
            Value::Object(map) => Value::Object(map),
            _ => Value::Object(Map::new()),
        };
        if let Value::Object(map) = &mut metadata {
            map.insert(
                "profile".to_string(),
                Value::String(self.profile.as_str().to_string()),
            );
            map.insert(
                "sandbox_type".to_string(),
                Value::String(self.sandbox_type.clone()),
            );
        }
        metadata
    }

    fn new_local(
        sandbox_id: String,
        project_id: String,
        tenant_id: String,
        profile: SandboxProfile,
        now: i64,
        local_config: Value,
    ) -> Self {
        let mut record = Self {
            association_id: format!("agistack_sandbox_{project_id}"),
            sandbox_id,
            project_id,
            tenant_id,
            sandbox_type: "local".to_string(),
            profile,
            status: "running".to_string(),
            created_at_ms: now,
            started_at_ms: Some(now),
            last_accessed_at_ms: now,
            metadata_json: local_metadata(profile, &local_config),
            local_config,
        };
        record.project_local_connection_fields();
        record
    }

    fn apply_runtime_ports(&mut self, ports: &[PortBinding]) {
        let host = sandbox_public_host();
        for binding in ports {
            if binding.host_port == 0 {
                continue;
            }
            match binding.container_port {
                MCP_CONTAINER_PORT => self.set_mcp_port(binding.host_port, &host),
                DESKTOP_CONTAINER_PORT => self.set_desktop_port(binding.host_port, &host),
                TERMINAL_CONTAINER_PORT => self.set_terminal_port(binding.host_port, &host),
                _ => {}
            }
        }
    }

    fn metadata_object_mut(&mut self) -> &mut Map<String, Value> {
        if !matches!(self.metadata_json, Value::Object(_)) {
            self.metadata_json = Value::Object(Map::new());
        }
        match &mut self.metadata_json {
            Value::Object(map) => map,
            _ => unreachable!("metadata_json normalized to object"),
        }
    }

    fn set_mcp_port(&mut self, port: u16, host: &str) {
        let url = format!("ws://{host}:{port}");
        let map = self.metadata_object_mut();
        map.insert("mcp_port".to_string(), Value::from(port));
        map.insert("endpoint".to_string(), Value::String(url.clone()));
        map.insert("websocket_url".to_string(), Value::String(url.clone()));
        map.insert("mcp_url".to_string(), Value::String(url));
    }

    fn project_local_connection_fields(&mut self) {
        if !self.is_local() {
            return;
        }
        let Some(url) = local_config_websocket_url(&self.local_config) else {
            return;
        };
        let port = port_field(&self.local_config, "port");
        let map = self.metadata_object_mut();
        map.insert("endpoint".to_string(), Value::String(url.clone()));
        map.insert("websocket_url".to_string(), Value::String(url.clone()));
        map.insert("mcp_url".to_string(), Value::String(url));
        if let Some(port) = port {
            map.insert("mcp_port".to_string(), Value::from(port));
        }
    }

    fn set_desktop_port(&mut self, port: u16, host: &str) {
        let map = self.metadata_object_mut();
        map.insert("desktop_port".to_string(), Value::from(port));
        map.insert(
            "desktop_url".to_string(),
            Value::String(format!("https://{host}:{port}")),
        );
    }

    fn set_terminal_port(&mut self, port: u16, host: &str) {
        let map = self.metadata_object_mut();
        map.insert("terminal_port".to_string(), Value::from(port));
        map.insert(
            "terminal_url".to_string(),
            Value::String(format!("ws://{host}:{port}")),
        );
    }

    fn endpoint(&self) -> Option<String> {
        connection_url(&self.metadata_json, &self.local_config)
    }

    fn websocket_url(&self) -> Option<String> {
        string_field(&self.metadata_json, "websocket_url")
            .or_else(|| string_field(&self.metadata_json, "endpoint"))
            .or_else(|| string_field(&self.metadata_json, "mcp_url"))
            .or_else(|| local_config_websocket_url(&self.local_config))
    }

    fn mcp_port(&self) -> Option<u16> {
        port_field(&self.metadata_json, "mcp_port")
            .or_else(|| port_field(&self.local_config, "port"))
    }

    fn desktop_port(&self) -> Option<u16> {
        port_field(&self.metadata_json, "desktop_port")
    }

    fn terminal_port(&self) -> Option<u16> {
        port_field(&self.metadata_json, "terminal_port")
    }

    fn desktop_url(&self) -> Option<String> {
        string_field(&self.metadata_json, "desktop_url")
    }

    fn terminal_url(&self) -> Option<String> {
        string_field(&self.metadata_json, "terminal_url")
    }

    fn is_local(&self) -> bool {
        self.sandbox_type.eq_ignore_ascii_case("local")
    }

    fn synthetic_container_status(&self) -> ContainerStatus {
        let state = match self.status.as_str() {
            "running" => ContainerState::Running,
            "creating" | "pending" | "connecting" => ContainerState::Created,
            "stopped" | "terminated" | "orphan" => ContainerState::Exited,
            _ => ContainerState::Unknown,
        };
        ContainerStatus {
            id: self.sandbox_id.clone(),
            running: matches!(state, ContainerState::Running),
            state,
            exit_code: None,
            ports: Vec::new(),
        }
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

impl ProjectSandboxService {
    pub(crate) fn new(runtime: Arc<dyn ContainerRuntime>, image: impl Into<String>) -> Self {
        Self::with_registry(runtime, image, Arc::new(InMemorySandboxRegistry::new()))
    }

    pub(crate) fn with_postgres(
        runtime: Arc<dyn ContainerRuntime>,
        image: impl Into<String>,
        repo: PgProjectSandboxRepository,
    ) -> Self {
        Self::with_registry(runtime, image, Arc::new(PgSandboxRegistry::new(repo)))
    }

    fn with_registry(
        runtime: Arc<dyn ContainerRuntime>,
        image: impl Into<String>,
        registry: Arc<dyn SandboxRegistry>,
    ) -> Self {
        Self {
            runtime,
            tool_host: None,
            tool_connector: None,
            image: image.into(),
            registry,
            http_registry: in_memory_http_service_registry(),
            config_source: None,
        }
    }

    pub(crate) fn with_http_service_registry(
        mut self,
        registry: SharedHttpServiceRegistry,
    ) -> Self {
        self.http_registry = registry;
        self
    }

    pub(crate) fn with_project_config_source(
        mut self,
        source: Arc<dyn ProjectSandboxConfigSource>,
    ) -> Self {
        self.config_source = Some(source);
        self
    }

    pub(crate) fn with_tool_host(mut self, tool_host: Arc<dyn ToolHost>) -> Self {
        self.tool_host = Some(tool_host);
        self
    }

    pub(crate) fn with_ws_mcp_connector(mut self) -> Self {
        self.tool_connector = Some(Arc::new(WsMcpToolConnector));
        self
    }

    #[cfg(test)]
    fn with_tool_connector(mut self, connector: Arc<dyn SandboxToolConnector>) -> Self {
        self.tool_connector = Some(connector);
        self
    }

    async fn get(&self, project_id: &str) -> SandboxApiResult<Option<ProjectSandboxInfo>> {
        let record = self.registry.get(project_id).await?;
        match record {
            None => Ok(None),
            Some(record) => {
                let status = self.status_or_gone(&record).await?;
                let Some(status) = status else {
                    self.registry.delete(project_id).await?;
                    return Ok(None);
                };
                let mut touched = record;
                touched.last_accessed_at_ms = now_ms();
                let info = ProjectSandboxInfo::from_record(touched, status);
                let status = info.status_str();
                let error_message = info.error_message();
                let record = info.to_record();
                self.registry
                    .save(&record, status, error_message.as_deref())
                    .await?;
                Ok(Some(info))
            }
        }
    }

    async fn list(
        &self,
        tenant_id: &str,
        status: Option<&str>,
        limit: i64,
        offset: i64,
    ) -> SandboxApiResult<Vec<ProjectSandboxInfo>> {
        let records = self.registry.list(tenant_id, status, limit, offset).await?;
        let mut out = Vec::with_capacity(records.len());
        for record in records {
            let project_id = record.project_id.clone();
            let Some(status) = self.status_or_gone(&record).await? else {
                self.registry.delete(&project_id).await?;
                continue;
            };
            let info = ProjectSandboxInfo::from_record(record, status);
            let computed_status = info.status_str();
            let error_message = info.error_message();
            let record = info.to_record();
            self.registry
                .save(&record, computed_status, error_message.as_deref())
                .await?;
            out.push(info);
        }
        Ok(out)
    }

    async fn ensure(
        &self,
        project_id: &str,
        tenant_id: &str,
        profile: Option<SandboxProfile>,
    ) -> SandboxApiResult<ProjectSandboxInfo> {
        let profile = profile.unwrap_or(SandboxProfile::Standard);
        let project_config = self.project_sandbox_config(project_id).await?;
        if project_config.is_local() {
            return self
                .ensure_local(project_id, tenant_id, profile, project_config.local_config)
                .await;
        }
        self.discard_local_record_for_cloud_project(project_id)
            .await?;
        if let Some(info) = self.get(project_id).await? {
            if matches!(info.state, ContainerState::Running) {
                return Ok(info);
            }
            if info.is_local() {
                return self
                    .ensure_local(project_id, tenant_id, profile, info.local_config)
                    .await;
            }
            self.runtime
                .start(&info.sandbox_id)
                .await
                .map_err(SandboxApiError::internal)?;
            return self
                .get(project_id)
                .await?
                .ok_or_else(|| SandboxApiError::not_found(SANDBOX_NOT_FOUND));
        }

        let now = now_ms();
        let spec = ContainerSpec {
            image: self.image.clone(),
            cmd: None,
            env: vec![
                ("AGISTACK_PROJECT_ID".to_string(), project_id.to_string()),
                ("AGISTACK_TENANT_ID".to_string(), tenant_id.to_string()),
                (
                    "AGISTACK_SANDBOX_PROFILE".to_string(),
                    profile.as_str().to_string(),
                ),
            ],
            labels: vec![
                (PROJECT_LABEL.to_string(), project_id.to_string()),
                (TENANT_LABEL.to_string(), tenant_id.to_string()),
                (KIND_LABEL.to_string(), KIND_PROJECT.to_string()),
            ],
            ports: sandbox_port_bindings(),
        };
        let sandbox_id = self
            .runtime
            .create(&spec)
            .await
            .map_err(SandboxApiError::internal)?;
        let record = SandboxRecord::new(
            sandbox_id.clone(),
            project_id.to_string(),
            tenant_id.to_string(),
            profile,
            now,
        );
        self.registry.save(&record, "creating", None).await?;
        self.runtime
            .start(&sandbox_id)
            .await
            .map_err(SandboxApiError::internal)?;
        self.get(project_id)
            .await?
            .ok_or_else(|| SandboxApiError::not_found(SANDBOX_NOT_FOUND))
    }

    async fn project_sandbox_config(
        &self,
        project_id: &str,
    ) -> SandboxApiResult<ProjectSandboxConfig> {
        let Some(source) = self.config_source.as_ref() else {
            return Ok(ProjectSandboxConfig::cloud());
        };
        Ok(source
            .get_project_sandbox_config(project_id)
            .await?
            .unwrap_or_else(ProjectSandboxConfig::cloud))
    }

    async fn ensure_local(
        &self,
        project_id: &str,
        tenant_id: &str,
        profile: SandboxProfile,
        local_config: Value,
    ) -> SandboxApiResult<ProjectSandboxInfo> {
        let now = now_ms();
        let normalized_local_config = normalize_local_config(local_config);
        let existing = self.registry.get(project_id).await?;
        let existing_local = if let Some(existing) = existing {
            if !existing.is_local() {
                self.runtime
                    .stop(&existing.sandbox_id)
                    .await
                    .map_err(SandboxApiError::internal)?;
                self.runtime
                    .remove(&existing.sandbox_id)
                    .await
                    .map_err(SandboxApiError::internal)?;
                None
            } else {
                Some(existing)
            }
        } else {
            None
        };

        let mut record = existing_local.unwrap_or_else(|| {
            SandboxRecord::new_local(
                format!("local-{project_id}"),
                project_id.to_string(),
                tenant_id.to_string(),
                profile,
                now,
                normalized_local_config.clone(),
            )
        });
        record.sandbox_type = "local".to_string();
        record.tenant_id = tenant_id.to_string();
        record.profile = profile;
        record.status = "running".to_string();
        record.started_at_ms = Some(record.started_at_ms.unwrap_or(now));
        record.last_accessed_at_ms = now;
        record.local_config = normalized_local_config;
        record.metadata_json = local_metadata(record.profile, &record.local_config);
        record.project_local_connection_fields();

        self.registry.save(&record, "running", None).await?;
        Ok(ProjectSandboxInfo::from_record(
            record.clone(),
            record.synthetic_container_status(),
        ))
    }

    async fn discard_local_record_for_cloud_project(
        &self,
        project_id: &str,
    ) -> SandboxApiResult<()> {
        let Some(record) = self.registry.get(project_id).await? else {
            return Ok(());
        };
        if record.is_local() {
            self.registry.delete(project_id).await?;
        }
        Ok(())
    }

    async fn restart(&self, project_id: &str) -> SandboxApiResult<ProjectSandboxInfo> {
        let mut record = self
            .registry
            .get(project_id)
            .await?
            .ok_or_else(|| SandboxApiError::not_found(SANDBOX_NOT_FOUND))?;
        if record.is_local() {
            record.status = "running".to_string();
            record.last_accessed_at_ms = now_ms();
            self.registry.save(&record, "running", None).await?;
            return Ok(ProjectSandboxInfo::from_record(
                record.clone(),
                record.synthetic_container_status(),
            ));
        }
        self.runtime
            .stop(&record.sandbox_id)
            .await
            .map_err(SandboxApiError::internal)?;
        self.runtime
            .start(&record.sandbox_id)
            .await
            .map_err(SandboxApiError::internal)?;
        self.get(project_id)
            .await?
            .ok_or_else(|| SandboxApiError::not_found(SANDBOX_NOT_FOUND))
    }

    async fn terminate(&self, project_id: &str) -> SandboxApiResult<bool> {
        let record = self.registry.get(project_id).await?;
        let Some(record) = record else {
            return Ok(false);
        };
        if record.is_local() {
            self.registry.save(&record, "terminated", None).await?;
            self.registry.delete(project_id).await?;
            return Ok(true);
        }
        self.runtime
            .stop(&record.sandbox_id)
            .await
            .map_err(SandboxApiError::internal)?;
        self.runtime
            .remove(&record.sandbox_id)
            .await
            .map_err(SandboxApiError::internal)?;
        self.registry.save(&record, "terminated", None).await?;
        self.registry.delete(project_id).await?;
        Ok(true)
    }

    async fn execute_tool_with_max_timeout(
        &self,
        project_id: &str,
        tool_name: &str,
        arguments: &Value,
        timeout_seconds: f64,
        max_timeout_seconds: f64,
    ) -> SandboxApiResult<ExecuteToolResponse> {
        if !(1.0..=max_timeout_seconds).contains(&timeout_seconds) || !timeout_seconds.is_finite() {
            return Err(SandboxApiError::bad_request(format!(
                "Execution timeout must be between 1 and {max_timeout_seconds:.0} seconds"
            )));
        }

        let info = self
            .get(project_id)
            .await?
            .ok_or_else(|| SandboxApiError::not_found(SANDBOX_NOT_FOUND))?;
        if !info.healthy() {
            return Err(SandboxApiError::internal("Execution failed"));
        }
        let host = self.tool_host_for(&info).await?;

        let input_json = arguments.to_string();
        let started = Instant::now();
        let timeout = Duration::from_millis((timeout_seconds * 1_000.0).ceil() as u64);
        let raw = tokio::time::timeout(timeout, host.call(tool_name, &input_json))
            .await
            .map_err(|_| SandboxApiError::internal("Execution failed"))?
            .map_err(|_| SandboxApiError::internal("Execution failed"))?;
        let elapsed = started.elapsed().as_millis().min(i64::MAX as u128) as i64;
        Ok(normalize_tool_result(&raw, elapsed))
    }

    async fn execute_tool(
        &self,
        project_id: &str,
        tool_name: &str,
        arguments: &Value,
        timeout_seconds: f64,
    ) -> SandboxApiResult<ExecuteToolResponse> {
        self.execute_tool_with_max_timeout(project_id, tool_name, arguments, timeout_seconds, 300.0)
            .await
    }

    pub(crate) async fn execute_pipeline_tool(
        &self,
        project_id: &str,
        tool_name: &str,
        arguments: &Value,
        timeout_seconds: f64,
    ) -> SandboxApiResult<ExecuteToolResponse> {
        self.execute_tool_with_max_timeout(
            project_id,
            tool_name,
            arguments,
            timeout_seconds,
            3_600.0,
        )
        .await
    }

    async fn register_http_service(
        &self,
        project_id: &str,
        tenant_id: &str,
        req: RegisterHttpServiceRequest,
    ) -> SandboxApiResult<HttpServiceProxyInfo> {
        validate_http_service_name(&req.name)?;
        let service_id = normalize_http_service_id(req.service_id.as_deref())?;
        let now = now_ms();
        let updated_at = python_utc_offset_string(now);
        let restart_token = Some(now.to_string());

        let (service_url, preview_url, ws_preview_url, sandbox_id) = match req.source_type {
            HttpServiceSourceType::SandboxInternal => {
                let internal_port = req.internal_port.ok_or_else(|| {
                    SandboxApiError::bad_request(
                        "internal_port is required for sandbox_internal services",
                    )
                })?;
                let internal_scheme = normalize_internal_scheme(&req.internal_scheme)?;
                let info = self.ensure(project_id, tenant_id, None).await?;
                let host = sandbox_internal_service_host(&info);
                let path_prefix = normalize_path_prefix(&req.path_prefix);
                (
                    format!("{internal_scheme}://{host}:{internal_port}{path_prefix}"),
                    build_http_preview_proxy_url(project_id, &service_id),
                    Some(build_http_preview_ws_proxy_url(project_id, &service_id)),
                    Some(info.sandbox_id),
                )
            }
            HttpServiceSourceType::ExternalUrl => {
                let external_url = req.external_url.as_deref().ok_or_else(|| {
                    SandboxApiError::bad_request(
                        "external_url is required for external_url services",
                    )
                })?;
                let service_url = validate_external_http_url(external_url)?;
                (service_url.clone(), service_url, None, None)
            }
        };

        let info = HttpServiceProxyInfo {
            service_id: service_id.clone(),
            name: req.name,
            source_type: req.source_type,
            status: "running".to_string(),
            service_url,
            preview_url,
            ws_preview_url,
            sandbox_id,
            auto_open: req.auto_open,
            restart_token,
            updated_at,
        };
        self.upsert_http_service(project_id, info).await
    }

    async fn upsert_http_service(
        &self,
        project_id: &str,
        info: HttpServiceProxyInfo,
    ) -> SandboxApiResult<HttpServiceProxyInfo> {
        self.http_registry.upsert(project_id, info).await
    }

    async fn list_http_services(
        &self,
        project_id: &str,
    ) -> SandboxApiResult<Vec<HttpServiceProxyInfo>> {
        self.http_registry.list(project_id).await
    }

    async fn get_http_service(
        &self,
        project_id: &str,
        service_id: &str,
    ) -> SandboxApiResult<Option<HttpServiceProxyInfo>> {
        self.http_registry.get(project_id, service_id).await
    }

    async fn get_http_service_by_preview_label(
        &self,
        project_id: &str,
        service_label: &str,
    ) -> SandboxApiResult<Option<HttpServiceProxyInfo>> {
        Ok(self
            .list_http_services(project_id)
            .await?
            .into_iter()
            .find(|service| preview_service_host_label(&service.service_id) == service_label))
    }

    async fn remove_http_service(
        &self,
        project_id: &str,
        service_id: &str,
    ) -> SandboxApiResult<Option<HttpServiceProxyInfo>> {
        self.http_registry.remove(project_id, service_id).await
    }

    async fn preview_session(
        &self,
        project_id: &str,
        service_id: &str,
    ) -> SandboxApiResult<HttpServicePreviewSessionResponse> {
        let service = self
            .get_http_service(project_id, service_id)
            .await?
            .ok_or_else(http_service_not_found)?;
        if service.source_type == HttpServiceSourceType::ExternalUrl {
            return Ok(HttpServicePreviewSessionResponse {
                preview_url: service.preview_url,
                expires_in_seconds: 0,
            });
        }
        let token = agistack_adapters_secrets::generate_urlsafe_token(32);
        let expires_in_seconds = preview_session_ttl_seconds();
        self.http_registry
            .create_preview_session(
                &token,
                PreviewSessionRecord {
                    project_id: project_id.to_string(),
                    service_id: service_id.to_string(),
                    expires_at_ms: now_ms() + expires_in_seconds * 1000,
                },
                expires_in_seconds,
            )
            .await?;
        Ok(HttpServicePreviewSessionResponse {
            preview_url: append_query_param(
                &build_http_preview_proxy_url(project_id, service_id),
                PREVIEW_SESSION_QUERY_PARAM,
                &token,
            ),
            expires_in_seconds,
        })
    }

    async fn preview_session_matches_service(
        &self,
        token: Option<&str>,
        project_id: &str,
        service_id: &str,
    ) -> SandboxApiResult<Option<PreviewSessionRecord>> {
        let Some(token) = token.filter(|token| !token.is_empty()) else {
            return Ok(None);
        };
        let now = now_ms();
        Ok(self
            .http_registry
            .get_preview_session(token)
            .await?
            .filter(|session| session.project_id == project_id && session.service_id == service_id)
            .filter(|session| session.expires_at_ms > now))
    }

    async fn create_terminal_session(
        &self,
        project_id: &str,
    ) -> SandboxApiResult<TerminalSessionRecord> {
        let ttl_seconds = terminal_session_ttl_seconds();
        let now = now_ms();
        let record = TerminalSessionRecord::new(
            project_id.to_string(),
            new_terminal_session_id(),
            TerminalSize::default(),
            false,
            now,
            ttl_seconds,
        );
        self.http_registry
            .upsert_terminal_session(record.clone(), ttl_seconds)
            .await?;
        Ok(record)
    }

    async fn get_terminal_session(
        &self,
        project_id: &str,
        session_id: &str,
    ) -> SandboxApiResult<Option<TerminalSessionRecord>> {
        let now = now_ms();
        Ok(self
            .http_registry
            .get_terminal_session(project_id, session_id)
            .await?
            .filter(|session| session.project_id == project_id)
            .filter(|session| session.session_id == session_id)
            .filter(|session| session.expires_at_ms > now))
    }

    fn terminal_session_recorder(
        &self,
        project_id: String,
        session_id: String,
    ) -> TerminalSessionRecorder {
        TerminalSessionRecorder::new(
            self.http_registry.clone(),
            project_id,
            session_id,
            terminal_session_ttl_seconds(),
        )
    }

    async fn create_mcp_upstream_token(
        &self,
        project_id: &str,
        sandbox_id: &str,
    ) -> SandboxApiResult<McpUpstreamTokenRecord> {
        let ttl_seconds = mcp_upstream_token_ttl_seconds();
        let now = now_ms();
        let record = McpUpstreamTokenRecord::new(
            project_id.to_string(),
            sandbox_id.to_string(),
            now,
            ttl_seconds,
        );
        self.http_registry
            .create_mcp_upstream_token(record.clone(), ttl_seconds)
            .await?;
        Ok(record)
    }

    async fn tool_host_for(
        &self,
        info: &ProjectSandboxInfo,
    ) -> SandboxApiResult<Arc<dyn ToolHost>> {
        let endpoint = info.websocket_url.as_ref().or(info.endpoint.as_ref());
        if let (Some(url), Some(connector)) = (endpoint, self.tool_connector.as_ref()) {
            return connector.connect_tool_host(url).await;
        }
        self.tool_host
            .clone()
            .ok_or_else(|| SandboxApiError::internal("Sandbox tool host is not configured"))
    }

    async fn status_or_gone(
        &self,
        record: &SandboxRecord,
    ) -> SandboxApiResult<Option<ContainerStatus>> {
        if record.is_local() {
            return Ok(Some(record.synthetic_container_status()));
        }
        self.runtime
            .status(&record.sandbox_id)
            .await
            .map_err(SandboxApiError::internal)
    }
}

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

#[derive(Debug, Deserialize)]
struct EnsureSandboxRequest {
    profile: Option<String>,
    #[serde(default = "default_auto_create")]
    _auto_create: bool,
}

fn default_auto_create() -> bool {
    true
}

#[derive(Debug, Serialize, PartialEq)]
struct ProjectSandboxResponse {
    sandbox_id: String,
    project_id: String,
    tenant_id: String,
    status: String,
    endpoint: Option<String>,
    websocket_url: Option<String>,
    mcp_port: Option<u16>,
    desktop_port: Option<u16>,
    terminal_port: Option<u16>,
    desktop_url: Option<String>,
    terminal_url: Option<String>,
    created_at: Option<String>,
    last_accessed_at: Option<String>,
    is_healthy: bool,
    error_message: Option<String>,
}

impl From<ProjectSandboxInfo> for ProjectSandboxResponse {
    fn from(info: ProjectSandboxInfo) -> Self {
        let status = info.status_str().to_string();
        let is_healthy = info.healthy();
        let error_message = info.error_message();
        Self {
            sandbox_id: info.sandbox_id,
            project_id: info.project_id,
            tenant_id: info.tenant_id,
            status,
            endpoint: info.endpoint,
            websocket_url: info.websocket_url,
            mcp_port: info.mcp_port,
            desktop_port: info.desktop_port,
            terminal_port: info.terminal_port,
            desktop_url: info.desktop_url,
            terminal_url: info.terminal_url,
            created_at: Some(rfc3339(info.created_at_ms)),
            last_accessed_at: Some(rfc3339(info.last_accessed_at_ms)),
            is_healthy,
            error_message,
        }
    }
}

#[derive(Debug, Serialize, PartialEq)]
struct HealthCheckResponse {
    project_id: String,
    sandbox_id: String,
    healthy: bool,
    status: String,
    checked_at: String,
}

#[derive(Debug, Serialize, PartialEq)]
struct SandboxStatsResponse {
    project_id: String,
    sandbox_id: String,
    status: String,
    cpu_percent: f64,
    memory_usage: u64,
    memory_limit: u64,
    memory_percent: f64,
    disk_usage: Option<u64>,
    disk_limit: Option<u64>,
    disk_percent: Option<f64>,
    network_rx_bytes: Option<u64>,
    network_tx_bytes: Option<u64>,
    pids: u64,
    uptime_seconds: Option<i64>,
    created_at: Option<String>,
    collected_at: String,
}

#[derive(Debug, Serialize, PartialEq)]
struct SandboxActionResponse {
    success: bool,
    message: String,
    sandbox: Option<ProjectSandboxResponse>,
}

#[derive(Debug, Serialize, PartialEq)]
struct ListProjectSandboxesResponse {
    sandboxes: Vec<ProjectSandboxResponse>,
    total: usize,
}

#[derive(Debug, Deserialize)]
struct ExecuteToolRequest {
    tool_name: String,
    #[serde(default)]
    arguments: Value,
    #[serde(default = "default_tool_timeout")]
    timeout: f64,
}

fn default_tool_timeout() -> f64 {
    30.0
}

#[derive(Debug, Serialize, PartialEq)]
pub(crate) struct ExecuteToolResponse {
    pub(crate) success: bool,
    pub(crate) content: Vec<Value>,
    pub(crate) is_error: bool,
    pub(crate) execution_time_ms: Option<i64>,
}

#[derive(Debug, Deserialize)]
struct StartDesktopQuery {
    resolution: Option<String>,
}

#[derive(Debug, Deserialize)]
struct TerminalWsQuery {
    session_id: Option<String>,
}

#[derive(Debug, Serialize, PartialEq)]
struct DesktopServiceResponse {
    success: bool,
    url: Option<String>,
    display: String,
    resolution: String,
    port: u16,
    audio_enabled: bool,
    dynamic_resize: bool,
    encoding: String,
}

impl DesktopServiceResponse {
    fn from_info(info: &ProjectSandboxInfo, resolution: String) -> Self {
        Self {
            success: info.desktop_url.is_some(),
            url: info.desktop_url.clone(),
            display: DESKTOP_DEFAULT_DISPLAY.to_string(),
            resolution,
            port: info.desktop_port.unwrap_or(0),
            audio_enabled: false,
            dynamic_resize: true,
            encoding: DESKTOP_DEFAULT_ENCODING.to_string(),
        }
    }
}

#[derive(Debug, Serialize, PartialEq)]
struct TerminalServiceResponse {
    success: bool,
    url: Option<String>,
    port: u16,
    session_id: Option<String>,
}

impl TerminalServiceResponse {
    #[cfg(test)]
    fn from_info(info: &ProjectSandboxInfo) -> Self {
        Self::from_info_with_session(info, None)
    }

    fn from_info_with_session(info: &ProjectSandboxInfo, session_id: Option<String>) -> Self {
        Self {
            success: info.terminal_url.is_some(),
            url: info.terminal_url.clone(),
            port: info.terminal_port.unwrap_or(0),
            session_id,
        }
    }
}

#[derive(Debug, Serialize, PartialEq)]
struct SandboxServiceStopResponse {
    success: bool,
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

#[derive(Debug, Serialize, PartialEq)]
struct HttpServiceResponse {
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

impl From<HttpServiceProxyInfo> for HttpServiceResponse {
    fn from(info: HttpServiceProxyInfo) -> Self {
        Self {
            service_id: info.service_id,
            name: info.name,
            source_type: info.source_type,
            status: info.status,
            service_url: info.service_url,
            preview_url: info.preview_url,
            ws_preview_url: info.ws_preview_url,
            sandbox_id: info.sandbox_id,
            auto_open: info.auto_open,
            restart_token: info.restart_token,
            updated_at: info.updated_at,
        }
    }
}

#[derive(Debug, Serialize, PartialEq)]
struct ListHttpServicesResponse {
    services: Vec<HttpServiceResponse>,
    total: usize,
}

#[derive(Debug, Serialize, PartialEq)]
struct HttpServiceActionResponse {
    success: bool,
    message: String,
    service: Option<HttpServiceResponse>,
}

#[derive(Debug, Serialize, PartialEq)]
struct HttpServicePreviewSessionResponse {
    preview_url: String,
    expires_in_seconds: i64,
}

#[derive(Debug, Serialize, PartialEq)]
struct SandboxProxyAuthCookieResponse {
    success: bool,
    expires_in_seconds: i64,
}

#[derive(Debug, Deserialize)]
struct ListProjectSandboxesQuery {
    status: Option<String>,
    limit: Option<i64>,
    offset: Option<i64>,
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
        .expect("valid http service attribute rewrite regex");
    content = attr_re
        .replace_all(&content, |caps: &regex::Captures<'_>| {
            let proxied = append_proxy_token(&format!("{}{}", proxy_prefix, &caps[3]), token_param);
            format!("{}={}{}", &caps[1], &caps[2], proxied)
        })
        .into_owned();

    let url_re = regex::Regex::new(r#"url\((['"]?)/([^/'")][^)'"]*)['"]?\)"#)
        .expect("valid http service url() rewrite regex");
    content = url_re
        .replace_all(&content, |caps: &regex::Captures<'_>| {
            let quote = caps.get(1).map(|m| m.as_str()).unwrap_or_default();
            let proxied = append_proxy_token(&format!("{}{}", proxy_prefix, &caps[2]), token_param);
            format!("url({quote}{proxied}{quote})")
        })
        .into_owned();

    let browser_call_re = regex::Regex::new(r#"\b(fetch|EventSource)\((['"])/([^/'"][^'"]*)"#)
        .expect("valid http service browser call rewrite regex");
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
        .expect("valid http service websocket rewrite regex");
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
        .expect("valid desktop attribute rewrite regex");
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

fn websocket_upgrade_with_auth_protocol(
    ws: WebSocketUpgrade,
    headers: &HeaderMap,
) -> WebSocketUpgrade {
    match select_websocket_auth_subprotocol(headers) {
        Some(protocol) => ws.protocols([protocol]),
        None => ws,
    }
}

fn websocket_upgrade_with_desktop_protocol(ws: WebSocketUpgrade) -> WebSocketUpgrade {
    ws.protocols([DESKTOP_WEBSOCKET_SUBPROTOCOL])
}

async fn close_http_service_ws_with_policy_error(mut socket: WebSocket, reason: &'static str) {
    let _ = socket
        .send(AxumWsMessage::Close(Some(AxumCloseFrame {
            code: 1008,
            reason: reason.into(),
        })))
        .await;
}

async fn close_http_service_ws_with_internal_error(mut socket: WebSocket) {
    let _ = socket
        .send(AxumWsMessage::Text(
            json!({ "error": "HTTP service WebSocket proxy failed" }).to_string(),
        ))
        .await;
    let _ = socket
        .send(AxumWsMessage::Close(Some(AxumCloseFrame {
            code: 1011,
            reason: "HTTP service WS proxy failure".into(),
        })))
        .await;
}

async fn close_desktop_ws_with_policy_error(mut socket: WebSocket, reason: &'static str) {
    let _ = socket
        .send(AxumWsMessage::Close(Some(AxumCloseFrame {
            code: 1008,
            reason: reason.into(),
        })))
        .await;
}

async fn close_desktop_ws_with_internal_error(mut socket: WebSocket) {
    let _ = socket
        .send(AxumWsMessage::Text(
            json!({ "error": "Desktop WebSocket proxy failed" }).to_string(),
        ))
        .await;
    let _ = socket
        .send(AxumWsMessage::Close(Some(AxumCloseFrame {
            code: 1011,
            reason: "Desktop WS proxy failure".into(),
        })))
        .await;
}

async fn close_terminal_ws_with_policy_error(mut socket: WebSocket, reason: &'static str) {
    let _ = socket
        .send(AxumWsMessage::Close(Some(AxumCloseFrame {
            code: 1008,
            reason: reason.into(),
        })))
        .await;
}

async fn close_terminal_ws_with_internal_error(mut socket: WebSocket) {
    let _ = socket
        .send(AxumWsMessage::Text(terminal_error_message()))
        .await;
    let _ = socket
        .send(AxumWsMessage::Close(Some(AxumCloseFrame {
            code: 1011,
            reason: "Terminal WebSocket proxy failure".into(),
        })))
        .await;
}

async fn close_mcp_ws_with_policy_error(mut socket: WebSocket, reason: &'static str) {
    let _ = socket
        .send(AxumWsMessage::Close(Some(AxumCloseFrame {
            code: 1008,
            reason: reason.into(),
        })))
        .await;
}

async fn close_mcp_ws_with_internal_error(mut socket: WebSocket) {
    let _ = socket
        .send(AxumWsMessage::Text(
            json!({ "error": "MCP WebSocket proxy failed" }).to_string(),
        ))
        .await;
    let _ = socket
        .send(AxumWsMessage::Close(Some(AxumCloseFrame {
            code: 1011,
            reason: "MCP WebSocket proxy failure".into(),
        })))
        .await;
}

async fn close_http_preview_host_ws_with_internal_error(mut socket: WebSocket) {
    let _ = socket
        .send(AxumWsMessage::Text(
            json!({ "error": "HTTP preview host WS proxy failed" }).to_string(),
        ))
        .await;
    let _ = socket
        .send(AxumWsMessage::Close(Some(AxumCloseFrame {
            code: 1011,
            reason: "HTTP preview host WS proxy failure".into(),
        })))
        .await;
}

async fn ensure_project_access(
    app: &AppState,
    identity: &Identity,
    project_id: &str,
) -> SandboxApiResult<()> {
    let allowed = app
        .auth
        .can_access_project(&identity.user_id, project_id)
        .await
        .map_err(SandboxApiError::internal)?;
    if allowed {
        Ok(())
    } else {
        Err(SandboxApiError::forbidden("Access denied to project"))
    }
}

async fn ensure_project_write(
    app: &AppState,
    identity: &Identity,
    project_id: &str,
) -> SandboxApiResult<()> {
    let allowed = app
        .auth
        .can_write_project(&identity.user_id, project_id)
        .await
        .map_err(SandboxApiError::internal)?;
    if allowed {
        Ok(())
    } else {
        Err(SandboxApiError::forbidden("Access denied to project"))
    }
}

async fn ensure_project_admin(
    app: &AppState,
    identity: &Identity,
    project_id: &str,
) -> SandboxApiResult<()> {
    let allowed = app
        .auth
        .can_admin_project(&identity.user_id, project_id)
        .await
        .map_err(SandboxApiError::internal)?;
    if allowed {
        Ok(())
    } else {
        Err(SandboxApiError::forbidden("Access denied to project"))
    }
}

async fn project_tenant_id(
    app: &AppState,
    identity: &Identity,
    project_id: &str,
) -> SandboxApiResult<String> {
    app.identity
        .get_project(&identity.user_id, project_id, None)
        .await
        .map(|project| project.tenant_id)
        .map_err(|err| SandboxApiError::new(err.status, err.detail))
}

async fn current_tenant_id(app: &AppState, identity: &Identity) -> SandboxApiResult<String> {
    let page = app
        .identity
        .list_tenants(&identity.user_id, None, 1, 1)
        .await
        .map_err(|err| SandboxApiError::new(err.status, err.detail))?;
    page.tenants
        .into_iter()
        .next()
        .map(|tenant| tenant.id)
        .ok_or_else(|| {
            SandboxApiError::bad_request(
                "User does not belong to any tenant. Please contact administrator.",
            )
        })
}

async fn list_project_sandboxes(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(query): Query<ListProjectSandboxesQuery>,
) -> SandboxApiResult<Json<ListProjectSandboxesResponse>> {
    let tenant_id = current_tenant_id(&app, &identity).await?;
    let status = parse_status_filter(query.status.as_deref())?;
    let limit = query.limit.unwrap_or(50).clamp(1, 100);
    let offset = query.offset.unwrap_or(0).max(0);
    let sandboxes = app
        .sandboxes
        .list(&tenant_id, status.as_deref(), limit, offset)
        .await?;
    let sandboxes = sandboxes
        .into_iter()
        .map(ProjectSandboxResponse::from)
        .collect::<Vec<_>>();
    let total = sandboxes.len();
    Ok(Json(ListProjectSandboxesResponse { sandboxes, total }))
}

async fn get_project_sandbox(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
) -> SandboxApiResult<Json<ProjectSandboxResponse>> {
    ensure_project_access(&app, &identity, &project_id).await?;
    let info = app
        .sandboxes
        .get(&project_id)
        .await?
        .ok_or_else(|| SandboxApiError::not_found(SANDBOX_NOT_FOUND_WITH_CREATE_HINT))?;
    Ok(Json(info.into()))
}

async fn ensure_project_sandbox(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
    Json(req): Json<EnsureSandboxRequest>,
) -> SandboxApiResult<Json<ProjectSandboxResponse>> {
    ensure_project_write(&app, &identity, &project_id).await?;
    let profile = SandboxProfile::parse(req.profile.as_deref())?;
    let tenant_id = project_tenant_id(&app, &identity, &project_id).await?;
    let info = app
        .sandboxes
        .ensure(&project_id, &tenant_id, profile)
        .await?;
    Ok(Json(info.into()))
}

async fn check_project_sandbox_health(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
) -> SandboxApiResult<Json<HealthCheckResponse>> {
    ensure_project_access(&app, &identity, &project_id).await?;
    let info = app
        .sandboxes
        .get(&project_id)
        .await?
        .ok_or_else(|| SandboxApiError::not_found(SANDBOX_NOT_FOUND))?;
    let healthy = info.healthy();
    let status = info.status_str().to_string();
    Ok(Json(HealthCheckResponse {
        project_id,
        sandbox_id: info.sandbox_id,
        healthy,
        status,
        checked_at: rfc3339(now_ms()),
    }))
}

async fn get_project_sandbox_stats(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
) -> SandboxApiResult<Json<SandboxStatsResponse>> {
    ensure_project_access(&app, &identity, &project_id).await?;
    let info = app
        .sandboxes
        .get(&project_id)
        .await?
        .ok_or_else(|| SandboxApiError::not_found(SANDBOX_NOT_FOUND))?;
    let now = now_ms();
    let status = info.status_str().to_string();
    let created_at_ms = info.created_at_ms;
    Ok(Json(SandboxStatsResponse {
        project_id,
        sandbox_id: info.sandbox_id,
        status,
        cpu_percent: 0.0,
        memory_usage: 0,
        memory_limit: 0,
        memory_percent: 0.0,
        disk_usage: None,
        disk_limit: None,
        disk_percent: None,
        network_rx_bytes: None,
        network_tx_bytes: None,
        pids: 0,
        uptime_seconds: Some((now - created_at_ms).max(0) / 1_000),
        created_at: Some(rfc3339(created_at_ms)),
        collected_at: rfc3339(now),
    }))
}

async fn execute_project_sandbox_tool(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
    Json(req): Json<ExecuteToolRequest>,
) -> SandboxApiResult<Json<ExecuteToolResponse>> {
    ensure_project_access(&app, &identity, &project_id).await?;
    let result = app
        .sandboxes
        .execute_tool(&project_id, &req.tool_name, &req.arguments, req.timeout)
        .await
        .map_err(|err| {
            if err.status == StatusCode::BAD_REQUEST {
                err
            } else {
                SandboxApiError::internal("Execution failed")
            }
        })?;
    Ok(Json(result))
}

async fn seed_project_sandbox_proxy_auth_cookie(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Extension(raw_key): Extension<RawApiKey>,
    headers: HeaderMap,
    Path(project_id): Path<String>,
) -> SandboxApiResult<Response> {
    ensure_project_access(&app, &identity, &project_id).await?;
    let cookie =
        sandbox_proxy_auth_cookie(&project_id, &raw_key.0, proxy_auth_cookie_secure(&headers))?;
    let mut response = Json(SandboxProxyAuthCookieResponse {
        success: true,
        expires_in_seconds: SANDBOX_PROXY_AUTH_COOKIE_MAX_AGE_SECONDS,
    })
    .into_response();
    response.headers_mut().append(SET_COOKIE, cookie);
    Ok(response)
}

async fn start_project_desktop(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
    Query(query): Query<StartDesktopQuery>,
) -> SandboxApiResult<Json<DesktopServiceResponse>> {
    ensure_project_access(&app, &identity, &project_id).await?;
    let tenant_id = project_tenant_id(&app, &identity, &project_id).await?;
    let info = app.sandboxes.ensure(&project_id, &tenant_id, None).await?;
    Ok(Json(DesktopServiceResponse::from_info(
        &info,
        query
            .resolution
            .unwrap_or_else(|| DESKTOP_DEFAULT_RESOLUTION.to_string()),
    )))
}

async fn stop_project_desktop(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
) -> SandboxApiResult<Json<SandboxServiceStopResponse>> {
    ensure_project_access(&app, &identity, &project_id).await?;
    app.sandboxes
        .get(&project_id)
        .await?
        .ok_or_else(|| SandboxApiError::not_found(SANDBOX_NOT_FOUND))?;
    Ok(Json(SandboxServiceStopResponse { success: true }))
}

async fn start_project_terminal(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
) -> SandboxApiResult<Json<TerminalServiceResponse>> {
    ensure_project_access(&app, &identity, &project_id).await?;
    let tenant_id = project_tenant_id(&app, &identity, &project_id).await?;
    let info = app.sandboxes.ensure(&project_id, &tenant_id, None).await?;
    let session = app.sandboxes.create_terminal_session(&project_id).await?;
    Ok(Json(TerminalServiceResponse::from_info_with_session(
        &info,
        Some(session.session_id),
    )))
}

async fn stop_project_terminal(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
) -> SandboxApiResult<Json<SandboxServiceStopResponse>> {
    ensure_project_access(&app, &identity, &project_id).await?;
    app.sandboxes
        .get(&project_id)
        .await?
        .ok_or_else(|| SandboxApiError::not_found(SANDBOX_NOT_FOUND))?;
    Ok(Json(SandboxServiceStopResponse { success: true }))
}

async fn proxy_project_desktop_impl(
    app: AppState,
    identity: Identity,
    project_id: String,
    path: String,
    raw_query: Option<String>,
    headers: HeaderMap,
) -> SandboxApiResult<Response> {
    ensure_project_access(&app, &identity, &project_id).await?;
    let info = app
        .sandboxes
        .get(&project_id)
        .await?
        .ok_or_else(|| SandboxApiError::not_found(SANDBOX_NOT_FOUND))?;
    let secure_cookie = proxy_auth_cookie_secure(&headers);
    proxy_project_desktop_response(
        &project_id,
        &info,
        &path,
        raw_query.as_deref(),
        headers,
        secure_cookie,
    )
    .await
}

async fn proxy_project_desktop_root(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
    RawQuery(raw_query): RawQuery,
    headers: HeaderMap,
) -> SandboxApiResult<Response> {
    proxy_project_desktop_impl(app, identity, project_id, String::new(), raw_query, headers).await
}

async fn proxy_project_desktop_path(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((project_id, path)): Path<(String, String)>,
    RawQuery(raw_query): RawQuery,
    headers: HeaderMap,
) -> SandboxApiResult<Response> {
    proxy_project_desktop_impl(app, identity, project_id, path, raw_query, headers).await
}

async fn proxy_project_desktop_ws_impl(
    app: AppState,
    identity: Identity,
    project_id: String,
    ws: WebSocketUpgrade,
) -> SandboxApiResult<Response> {
    ensure_project_access(&app, &identity, &project_id).await?;
    let Some(info) = app.sandboxes.get(&project_id).await? else {
        return Ok(websocket_upgrade_with_desktop_protocol(ws)
            .on_upgrade(|socket| close_desktop_ws_with_policy_error(socket, SANDBOX_NOT_FOUND))
            .into_response());
    };
    let Some(desktop_url) = info.desktop_url.as_deref() else {
        return Ok(websocket_upgrade_with_desktop_protocol(ws)
            .on_upgrade(|socket| {
                close_desktop_ws_with_policy_error(socket, DESKTOP_SERVICE_NOT_RUNNING)
            })
            .into_response());
    };
    let ws_target = match build_desktop_websocket_target(desktop_url) {
        Ok(ws_target) => ws_target,
        Err(_) => {
            return Ok(websocket_upgrade_with_desktop_protocol(ws)
                .on_upgrade(close_desktop_ws_with_internal_error)
                .into_response());
        }
    };
    let origin = desktop_websocket_origin(desktop_url, &ws_target);
    Ok(websocket_upgrade_with_desktop_protocol(ws)
        .on_upgrade(move |socket| proxy_desktop_ws_session(socket, ws_target, origin))
        .into_response())
}

async fn proxy_project_desktop_websockify(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
    ws: WebSocketUpgrade,
) -> SandboxApiResult<Response> {
    proxy_project_desktop_ws_impl(app, identity, project_id, ws).await
}

async fn proxy_project_terminal_ws_impl(
    app: AppState,
    identity: Identity,
    project_id: String,
    query: TerminalWsQuery,
    headers: HeaderMap,
    ws: WebSocketUpgrade,
) -> SandboxApiResult<Response> {
    ensure_project_access(&app, &identity, &project_id).await?;
    let Some(info) = app.sandboxes.get(&project_id).await? else {
        return Ok(websocket_upgrade_with_auth_protocol(ws, &headers)
            .on_upgrade(|socket| close_terminal_ws_with_policy_error(socket, SANDBOX_NOT_FOUND))
            .into_response());
    };
    let Some(terminal_url) = info.terminal_url.as_deref() else {
        return Ok(websocket_upgrade_with_auth_protocol(ws, &headers)
            .on_upgrade(|socket| {
                close_terminal_ws_with_policy_error(socket, TERMINAL_SERVICE_NOT_RUNNING)
            })
            .into_response());
    };
    let ws_target = match build_terminal_websocket_target(terminal_url) {
        Ok(ws_target) => ws_target,
        Err(_) => {
            return Ok(websocket_upgrade_with_auth_protocol(ws, &headers)
                .on_upgrade(close_terminal_ws_with_internal_error)
                .into_response());
        }
    };
    let origin = terminal_websocket_origin(terminal_url, &ws_target);
    let session_id = query.session_id.unwrap_or_else(new_terminal_session_id);
    let initial_size = app
        .sandboxes
        .get_terminal_session(&project_id, &session_id)
        .await?
        .map(|session| session.size())
        .unwrap_or_default();
    let recorder = app
        .sandboxes
        .terminal_session_recorder(project_id, session_id.clone());
    Ok(websocket_upgrade_with_auth_protocol(ws, &headers)
        .on_upgrade(move |socket| {
            proxy_terminal_ws_session(
                socket,
                ws_target,
                origin,
                session_id,
                initial_size,
                recorder,
            )
        })
        .into_response())
}

async fn proxy_project_terminal_websocket(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
    Query(query): Query<TerminalWsQuery>,
    headers: HeaderMap,
    ws: WebSocketUpgrade,
) -> SandboxApiResult<Response> {
    proxy_project_terminal_ws_impl(app, identity, project_id, query, headers, ws).await
}

async fn proxy_project_mcp_ws_impl(
    app: AppState,
    identity: Identity,
    project_id: String,
    headers: HeaderMap,
    ws: WebSocketUpgrade,
) -> SandboxApiResult<Response> {
    ensure_project_access(&app, &identity, &project_id).await?;
    let Some(info) = app.sandboxes.get(&project_id).await? else {
        return Ok(websocket_upgrade_with_auth_protocol(ws, &headers)
            .on_upgrade(|socket| close_mcp_ws_with_policy_error(socket, SANDBOX_NOT_FOUND))
            .into_response());
    };
    let Some(mcp_url) = info.websocket_url.as_deref().or(info.endpoint.as_deref()) else {
        return Ok(websocket_upgrade_with_auth_protocol(ws, &headers)
            .on_upgrade(|socket| close_mcp_ws_with_policy_error(socket, MCP_SERVICE_NOT_RUNNING))
            .into_response());
    };
    let ws_target = match build_mcp_websocket_target(mcp_url) {
        Ok(target) => {
            let token = app
                .sandboxes
                .create_mcp_upstream_token(&project_id, &info.sandbox_id)
                .await?;
            append_mcp_upstream_token(&target, &token.token)?
        }
        Err(_) => {
            return Ok(websocket_upgrade_with_auth_protocol(ws, &headers)
                .on_upgrade(close_mcp_ws_with_internal_error)
                .into_response());
        }
    };
    Ok(websocket_upgrade_with_auth_protocol(ws, &headers)
        .on_upgrade(move |socket| proxy_mcp_ws_session(socket, ws_target))
        .into_response())
}

async fn proxy_project_mcp_websocket(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
    headers: HeaderMap,
    ws: WebSocketUpgrade,
) -> SandboxApiResult<Response> {
    proxy_project_mcp_ws_impl(app, identity, project_id, headers, ws).await
}

async fn register_project_http_service(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
    Json(req): Json<RegisterHttpServiceRequest>,
) -> SandboxApiResult<Json<HttpServiceResponse>> {
    ensure_project_access(&app, &identity, &project_id).await?;
    let tenant_id = project_tenant_id(&app, &identity, &project_id).await?;
    let service = app
        .sandboxes
        .register_http_service(&project_id, &tenant_id, req)
        .await?;
    Ok(Json(service.into()))
}

async fn list_project_http_services(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
) -> SandboxApiResult<Json<ListHttpServicesResponse>> {
    ensure_project_access(&app, &identity, &project_id).await?;
    let services = app
        .sandboxes
        .list_http_services(&project_id)
        .await?
        .into_iter()
        .map(HttpServiceResponse::from)
        .collect::<Vec<_>>();
    let total = services.len();
    Ok(Json(ListHttpServicesResponse { services, total }))
}

async fn create_project_http_service_preview_session(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((project_id, service_id)): Path<(String, String)>,
) -> SandboxApiResult<Json<HttpServicePreviewSessionResponse>> {
    ensure_project_access(&app, &identity, &project_id).await?;
    Ok(Json(
        app.sandboxes
            .preview_session(&project_id, &service_id)
            .await?,
    ))
}

async fn stop_project_http_service(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((project_id, service_id)): Path<(String, String)>,
) -> SandboxApiResult<Json<HttpServiceActionResponse>> {
    ensure_project_access(&app, &identity, &project_id).await?;
    let mut removed = app
        .sandboxes
        .remove_http_service(&project_id, &service_id)
        .await?
        .ok_or_else(http_service_not_found)?;
    removed.status = "stopped".to_string();
    removed.updated_at = python_utc_offset_string(now_ms());
    Ok(Json(HttpServiceActionResponse {
        success: true,
        message: format!("HTTP service {service_id} stopped"),
        service: Some(removed.into()),
    }))
}

struct HttpServiceRouteRequest {
    app: AppState,
    identity: Identity,
    raw_key: RawApiKey,
    project_id: String,
    service_id: String,
    path: String,
    raw_query: Option<String>,
    req: Request<Body>,
}

async fn proxy_project_http_service_impl(
    input: HttpServiceRouteRequest,
) -> SandboxApiResult<Response> {
    let HttpServiceRouteRequest {
        app,
        identity,
        raw_key,
        project_id,
        service_id,
        path,
        raw_query,
        req,
    } = input;
    ensure_project_access(&app, &identity, &project_id).await?;
    let service_info = app
        .sandboxes
        .get_http_service(&project_id, &service_id)
        .await?
        .ok_or_else(http_service_not_found)?;
    let method = req.method().clone();
    let headers = req.headers().clone();
    let secure_cookie = proxy_auth_cookie_secure(&headers);
    let body = to_bytes(req.into_body(), HTTP_PROXY_BODY_LIMIT_BYTES)
        .await
        .map_err(|_| SandboxApiError::bad_request("Request body too large"))?
        .to_vec();
    proxy_http_service_response(HttpServiceProxyResponseInput {
        project_id: &project_id,
        service_id: &service_id,
        service_info: &service_info,
        path: &path,
        raw_query: raw_query.as_deref(),
        method,
        request_headers: headers,
        request_body: body,
        raw_key: &raw_key.0,
        secure_cookie,
    })
    .await
}

async fn proxy_project_http_service_root(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Extension(raw_key): Extension<RawApiKey>,
    Path((project_id, service_id)): Path<(String, String)>,
    RawQuery(raw_query): RawQuery,
    req: Request<Body>,
) -> SandboxApiResult<Response> {
    proxy_project_http_service_impl(HttpServiceRouteRequest {
        app,
        identity,
        raw_key,
        project_id,
        service_id,
        path: String::new(),
        raw_query,
        req,
    })
    .await
}

async fn proxy_project_http_service_path(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Extension(raw_key): Extension<RawApiKey>,
    Path((project_id, service_id, path)): Path<(String, String, String)>,
    RawQuery(raw_query): RawQuery,
    req: Request<Body>,
) -> SandboxApiResult<Response> {
    proxy_project_http_service_impl(HttpServiceRouteRequest {
        app,
        identity,
        raw_key,
        project_id,
        service_id,
        path,
        raw_query,
        req,
    })
    .await
}

struct HttpServiceWsRouteRequest {
    app: AppState,
    identity: Identity,
    project_id: String,
    service_id: String,
    path: String,
    raw_query: Option<String>,
    headers: HeaderMap,
    ws: WebSocketUpgrade,
}

async fn proxy_project_http_service_ws_impl(
    input: HttpServiceWsRouteRequest,
) -> SandboxApiResult<Response> {
    let HttpServiceWsRouteRequest {
        app,
        identity,
        project_id,
        service_id,
        path,
        raw_query,
        headers,
        ws,
    } = input;
    ensure_project_access(&app, &identity, &project_id).await?;
    let Some(service_info) = app
        .sandboxes
        .get_http_service(&project_id, &service_id)
        .await?
    else {
        return Ok(websocket_upgrade_with_auth_protocol(ws, &headers)
            .on_upgrade(|socket| {
                close_http_service_ws_with_policy_error(socket, "HTTP service not found")
            })
            .into_response());
    };
    if service_info.source_type != HttpServiceSourceType::SandboxInternal {
        return Ok(websocket_upgrade_with_auth_protocol(ws, &headers)
            .on_upgrade(|socket| {
                close_http_service_ws_with_policy_error(
                    socket,
                    "WebSocket proxy is only available for sandbox_internal services",
                )
            })
            .into_response());
    }

    let ws_target = build_upstream_ws_url(&service_info.service_url, &path, raw_query.as_deref())?;
    let origin = service_info.service_url;
    Ok(websocket_upgrade_with_auth_protocol(ws, &headers)
        .on_upgrade(move |socket| proxy_http_service_ws_session(socket, ws_target, origin))
        .into_response())
}

async fn proxy_project_http_service_ws_root(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((project_id, service_id)): Path<(String, String)>,
    RawQuery(raw_query): RawQuery,
    headers: HeaderMap,
    ws: WebSocketUpgrade,
) -> SandboxApiResult<Response> {
    proxy_project_http_service_ws_impl(HttpServiceWsRouteRequest {
        app,
        identity,
        project_id,
        service_id,
        path: String::new(),
        raw_query,
        headers,
        ws,
    })
    .await
}

async fn proxy_project_http_service_ws_path(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((project_id, service_id, path)): Path<(String, String, String)>,
    RawQuery(raw_query): RawQuery,
    headers: HeaderMap,
    ws: WebSocketUpgrade,
) -> SandboxApiResult<Response> {
    proxy_project_http_service_ws_impl(HttpServiceWsRouteRequest {
        app,
        identity,
        project_id,
        service_id,
        path,
        raw_query,
        headers,
        ws,
    })
    .await
}

async fn restart_project_sandbox(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
) -> SandboxApiResult<Json<SandboxActionResponse>> {
    ensure_project_admin(&app, &identity, &project_id).await?;
    let info = app.sandboxes.restart(&project_id).await?;
    let sandbox_id = info.sandbox_id.clone();
    Ok(Json(SandboxActionResponse {
        success: true,
        message: format!("Sandbox {sandbox_id} restarted successfully"),
        sandbox: Some(info.into()),
    }))
}

async fn terminate_project_sandbox(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
) -> SandboxApiResult<Json<SandboxActionResponse>> {
    ensure_project_admin(&app, &identity, &project_id).await?;
    if !app.sandboxes.terminate(&project_id).await? {
        return Err(SandboxApiError::not_found(SANDBOX_NOT_FOUND));
    }
    Ok(Json(SandboxActionResponse {
        success: true,
        message: "Sandbox terminated successfully".to_string(),
        sandbox: None,
    }))
}

async fn sync_project_sandbox_status(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
) -> SandboxApiResult<Json<ProjectSandboxResponse>> {
    ensure_project_access(&app, &identity, &project_id).await?;
    let info = app
        .sandboxes
        .get(&project_id)
        .await?
        .ok_or_else(|| SandboxApiError::not_found(SANDBOX_NOT_FOUND_WITH_CREATE_HINT))?;
    Ok(Json(info.into()))
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
