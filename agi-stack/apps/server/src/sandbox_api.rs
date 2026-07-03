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
use futures_util::{SinkExt, StreamExt};
use rustls::{
    client::danger::{HandshakeSignatureValid, ServerCertVerified, ServerCertVerifier},
    pki_types::{CertificateDer, ServerName, UnixTime},
    DigitallySignedStruct, Error as RustlsError, SignatureScheme,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};
use tokio_tungstenite::{
    connect_async, connect_async_tls_with_config,
    tungstenite::{
        client::IntoClientRequest,
        protocol::{
            frame::{
                coding::CloseCode as TungsteniteCloseCode, CloseFrame as TungsteniteCloseFrame,
            },
            Message as TungsteniteMessage,
        },
    },
    Connector,
};

use agistack_adapters_postgres::{
    PgProjectReadRepository, PgProjectSandboxRepository, ProjectReadRecord, ProjectSandboxRecord,
};
use agistack_core::ports::{
    ContainerRuntime, ContainerSpec, ContainerState, ContainerStatus, PortBinding, ToolHost,
};

use crate::auth::{Identity, RawApiKey};
use crate::AppState;

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
                if status.is_none() {
                    self.registry.delete(project_id).await?;
                    return Ok(None);
                }
                let mut touched = record;
                touched.last_accessed_at_ms = now_ms();
                let info =
                    ProjectSandboxInfo::from_record(touched, status.expect("status checked"));
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
        TerminalSessionRecorder {
            registry: self.http_registry.clone(),
            project_id,
            session_id,
            ttl_seconds: terminal_session_ttl_seconds(),
        }
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
pub(crate) struct TerminalSessionRecord {
    project_id: String,
    session_id: String,
    cols: u16,
    rows: u16,
    connected: bool,
    last_seen_at_ms: i64,
    expires_at_ms: i64,
}

impl TerminalSessionRecord {
    fn new(
        project_id: String,
        session_id: String,
        size: TerminalSize,
        connected: bool,
        now_ms: i64,
        ttl_seconds: i64,
    ) -> Self {
        Self {
            project_id,
            session_id,
            cols: size.cols,
            rows: size.rows,
            connected,
            last_seen_at_ms: now_ms,
            expires_at_ms: now_ms + ttl_seconds.max(1) * 1000,
        }
    }

    fn size(&self) -> TerminalSize {
        TerminalSize {
            cols: self.cols.max(1),
            rows: self.rows.max(1),
        }
    }
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

fn build_desktop_websocket_target(desktop_url: &str) -> SandboxApiResult<String> {
    let desktop_base = normalize_desktop_upstream_base(desktop_url);
    let mut url = url::Url::parse(&desktop_base)
        .map_err(|_| SandboxApiError::bad_request("Invalid desktop service URL"))?;
    let scheme = match url.scheme() {
        "http" => "ws",
        "https" => "wss",
        "ws" => "ws",
        "wss" => "wss",
        _ => return Err(SandboxApiError::bad_request("Invalid desktop service URL")),
    };
    url.set_scheme(scheme)
        .map_err(|_| SandboxApiError::bad_request("Invalid desktop service URL"))?;
    let base_path = url.path().trim_end_matches('/');
    let final_path = if base_path.is_empty() || base_path == "/" {
        "/websockify".to_string()
    } else {
        format!("{base_path}/websockify")
    };
    url.set_path(&final_path);
    url.set_query(None);
    Ok(url.to_string())
}

fn desktop_websocket_origin(desktop_url: &str, ws_target: &str) -> String {
    match url::Url::parse(ws_target).map(|url| url.scheme() == "wss") {
        Ok(true) => normalize_desktop_upstream_base(desktop_url),
        _ => desktop_url.to_string(),
    }
}

fn build_terminal_websocket_target(terminal_url: &str) -> SandboxApiResult<String> {
    let mut url = url::Url::parse(terminal_url)
        .map_err(|_| SandboxApiError::bad_request("Invalid terminal service URL"))?;
    let scheme = match url.scheme() {
        "http" => "ws",
        "https" => "wss",
        "ws" => "ws",
        "wss" => "wss",
        _ => return Err(SandboxApiError::bad_request("Invalid terminal service URL")),
    };
    url.set_scheme(scheme)
        .map_err(|_| SandboxApiError::bad_request("Invalid terminal service URL"))?;
    url.set_query(None);
    Ok(url.to_string())
}

fn terminal_websocket_origin(terminal_url: &str, ws_target: &str) -> String {
    match url::Url::parse(ws_target).map(|url| url.scheme() == "wss") {
        Ok(true) => terminal_url
            .strip_prefix("ws://")
            .map(|rest| format!("https://{rest}"))
            .unwrap_or_else(|| terminal_url.to_string()),
        _ => terminal_url.to_string(),
    }
}

fn build_mcp_websocket_target(mcp_url: &str) -> SandboxApiResult<String> {
    let url = url::Url::parse(mcp_url)
        .map_err(|_| SandboxApiError::bad_request("Invalid MCP service URL"))?;
    match url.scheme() {
        "ws" | "wss" => Ok(url.to_string()),
        _ => Err(SandboxApiError::bad_request("Invalid MCP service URL")),
    }
}

fn append_mcp_upstream_token(ws_target: &str, token: &str) -> SandboxApiResult<String> {
    let mut url = url::Url::parse(ws_target)
        .map_err(|_| SandboxApiError::bad_request("Invalid MCP service URL"))?;
    let existing: Vec<(String, String)> = url
        .query_pairs()
        .filter(|(key, _)| key != MCP_UPSTREAM_TOKEN_QUERY_PARAM)
        .map(|(key, value)| (key.into_owned(), value.into_owned()))
        .collect();
    url.set_query(None);
    {
        let mut pairs = url.query_pairs_mut();
        for (key, value) in existing {
            pairs.append_pair(&key, &value);
        }
        pairs.append_pair(MCP_UPSTREAM_TOKEN_QUERY_PARAM, token);
    }
    Ok(url.to_string())
}

fn normalize_mcp_resource_mime_type(message: &str) -> String {
    let Ok(mut data) = serde_json::from_str::<Value>(message) else {
        return message.to_string();
    };
    let mut modified = false;
    if let Some(contents) = data
        .get_mut("result")
        .and_then(Value::as_object_mut)
        .and_then(|result| result.get_mut("contents"))
        .and_then(Value::as_array_mut)
    {
        for item in contents {
            let Some(item) = item.as_object_mut() else {
                continue;
            };
            let is_plain_html = item
                .get("mimeType")
                .and_then(Value::as_str)
                .map(str::trim)
                .is_some_and(|mime| mime.eq_ignore_ascii_case("text/html"));
            if is_plain_html {
                item.insert(
                    "mimeType".to_string(),
                    Value::String(MCP_APP_MIME_TYPE.to_string()),
                );
                modified = true;
            }
        }
    }
    if modified {
        data.to_string()
    } else {
        message.to_string()
    }
}

fn new_terminal_session_id() -> String {
    agistack_adapters_secrets::generate_uuid_v4()
        .replace('-', "")
        .chars()
        .take(12)
        .collect()
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct TerminalSize {
    cols: u16,
    rows: u16,
}

impl Default for TerminalSize {
    fn default() -> Self {
        Self {
            cols: TERMINAL_DEFAULT_COLS,
            rows: TERMINAL_DEFAULT_ROWS,
        }
    }
}

impl TerminalSize {
    fn update(self, cols: Option<u16>, rows: Option<u16>) -> Self {
        Self {
            cols: cols.unwrap_or(self.cols).max(1),
            rows: rows.unwrap_or(self.rows).max(1),
        }
    }
}

fn terminal_connected_message(session_id: &str, size: TerminalSize) -> String {
    json!({
        "type": "connected",
        "session_id": session_id,
        "cols": size.cols,
        "rows": size.rows,
    })
    .to_string()
}

fn terminal_output_message(data: &str) -> String {
    json!({
        "type": "output",
        "data": data,
    })
    .to_string()
}

fn terminal_error_message() -> String {
    json!({
        "type": "error",
        "message": "Terminal WebSocket proxy failed",
    })
    .to_string()
}

fn ttyd_initial_terminal_message(size: TerminalSize) -> TungsteniteMessage {
    TungsteniteMessage::Binary(
        json!({
            "AuthToken": "",
            "columns": size.cols,
            "rows": size.rows,
        })
        .to_string()
        .into_bytes(),
    )
}

fn ttyd_input_message(data: &[u8]) -> TungsteniteMessage {
    let mut payload = Vec::with_capacity(data.len() + 1);
    payload.push(TTYD_INPUT_COMMAND);
    payload.extend_from_slice(data);
    TungsteniteMessage::Binary(payload)
}

fn ttyd_resize_message(size: TerminalSize) -> TungsteniteMessage {
    let mut payload = Vec::with_capacity(32);
    payload.push(TTYD_RESIZE_COMMAND);
    payload.extend_from_slice(
        json!({
            "columns": size.cols,
            "rows": size.rows,
        })
        .to_string()
        .as_bytes(),
    );
    TungsteniteMessage::Binary(payload)
}

fn ttyd_output_payload(data: &[u8]) -> Option<String> {
    let (&command, payload) = data.split_first()?;
    match command {
        TTYD_INPUT_COMMAND => Some(String::from_utf8_lossy(payload).to_string()),
        TTYD_RESIZE_COMMAND | TTYD_PREFERENCES_COMMAND => None,
        _ => Some(String::from_utf8_lossy(data).to_string()),
    }
}

fn build_upstream_ws_url(
    base_url: &str,
    path: &str,
    raw_query: Option<&str>,
) -> SandboxApiResult<String> {
    let mut url = url::Url::parse(base_url)
        .map_err(|_| SandboxApiError::bad_request("Invalid HTTP service URL"))?;
    let scheme = if url.scheme() == "https" { "wss" } else { "ws" };
    url.set_scheme(scheme)
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

fn build_upstream_preview_ws_url(
    base_url: &str,
    path: &str,
    raw_query: Option<&str>,
) -> SandboxApiResult<String> {
    let mut url = url::Url::parse(base_url)
        .map_err(|_| SandboxApiError::bad_request("Invalid HTTP service URL"))?;
    let scheme = if url.scheme() == "https" { "wss" } else { "ws" };
    url.set_scheme(scheme)
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

async fn proxy_project_desktop_response(
    project_id: &str,
    info: &ProjectSandboxInfo,
    path: &str,
    raw_query: Option<&str>,
    request_headers: HeaderMap,
    secure_cookie: bool,
) -> SandboxApiResult<Response> {
    let desktop_url = info.desktop_url.as_deref().ok_or_else(|| {
        SandboxApiError::new(StatusCode::SERVICE_UNAVAILABLE, DESKTOP_SERVICE_NOT_RUNNING)
    })?;
    let target_url = build_upstream_desktop_http_url(desktop_url, path, raw_query)?;
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(30))
        .redirect(reqwest::redirect::Policy::none())
        .danger_accept_invalid_certs(true)
        .no_proxy()
        .build()
        .map_err(|_| SandboxApiError::bad_gateway("Failed to connect to desktop service"))?;
    let upstream = client
        .get(target_url)
        .headers(filter_desktop_proxy_headers(&request_headers))
        .send()
        .await
        .map_err(|_| SandboxApiError::bad_gateway("Failed to connect to desktop service"))?;

    let status = StatusCode::from_u16(upstream.status().as_u16())
        .unwrap_or(StatusCode::INTERNAL_SERVER_ERROR);
    let upstream_headers = upstream.headers().clone();
    let content_type = upstream_headers
        .get(CONTENT_TYPE)
        .cloned()
        .unwrap_or_else(|| HeaderValue::from_static("application/octet-stream"));
    let content_type_str = content_type.to_str().unwrap_or("application/octet-stream");
    let token_param = proxy_token_from_query(raw_query);
    let body = upstream
        .bytes()
        .await
        .map_err(|_| SandboxApiError::bad_gateway("Failed to connect to desktop service"))?;
    let body = rewrite_desktop_content(&body, content_type_str, project_id, &token_param);

    let mut response = (status, body).into_response();
    response.headers_mut().insert(CONTENT_TYPE, content_type);
    if !token_param.is_empty() {
        response.headers_mut().append(
            SET_COOKIE,
            sandbox_proxy_auth_cookie(project_id, &token_param, secure_cookie)?,
        );
        response.headers_mut().append(
            SET_COOKIE,
            desktop_proxy_token_cookie(project_id, &token_param)?,
        );
    }
    Ok(response)
}

async fn proxy_http_service_response(
    project_id: &str,
    service_id: &str,
    service_info: &HttpServiceProxyInfo,
    path: &str,
    raw_query: Option<&str>,
    method: Method,
    request_headers: HeaderMap,
    request_body: Vec<u8>,
    raw_key: &str,
    secure_cookie: bool,
) -> SandboxApiResult<Response> {
    if service_info.source_type != HttpServiceSourceType::SandboxInternal {
        return Err(SandboxApiError::bad_request(
            "HTTP proxy is only available for sandbox_internal services",
        ));
    }
    let target_url = build_upstream_http_url(&service_info.service_url, path, raw_query)?;
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(3))
        .redirect(reqwest::redirect::Policy::none())
        .danger_accept_invalid_certs(true)
        .no_proxy()
        .build()
        .map_err(|_| SandboxApiError::bad_gateway("Failed to connect to HTTP service"))?;
    let upstream = client
        .request(method, target_url)
        .headers(filter_proxy_headers(&request_headers))
        .body(request_body)
        .send()
        .await
        .map_err(|_| SandboxApiError::bad_gateway("Failed to connect to HTTP service"))?;

    let status = StatusCode::from_u16(upstream.status().as_u16())
        .unwrap_or(StatusCode::INTERNAL_SERVER_ERROR);
    let upstream_headers = upstream.headers().clone();
    let content_type = upstream_headers
        .get(CONTENT_TYPE)
        .cloned()
        .unwrap_or_else(|| HeaderValue::from_static("application/octet-stream"));
    let content_type_str = content_type.to_str().unwrap_or("application/octet-stream");
    let token_param = raw_query
        .and_then(|query| {
            url::form_urlencoded::parse(query.as_bytes())
                .find(|(key, _)| key == PROXY_TOKEN_QUERY_PARAM)
                .map(|(_, value)| value.into_owned())
        })
        .unwrap_or_default();
    let body = upstream
        .bytes()
        .await
        .map_err(|_| SandboxApiError::bad_gateway("Failed to connect to HTTP service"))?;
    let body = rewrite_http_service_content(
        &body,
        content_type_str,
        project_id,
        service_id,
        &token_param,
    );

    let mut response = (status, body).into_response();
    response.headers_mut().insert(CONTENT_TYPE, content_type);
    if let Some(cache_control) = upstream_headers.get(CACHE_CONTROL) {
        response
            .headers_mut()
            .insert(CACHE_CONTROL, cache_control.clone());
    }
    if let Some(location) = upstream_headers
        .get(LOCATION)
        .and_then(|value| value.to_str().ok())
    {
        let rewritten = rewrite_http_service_location(
            location,
            project_id,
            service_id,
            &token_param,
            &service_info.service_url,
        );
        let header = HeaderValue::from_str(&rewritten)
            .map_err(|_| SandboxApiError::bad_gateway("Failed to connect to HTTP service"))?;
        response.headers_mut().insert(LOCATION, header);
    }

    response.headers_mut().append(
        SET_COOKIE,
        sandbox_proxy_auth_cookie(project_id, raw_key, secure_cookie)?,
    );
    response.headers_mut().append(
        SET_COOKIE,
        desktop_token_cookie(project_id, service_id, raw_key)?,
    );
    Ok(response)
}

async fn proxy_http_service_preview_host_response(
    sandboxes: &ProjectSandboxService,
    host_header: &str,
    path: &str,
    raw_query: Option<&str>,
    method: Method,
    request_headers: HeaderMap,
    request_body: Vec<u8>,
) -> SandboxApiResult<Response> {
    let (project_id, service_label) = parse_http_preview_host(host_header)
        .ok_or_else(|| SandboxApiError::not_found("Not found"))?;
    let service_info = sandboxes
        .get_http_service_by_preview_label(&project_id, &service_label)
        .await?
        .ok_or_else(http_service_not_found)?;
    if service_info.source_type != HttpServiceSourceType::SandboxInternal {
        return Err(SandboxApiError::bad_request(
            "HTTP preview host is only available for sandbox_internal services",
        ));
    }

    let query_token = preview_session_token_from_query(raw_query);
    let cookie_token = extract_cookie_value(&request_headers, PREVIEW_SESSION_COOKIE_NAME);
    let session_token = query_token.as_deref().or(cookie_token.as_deref());
    let session = sandboxes
        .preview_session_matches_service(session_token, &project_id, &service_info.service_id)
        .await?
        .ok_or_else(|| {
            SandboxApiError::new(
                StatusCode::UNAUTHORIZED,
                "Preview session is missing or expired",
            )
        })?;

    if let Some(query_token) = query_token {
        let mut response = (StatusCode::FOUND, Body::empty()).into_response();
        let location = HeaderValue::from_str(&clean_preview_session_path(path, raw_query))
            .map_err(|_| SandboxApiError::internal("Failed to set preview redirect location"))?;
        response.headers_mut().insert(LOCATION, location);
        response.headers_mut().append(
            SET_COOKIE,
            preview_session_cookie(
                &query_token,
                &session,
                proxy_auth_cookie_secure(&request_headers),
            )?,
        );
        return Ok(response);
    }

    let target_url = build_upstream_preview_http_url(&service_info.service_url, path, raw_query)?;
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(3))
        .redirect(reqwest::redirect::Policy::none())
        .danger_accept_invalid_certs(true)
        .no_proxy()
        .build()
        .map_err(|_| SandboxApiError::bad_gateway("Failed to connect to HTTP service"))?;
    let upstream = client
        .request(method, target_url)
        .headers(filter_proxy_headers(&request_headers))
        .body(request_body)
        .send()
        .await
        .map_err(|_| SandboxApiError::bad_gateway("Failed to connect to HTTP service"))?;

    let status = StatusCode::from_u16(upstream.status().as_u16())
        .unwrap_or(StatusCode::INTERNAL_SERVER_ERROR);
    let upstream_headers = upstream.headers().clone();
    let content_type = upstream_headers
        .get(CONTENT_TYPE)
        .cloned()
        .unwrap_or_else(|| HeaderValue::from_static("application/octet-stream"));
    let body = upstream
        .bytes()
        .await
        .map_err(|_| SandboxApiError::bad_gateway("Failed to connect to HTTP service"))?;

    let mut response = (status, body).into_response();
    response.headers_mut().insert(CONTENT_TYPE, content_type);
    if let Some(cache_control) = upstream_headers.get(CACHE_CONTROL) {
        response
            .headers_mut()
            .insert(CACHE_CONTROL, cache_control.clone());
    }
    if let Some(location) = upstream_headers
        .get(LOCATION)
        .and_then(|value| value.to_str().ok())
    {
        let rewritten = rewrite_http_service_host_location(
            location,
            request_scheme_from_headers(&request_headers),
            host_header,
            &service_info.service_url,
        );
        let header = HeaderValue::from_str(&rewritten)
            .map_err(|_| SandboxApiError::bad_gateway("Failed to connect to HTTP service"))?;
        response.headers_mut().insert(LOCATION, header);
    }
    Ok(response)
}

async fn proxy_http_service_preview_host_ws_response(
    sandboxes: &ProjectSandboxService,
    host_header: &str,
    path: &str,
    raw_query: Option<&str>,
    headers: HeaderMap,
    ws: WebSocketUpgrade,
) -> Response {
    let upgrade = websocket_upgrade_with_auth_protocol(ws, &headers);
    let Some((project_id, service_label)) = parse_http_preview_host(host_header) else {
        return upgrade
            .on_upgrade(|socket| {
                close_http_service_ws_with_policy_error(socket, "Not a preview host")
            })
            .into_response();
    };
    let service_info = match sandboxes
        .get_http_service_by_preview_label(&project_id, &service_label)
        .await
    {
        Ok(Some(service_info)) => service_info,
        Ok(None) => {
            return upgrade
                .on_upgrade(|socket| {
                    close_http_service_ws_with_policy_error(socket, "HTTP service not found")
                })
                .into_response();
        }
        Err(_) => {
            return upgrade
                .on_upgrade(close_http_preview_host_ws_with_internal_error)
                .into_response();
        }
    };
    if service_info.source_type != HttpServiceSourceType::SandboxInternal {
        return upgrade
            .on_upgrade(|socket| {
                close_http_service_ws_with_policy_error(
                    socket,
                    "HTTP preview host WS proxy is only available for sandbox_internal services",
                )
            })
            .into_response();
    }

    let query_token = preview_session_token_from_query(raw_query);
    let cookie_token = extract_cookie_value(&headers, PREVIEW_SESSION_COOKIE_NAME);
    let session_token = query_token.as_deref().or(cookie_token.as_deref());
    let session_matches = sandboxes
        .preview_session_matches_service(session_token, &project_id, &service_info.service_id)
        .await
        .ok()
        .flatten()
        .is_some();
    if !session_matches {
        return upgrade
            .on_upgrade(|socket| {
                close_http_service_ws_with_policy_error(
                    socket,
                    "Preview session is missing or expired",
                )
            })
            .into_response();
    }

    let ws_target = match build_upstream_preview_ws_url(&service_info.service_url, path, raw_query)
    {
        Ok(ws_target) => ws_target,
        Err(_) => {
            return upgrade
                .on_upgrade(close_http_preview_host_ws_with_internal_error)
                .into_response();
        }
    };
    let origin = request_origin_from_headers(&headers, &service_info.service_url);
    upgrade
        .on_upgrade(move |socket| proxy_http_service_ws_session(socket, ws_target, origin))
        .into_response()
}

pub(crate) async fn preview_host_proxy(
    State(app): State<AppState>,
    ws: Option<WebSocketUpgrade>,
    method: Method,
    uri: Uri,
    headers: HeaderMap,
    req: Request<Body>,
) -> Response {
    let path = uri.path().to_string();
    let raw_query = uri.query().map(str::to_string);
    let host_header = headers
        .get("host")
        .and_then(|value| value.to_str().ok())
        .unwrap_or_default()
        .to_string();
    if let Some(ws) = ws {
        return proxy_http_service_preview_host_ws_response(
            &app.sandboxes,
            &host_header,
            &path,
            raw_query.as_deref(),
            headers,
            ws,
        )
        .await;
    }

    let body = match to_bytes(req.into_body(), HTTP_PROXY_BODY_LIMIT_BYTES).await {
        Ok(body) => body.to_vec(),
        Err(_) => return SandboxApiError::bad_request("Request body too large").into_response(),
    };
    proxy_http_service_preview_host_response(
        &app.sandboxes,
        &host_header,
        &path,
        raw_query.as_deref(),
        method,
        headers,
        body,
    )
    .await
    .unwrap_or_else(IntoResponse::into_response)
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

#[derive(Debug)]
struct NoDesktopCertificateVerification;

impl ServerCertVerifier for NoDesktopCertificateVerification {
    fn verify_server_cert(
        &self,
        _end_entity: &CertificateDer<'_>,
        _intermediates: &[CertificateDer<'_>],
        _server_name: &ServerName<'_>,
        _ocsp_response: &[u8],
        _now: UnixTime,
    ) -> Result<ServerCertVerified, RustlsError> {
        Ok(ServerCertVerified::assertion())
    }

    fn verify_tls12_signature(
        &self,
        _message: &[u8],
        _cert: &CertificateDer<'_>,
        _dss: &DigitallySignedStruct,
    ) -> Result<HandshakeSignatureValid, RustlsError> {
        Ok(HandshakeSignatureValid::assertion())
    }

    fn verify_tls13_signature(
        &self,
        _message: &[u8],
        _cert: &CertificateDer<'_>,
        _dss: &DigitallySignedStruct,
    ) -> Result<HandshakeSignatureValid, RustlsError> {
        Ok(HandshakeSignatureValid::assertion())
    }

    fn supported_verify_schemes(&self) -> Vec<SignatureScheme> {
        vec![
            SignatureScheme::RSA_PKCS1_SHA256,
            SignatureScheme::RSA_PKCS1_SHA384,
            SignatureScheme::RSA_PKCS1_SHA512,
            SignatureScheme::RSA_PSS_SHA256,
            SignatureScheme::RSA_PSS_SHA384,
            SignatureScheme::RSA_PSS_SHA512,
            SignatureScheme::ECDSA_NISTP256_SHA256,
            SignatureScheme::ECDSA_NISTP384_SHA384,
            SignatureScheme::ED25519,
        ]
    }
}

fn desktop_ws_tls_connector() -> Connector {
    let config = rustls::ClientConfig::builder_with_provider(
        rustls::crypto::aws_lc_rs::default_provider().into(),
    )
    .with_safe_default_protocol_versions()
    .expect("rustls default protocol versions are valid")
    .dangerous()
    .with_custom_certificate_verifier(Arc::new(NoDesktopCertificateVerification))
    .with_no_client_auth();
    Connector::Rustls(Arc::new(config))
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

async fn proxy_mcp_ws_session(socket: WebSocket, ws_target: String) {
    let request = match ws_target.into_client_request() {
        Ok(request) => request,
        Err(_) => {
            close_mcp_ws_with_internal_error(socket).await;
            return;
        }
    };

    let upstream = match tokio::time::timeout(Duration::from_secs(10), connect_async(request)).await
    {
        Ok(Ok((stream, _response))) => stream,
        _ => {
            close_mcp_ws_with_internal_error(socket).await;
            return;
        }
    };

    let (mut client_tx, mut client_rx) = socket.split();
    let (mut upstream_tx, mut upstream_rx) = upstream.split();

    loop {
        tokio::select! {
            incoming = client_rx.next() => {
                let Some(Ok(message)) = incoming else {
                    let _ = upstream_tx.close().await;
                    break;
                };
                let should_close = matches!(message, AxumWsMessage::Close(_));
                if upstream_tx.send(axum_ws_to_tungstenite(message)).await.is_err() {
                    break;
                }
                if should_close {
                    break;
                }
            }
            incoming = upstream_rx.next() => {
                let Some(message) = incoming else {
                    let _ = client_tx
                        .send(AxumWsMessage::Close(Some(AxumCloseFrame {
                            code: 1001,
                            reason: "Upstream disconnected".into(),
                        })))
                        .await;
                    break;
                };
                match message {
                    Ok(TungsteniteMessage::Text(text)) => {
                        let normalized = normalize_mcp_resource_mime_type(&text);
                        if client_tx
                            .send(AxumWsMessage::Text(normalized))
                            .await
                            .is_err()
                        {
                            break;
                        }
                    }
                    Ok(message) => {
                        let should_close = matches!(message, TungsteniteMessage::Close(_));
                        if let Some(message) = tungstenite_ws_to_axum(message) {
                            if client_tx.send(message).await.is_err() {
                                break;
                            }
                        }
                        if should_close {
                            break;
                        }
                    }
                    Err(_) => {
                        let _ = client_tx
                            .send(AxumWsMessage::Text(
                                json!({ "error": "MCP WebSocket proxy failed" }).to_string(),
                            ))
                            .await;
                        let _ = client_tx
                            .send(AxumWsMessage::Close(Some(AxumCloseFrame {
                                code: 1011,
                                reason: "MCP WebSocket proxy failure".into(),
                            })))
                            .await;
                        break;
                    }
                }
            }
        }
    }
}

async fn proxy_http_service_ws_session(socket: WebSocket, ws_target: String, origin: String) {
    let mut request = match ws_target.into_client_request() {
        Ok(request) => request,
        Err(_) => {
            close_http_service_ws_with_internal_error(socket).await;
            return;
        }
    };
    let origin = match HeaderValue::from_str(&origin) {
        Ok(origin) => origin,
        Err(_) => {
            close_http_service_ws_with_internal_error(socket).await;
            return;
        }
    };
    request.headers_mut().insert("origin", origin);

    let upstream = match tokio::time::timeout(Duration::from_secs(10), connect_async(request)).await
    {
        Ok(Ok((stream, _response))) => stream,
        _ => {
            close_http_service_ws_with_internal_error(socket).await;
            return;
        }
    };
    pump_http_service_websockets(socket, upstream).await;
}

#[derive(Debug, Deserialize)]
struct TerminalClientWsMessage {
    #[serde(rename = "type")]
    kind: String,
    data: Option<String>,
    cols: Option<u16>,
    rows: Option<u16>,
}

#[derive(Clone)]
struct TerminalSessionRecorder {
    registry: SharedHttpServiceRegistry,
    project_id: String,
    session_id: String,
    ttl_seconds: i64,
}

impl TerminalSessionRecorder {
    async fn store(&self, size: TerminalSize, connected: bool) -> SandboxApiResult<()> {
        let now = now_ms();
        let record = TerminalSessionRecord::new(
            self.project_id.clone(),
            self.session_id.clone(),
            size,
            connected,
            now,
            self.ttl_seconds,
        );
        self.registry
            .upsert_terminal_session(record, self.ttl_seconds)
            .await
    }
}

async fn proxy_terminal_ws_session(
    socket: WebSocket,
    ws_target: String,
    origin: String,
    session_id: String,
    initial_size: TerminalSize,
    recorder: TerminalSessionRecorder,
) {
    let mut request = match ws_target.into_client_request() {
        Ok(request) => request,
        Err(_) => {
            close_terminal_ws_with_internal_error(socket).await;
            return;
        }
    };
    let origin = match HeaderValue::from_str(&origin) {
        Ok(origin) => origin,
        Err(_) => {
            close_terminal_ws_with_internal_error(socket).await;
            return;
        }
    };
    request.headers_mut().insert("origin", origin);

    let upstream = match tokio::time::timeout(Duration::from_secs(10), connect_async(request)).await
    {
        Ok(Ok((stream, _response))) => stream,
        _ => {
            close_terminal_ws_with_internal_error(socket).await;
            return;
        }
    };

    let (mut client_tx, mut client_rx) = socket.split();
    let (mut upstream_tx, mut upstream_rx) = upstream.split();
    let mut terminal_size = initial_size;
    if recorder.store(terminal_size, true).await.is_err() {
        let _ = client_tx
            .send(AxumWsMessage::Text(terminal_error_message()))
            .await;
        let _ = client_tx
            .send(AxumWsMessage::Close(Some(AxumCloseFrame {
                code: 1011,
                reason: "Terminal WebSocket proxy failure".into(),
            })))
            .await;
        let _ = upstream_tx.close().await;
        return;
    }
    if upstream_tx
        .send(ttyd_initial_terminal_message(terminal_size))
        .await
        .is_err()
    {
        let _ = client_tx
            .send(AxumWsMessage::Text(terminal_error_message()))
            .await;
        let _ = client_tx
            .send(AxumWsMessage::Close(Some(AxumCloseFrame {
                code: 1011,
                reason: "Terminal WebSocket proxy failure".into(),
            })))
            .await;
        return;
    }
    if client_tx
        .send(AxumWsMessage::Text(terminal_connected_message(
            &session_id,
            terminal_size,
        )))
        .await
        .is_err()
    {
        let _ = upstream_tx.close().await;
        return;
    }

    loop {
        tokio::select! {
            incoming = client_rx.next() => {
                let Some(Ok(message)) = incoming else {
                    let _ = upstream_tx.close().await;
                    break;
                };
                match message {
                    AxumWsMessage::Text(text) => {
                        let parsed = serde_json::from_str::<TerminalClientWsMessage>(&text);
                        let Ok(message) = parsed else {
                            let _ = client_tx
                                .send(AxumWsMessage::Text(terminal_error_message()))
                                .await;
                            let _ = client_tx
                                .send(AxumWsMessage::Close(Some(AxumCloseFrame {
                                    code: 1011,
                                    reason: "Terminal WebSocket proxy failure".into(),
                                })))
                                .await;
                            let _ = upstream_tx.close().await;
                            break;
                        };
                        match message.kind.as_str() {
                            "input" => {
                                let data = message.data.unwrap_or_default();
                                if upstream_tx
                                    .send(ttyd_input_message(data.as_bytes()))
                                    .await
                                    .is_err()
                                {
                                    break;
                                }
                            }
                            "resize" => {
                                terminal_size = terminal_size.update(message.cols, message.rows);
                                if upstream_tx
                                    .send(ttyd_resize_message(terminal_size))
                                    .await
                                    .is_err()
                                {
                                    break;
                                }
                                if recorder.store(terminal_size, true).await.is_err() {
                                    let _ = client_tx
                                        .send(AxumWsMessage::Text(terminal_error_message()))
                                        .await;
                                    let _ = client_tx
                                        .send(AxumWsMessage::Close(Some(AxumCloseFrame {
                                            code: 1011,
                                            reason: "Terminal WebSocket proxy failure".into(),
                                        })))
                                        .await;
                                    let _ = upstream_tx.close().await;
                                    break;
                                }
                            }
                            "ping"
                                if client_tx
                                    .send(AxumWsMessage::Text(
                                        json!({ "type": "pong" }).to_string(),
                                    ))
                                    .await
                                    .is_err() =>
                            {
                                break;
                            }
                            "ping" => {}
                            _ => {}
                        }
                    }
                    AxumWsMessage::Binary(binary) => {
                        if upstream_tx
                            .send(ttyd_input_message(binary.as_ref()))
                            .await
                            .is_err()
                        {
                            break;
                        }
                    }
                    AxumWsMessage::Ping(payload) => {
                        let _ = upstream_tx.send(TungsteniteMessage::Ping(payload)).await;
                    }
                    AxumWsMessage::Pong(payload) => {
                        let _ = upstream_tx.send(TungsteniteMessage::Pong(payload)).await;
                    }
                    AxumWsMessage::Close(close) => {
                        let _ = upstream_tx
                            .send(axum_ws_to_tungstenite(AxumWsMessage::Close(close)))
                            .await;
                        break;
                    }
                }
            }
            upstream = upstream_rx.next() => {
                let Some(message) = upstream else {
                    let _ = client_tx
                        .send(AxumWsMessage::Close(Some(AxumCloseFrame {
                            code: 1000,
                            reason: "Terminal upstream closed".into(),
                        })))
                        .await;
                    break;
                };
                match message {
                    Ok(TungsteniteMessage::Text(text)) => {
                        if let Some(output) = ttyd_output_payload(text.as_bytes()) {
                            if client_tx
                                .send(AxumWsMessage::Text(terminal_output_message(&output)))
                                .await
                                .is_err()
                            {
                                break;
                            }
                        }
                    }
                    Ok(TungsteniteMessage::Binary(binary)) => {
                        if let Some(output) = ttyd_output_payload(binary.as_ref()) {
                            if client_tx
                                .send(AxumWsMessage::Text(terminal_output_message(&output)))
                                .await
                                .is_err()
                            {
                                break;
                            }
                        }
                    }
                    Ok(TungsteniteMessage::Ping(payload)) => {
                        let _ = upstream_tx.send(TungsteniteMessage::Pong(payload)).await;
                    }
                    Ok(TungsteniteMessage::Pong(_)) => {}
                    Ok(TungsteniteMessage::Close(close)) => {
                        if let Some(close) =
                            tungstenite_ws_to_axum(TungsteniteMessage::Close(close))
                        {
                            let _ = client_tx.send(close).await;
                        }
                        break;
                    }
                    Ok(TungsteniteMessage::Frame(_)) => {}
                    Err(_) => {
                        let _ = client_tx
                            .send(AxumWsMessage::Text(terminal_error_message()))
                            .await;
                        let _ = client_tx
                            .send(AxumWsMessage::Close(Some(AxumCloseFrame {
                                code: 1011,
                                reason: "Terminal WebSocket proxy failure".into(),
                            })))
                            .await;
                        break;
                    }
                }
            }
        }
    }
    let _ = recorder.store(terminal_size, false).await;
}

async fn proxy_desktop_ws_session(socket: WebSocket, ws_target: String, origin: String) {
    let is_tls_target = match url::Url::parse(&ws_target) {
        Ok(url) => url.scheme() == "wss",
        Err(_) => {
            close_desktop_ws_with_internal_error(socket).await;
            return;
        }
    };
    let mut request = match ws_target.into_client_request() {
        Ok(request) => request,
        Err(_) => {
            close_desktop_ws_with_internal_error(socket).await;
            return;
        }
    };
    let origin = match HeaderValue::from_str(&origin) {
        Ok(origin) => origin,
        Err(_) => {
            close_desktop_ws_with_internal_error(socket).await;
            return;
        }
    };
    request.headers_mut().insert("origin", origin);
    request.headers_mut().insert(
        "sec-websocket-protocol",
        HeaderValue::from_static(DESKTOP_WEBSOCKET_SUBPROTOCOL),
    );

    let connect = async {
        if is_tls_target {
            connect_async_tls_with_config(request, None, false, Some(desktop_ws_tls_connector()))
                .await
        } else {
            connect_async(request).await
        }
    };
    let upstream = match tokio::time::timeout(Duration::from_secs(10), connect).await {
        Ok(Ok((stream, _response))) => stream,
        _ => {
            close_desktop_ws_with_internal_error(socket).await;
            return;
        }
    };
    pump_http_service_websockets(socket, upstream).await;
}

async fn pump_http_service_websockets(
    mut client: WebSocket,
    mut upstream: tokio_tungstenite::WebSocketStream<
        tokio_tungstenite::MaybeTlsStream<tokio::net::TcpStream>,
    >,
) {
    loop {
        tokio::select! {
            incoming = client.recv() => {
                let Some(Ok(message)) = incoming else {
                    let _ = upstream.close(None).await;
                    break;
                };
                let should_close = matches!(message, AxumWsMessage::Close(_));
                if upstream.send(axum_ws_to_tungstenite(message)).await.is_err() {
                    break;
                }
                if should_close {
                    break;
                }
            }
            incoming = upstream.next() => {
                let Some(Ok(message)) = incoming else {
                    let _ = client.send(AxumWsMessage::Close(None)).await;
                    break;
                };
                let should_close = matches!(message, TungsteniteMessage::Close(_));
                if let Some(message) = tungstenite_ws_to_axum(message) {
                    if client.send(message).await.is_err() {
                        break;
                    }
                }
                if should_close {
                    break;
                }
            }
        }
    }
}

fn axum_ws_to_tungstenite(message: AxumWsMessage) -> TungsteniteMessage {
    match message {
        AxumWsMessage::Text(text) => TungsteniteMessage::Text(text),
        AxumWsMessage::Binary(binary) => TungsteniteMessage::Binary(binary),
        AxumWsMessage::Ping(ping) => TungsteniteMessage::Ping(ping),
        AxumWsMessage::Pong(pong) => TungsteniteMessage::Pong(pong),
        AxumWsMessage::Close(Some(close)) => {
            TungsteniteMessage::Close(Some(TungsteniteCloseFrame {
                code: TungsteniteCloseCode::from(close.code),
                reason: close.reason,
            }))
        }
        AxumWsMessage::Close(None) => TungsteniteMessage::Close(None),
    }
}

fn tungstenite_ws_to_axum(message: TungsteniteMessage) -> Option<AxumWsMessage> {
    match message {
        TungsteniteMessage::Text(text) => Some(AxumWsMessage::Text(text)),
        TungsteniteMessage::Binary(binary) => Some(AxumWsMessage::Binary(binary)),
        TungsteniteMessage::Ping(ping) => Some(AxumWsMessage::Ping(ping)),
        TungsteniteMessage::Pong(pong) => Some(AxumWsMessage::Pong(pong)),
        TungsteniteMessage::Close(Some(close)) => {
            Some(AxumWsMessage::Close(Some(AxumCloseFrame {
                code: close.code.into(),
                reason: close.reason,
            })))
        }
        TungsteniteMessage::Close(None) => Some(AxumWsMessage::Close(None)),
        TungsteniteMessage::Frame(_) => None,
    }
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

async fn proxy_project_http_service_impl(
    app: AppState,
    identity: Identity,
    raw_key: RawApiKey,
    project_id: String,
    service_id: String,
    path: String,
    raw_query: Option<String>,
    req: Request<Body>,
) -> SandboxApiResult<Response> {
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
    proxy_http_service_response(
        &project_id,
        &service_id,
        &service_info,
        &path,
        raw_query.as_deref(),
        method,
        headers,
        body,
        &raw_key.0,
        secure_cookie,
    )
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
    proxy_project_http_service_impl(
        app,
        identity,
        raw_key,
        project_id,
        service_id,
        String::new(),
        raw_query,
        req,
    )
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
    proxy_project_http_service_impl(
        app, identity, raw_key, project_id, service_id, path, raw_query, req,
    )
    .await
}

async fn proxy_project_http_service_ws_impl(
    app: AppState,
    identity: Identity,
    project_id: String,
    service_id: String,
    path: String,
    raw_query: Option<String>,
    headers: HeaderMap,
    ws: WebSocketUpgrade,
) -> SandboxApiResult<Response> {
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
    proxy_project_http_service_ws_impl(
        app,
        identity,
        project_id,
        service_id,
        String::new(),
        raw_query,
        headers,
        ws,
    )
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
    proxy_project_http_service_ws_impl(
        app, identity, project_id, service_id, path, raw_query, headers, ws,
    )
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
mod tests {
    use super::*;
    use agistack_adapters_mem::InMemoryContainerRuntime;
    use agistack_core::ports::CoreResult;

    #[derive(Default)]
    struct StaticConfigSource {
        configs: Mutex<BTreeMap<String, ProjectSandboxConfig>>,
    }

    #[async_trait]
    impl ProjectSandboxConfigSource for StaticConfigSource {
        async fn get_project_sandbox_config(
            &self,
            project_id: &str,
        ) -> SandboxApiResult<Option<ProjectSandboxConfig>> {
            Ok(self
                .configs
                .lock()
                .map_err(|_| SandboxApiError::internal("config source mutex poisoned"))?
                .get(project_id)
                .cloned())
        }
    }

    #[derive(Default)]
    struct RecordingRuntime {
        calls: Mutex<Vec<String>>,
    }

    impl RecordingRuntime {
        fn call_count(&self) -> usize {
            self.calls.lock().unwrap().len()
        }
    }

    #[async_trait]
    impl ContainerRuntime for RecordingRuntime {
        async fn create(&self, _spec: &ContainerSpec) -> CoreResult<String> {
            self.calls.lock().unwrap().push("create".to_string());
            Ok("unexpected-container".to_string())
        }

        async fn start(&self, id: &str) -> CoreResult<()> {
            self.calls.lock().unwrap().push(format!("start:{id}"));
            Ok(())
        }

        async fn status(&self, id: &str) -> CoreResult<Option<ContainerStatus>> {
            self.calls.lock().unwrap().push(format!("status:{id}"));
            Ok(None)
        }

        async fn stop(&self, id: &str) -> CoreResult<()> {
            self.calls.lock().unwrap().push(format!("stop:{id}"));
            Ok(())
        }

        async fn remove(&self, id: &str) -> CoreResult<()> {
            self.calls.lock().unwrap().push(format!("remove:{id}"));
            Ok(())
        }

        async fn list(&self, _label: Option<(&str, &str)>) -> CoreResult<Vec<String>> {
            self.calls.lock().unwrap().push("list".to_string());
            Ok(Vec::new())
        }
    }

    struct RecordingConnector {
        urls: Mutex<Vec<String>>,
        output: String,
    }

    #[async_trait]
    impl SandboxToolConnector for RecordingConnector {
        async fn connect_tool_host(&self, url: &str) -> SandboxApiResult<Arc<dyn ToolHost>> {
            self.urls
                .lock()
                .map_err(|_| SandboxApiError::internal("recording connector mutex poisoned"))?
                .push(url.to_string());
            Ok(Arc::new(StaticToolHost {
                output: self.output.clone(),
            }))
        }
    }

    struct StaticToolHost {
        output: String,
    }

    #[async_trait]
    impl ToolHost for StaticToolHost {
        fn list_tools(&self) -> Vec<String> {
            vec!["bash".to_string()]
        }

        async fn call(&self, _tool: &str, _input_json: &str) -> CoreResult<String> {
            Ok(self.output.clone())
        }
    }

    #[tokio::test]
    async fn service_ensure_get_restart_and_terminate_lifecycle() {
        let service =
            ProjectSandboxService::new(Arc::new(InMemoryContainerRuntime::new()), "redis:7-alpine");

        assert!(service.get("p1").await.unwrap().is_none());

        let created = service
            .ensure("p1", "t1", Some(SandboxProfile::Lite))
            .await
            .unwrap();
        assert_eq!(created.project_id, "p1");
        assert_eq!(created.tenant_id, "t1");
        assert_eq!(created.profile, SandboxProfile::Lite);
        assert_eq!(created.status_str(), "running");
        assert!(created.healthy());

        let fetched = service.get("p1").await.unwrap().unwrap();
        assert_eq!(fetched.sandbox_id, created.sandbox_id);

        let restarted = service.restart("p1").await.unwrap();
        assert_eq!(restarted.sandbox_id, created.sandbox_id);
        assert_eq!(restarted.status_str(), "running");

        assert!(service.terminate("p1").await.unwrap());
        assert!(!service.terminate("p1").await.unwrap());
        assert!(service.get("p1").await.unwrap().is_none());
    }

    #[tokio::test]
    async fn service_ensure_local_tunnel_from_project_config_without_container_runtime() {
        let mut configs = BTreeMap::new();
        configs.insert(
            "p-local".to_string(),
            ProjectSandboxConfig {
                sandbox_type: "local".to_string(),
                local_config: json!({
                    "workspace_path": "/Users/me/workspace",
                    "tunnel_url": "wss://local.example/mcp?trace=1",
                    "host": "localhost",
                    "port": 19001,
                    "auth_token": "local-secret"
                }),
            },
        );
        let config_source = Arc::new(StaticConfigSource {
            configs: Mutex::new(configs),
        });
        let runtime = Arc::new(RecordingRuntime::default());
        let service = ProjectSandboxService::new(runtime.clone(), "redis:7-alpine")
            .with_project_config_source(config_source);

        let created = service
            .ensure("p-local", "t1", Some(SandboxProfile::Full))
            .await
            .unwrap();

        assert_eq!(created.sandbox_id, "local-p-local");
        assert_eq!(created.project_id, "p-local");
        assert_eq!(created.tenant_id, "t1");
        assert_eq!(created.sandbox_type, "local");
        assert_eq!(created.status_str(), "running");
        assert!(created.healthy());
        assert_eq!(created.mcp_port, Some(19001));
        assert_eq!(
            created.endpoint.as_deref(),
            Some("wss://local.example/mcp?trace=1&token=local-secret")
        );
        assert_eq!(created.endpoint, created.websocket_url);
        assert_eq!(runtime.call_count(), 0);

        let fetched = service.get("p-local").await.unwrap().unwrap();
        assert_eq!(fetched.sandbox_id, created.sandbox_id);
        assert_eq!(fetched.endpoint, created.endpoint);
        assert_eq!(runtime.call_count(), 0);

        let restarted = service.restart("p-local").await.unwrap();
        assert_eq!(restarted.status_str(), "running");
        assert_eq!(runtime.call_count(), 0);

        assert!(service.terminate("p-local").await.unwrap());
        assert!(service.get("p-local").await.unwrap().is_none());
        assert_eq!(runtime.call_count(), 0);
    }

    #[tokio::test]
    async fn service_lists_sandboxes_by_tenant_and_status() {
        let service =
            ProjectSandboxService::new(Arc::new(InMemoryContainerRuntime::new()), "redis:7-alpine");
        service
            .ensure("p1", "t1", Some(SandboxProfile::Lite))
            .await
            .unwrap();
        service
            .ensure("p2", "t1", Some(SandboxProfile::Standard))
            .await
            .unwrap();
        service
            .ensure("p3", "t2", Some(SandboxProfile::Full))
            .await
            .unwrap();

        let t1 = service.list("t1", None, 50, 0).await.unwrap();
        assert_eq!(t1.len(), 2);
        assert!(t1.iter().all(|sandbox| sandbox.tenant_id == "t1"));

        let running = service.list("t1", Some("running"), 50, 0).await.unwrap();
        assert_eq!(running.len(), 2);

        let stopped = service.list("t1", Some("stopped"), 50, 0).await.unwrap();
        assert!(stopped.is_empty());

        let page = service.list("t1", None, 1, 1).await.unwrap();
        assert_eq!(page.len(), 1);
    }

    #[tokio::test]
    async fn service_terminal_sessions_are_durable_for_resume() {
        let service =
            ProjectSandboxService::new(Arc::new(InMemoryContainerRuntime::new()), "redis:7-alpine");
        let session = service.create_terminal_session("p1").await.unwrap();
        assert_eq!(session.project_id, "p1");
        assert!(!session.session_id.is_empty());
        assert_eq!(session.size(), TerminalSize::default());
        assert!(!session.connected);

        let recorder = service.terminal_session_recorder("p1".into(), session.session_id.clone());
        recorder
            .store(
                TerminalSize {
                    cols: 132,
                    rows: 43,
                },
                true,
            )
            .await
            .unwrap();

        let restored = service
            .get_terminal_session("p1", &session.session_id)
            .await
            .unwrap()
            .unwrap();
        assert!(restored.connected);
        assert_eq!(
            restored.size(),
            TerminalSize {
                cols: 132,
                rows: 43,
            }
        );
    }

    #[tokio::test]
    async fn service_executes_tool_and_matches_python_wire_shape() {
        let host = StaticToolHost {
            output: json!({
                "content": [{ "type": "text", "text": "ok" }],
                "isError": false
            })
            .to_string(),
        };
        let service =
            ProjectSandboxService::new(Arc::new(InMemoryContainerRuntime::new()), "redis:7-alpine")
                .with_tool_host(Arc::new(host));
        service
            .ensure("p1", "t1", Some(SandboxProfile::Lite))
            .await
            .unwrap();

        let response = service
            .execute_tool("p1", "bash", &json!({ "cmd": "echo ok" }), 30.0)
            .await
            .unwrap();

        assert!(response.success);
        assert!(!response.is_error);
        assert_eq!(response.content[0]["text"], "ok");
        let execute_golden: serde_json::Value =
            serde_json::from_str(include_str!("../tests/golden/project_sandbox_execute.json"))
                .unwrap();
        agistack_parity::assert_parity(&execute_golden, &serde_json::to_value(&response).unwrap());
    }

    #[tokio::test]
    async fn service_prefers_record_mcp_endpoint_for_tool_execution() {
        let registry = Arc::new(InMemorySandboxRegistry::new());
        let connector = Arc::new(RecordingConnector {
            urls: Mutex::new(Vec::new()),
            output: json!({
                "content": [{ "type": "text", "text": "from mcp" }],
                "isError": false
            })
            .to_string(),
        });
        let fallback = StaticToolHost {
            output: json!({
                "content": [{ "type": "text", "text": "from fallback" }],
                "isError": false
            })
            .to_string(),
        };
        let service = ProjectSandboxService::with_registry(
            Arc::new(InMemoryContainerRuntime::new()),
            "redis:7-alpine",
            registry.clone(),
        )
        .with_tool_host(Arc::new(fallback))
        .with_tool_connector(connector.clone());
        service
            .ensure("p1", "t1", Some(SandboxProfile::Lite))
            .await
            .unwrap();
        let mut record = registry.get("p1").await.unwrap().unwrap();
        record.metadata_json = json!({
            "profile": "lite",
            "endpoint": "ws://sandbox-mcp.test:8765"
        });
        registry.save(&record, "running", None).await.unwrap();

        let response = service
            .execute_tool("p1", "bash", &json!({ "cmd": "pwd" }), 30.0)
            .await
            .unwrap();

        assert_eq!(response.content[0]["text"], "from mcp");
        assert_eq!(
            connector.urls.lock().unwrap().as_slice(),
            &["ws://sandbox-mcp.test:8765"]
        );
    }

    #[test]
    fn profile_validation_matches_python_enum_values() {
        assert_eq!(
            SandboxProfile::parse(Some("LITE")).unwrap(),
            Some(SandboxProfile::Lite)
        );
        assert_eq!(
            SandboxProfile::parse(Some("standard")).unwrap(),
            Some(SandboxProfile::Standard)
        );
        assert_eq!(
            SandboxProfile::parse(Some("full")).unwrap(),
            Some(SandboxProfile::Full)
        );
        assert!(SandboxProfile::parse(Some("gpu")).is_err());
        assert_eq!(
            parse_status_filter(Some("CONNECTING")).unwrap(),
            Some("connecting".to_string())
        );
        assert!(parse_status_filter(Some("gpu")).is_err());
    }

    #[test]
    fn sandbox_router_builds_with_http_service_proxy_routes() {
        let _ = router();
    }

    fn sample_info() -> ProjectSandboxInfo {
        ProjectSandboxInfo {
            sandbox_id: "s1".to_string(),
            project_id: "p1".to_string(),
            tenant_id: "t1".to_string(),
            sandbox_type: "cloud".to_string(),
            profile: SandboxProfile::Standard,
            state: ContainerState::Running,
            exit_code: None,
            created_at_ms: 0,
            started_at_ms: Some(0),
            last_accessed_at_ms: 0,
            metadata_json: json!({ "profile": "standard" }),
            local_config: json!({}),
            endpoint: None,
            websocket_url: None,
            mcp_port: None,
            desktop_port: None,
            terminal_port: None,
            desktop_url: None,
            terminal_url: None,
        }
    }

    #[test]
    fn response_keeps_python_wire_fields_and_null_proxy_urls() {
        let response = ProjectSandboxResponse::from(sample_info());
        assert_eq!(response.status, "running");
        assert!(response.is_healthy);
        assert_eq!(response.created_at.as_deref(), Some("1970-01-01T00:00:00Z"));
        assert_eq!(response.endpoint, None);
        assert_eq!(response.websocket_url, None);
        assert_eq!(response.mcp_port, None);
        assert_eq!(response.desktop_url, None);
        assert_eq!(response.terminal_url, None);

        let golden: serde_json::Value = serde_json::from_str(include_str!(
            "../tests/golden/project_sandbox_response.json"
        ))
        .unwrap();
        let actual = serde_json::to_value(&response).unwrap();
        agistack_parity::assert_parity(&golden, &actual);
    }

    #[test]
    fn response_surfaces_persisted_mcp_connection_fields() {
        let mut info = sample_info();
        info.endpoint = Some("ws://localhost:18765".to_string());
        info.websocket_url = Some("ws://localhost:18765".to_string());
        info.mcp_port = Some(18765);
        let response = ProjectSandboxResponse::from(info);
        assert_eq!(response.endpoint.as_deref(), Some("ws://localhost:18765"));
        assert_eq!(
            response.websocket_url.as_deref(),
            Some("ws://localhost:18765")
        );
        assert_eq!(response.mcp_port, Some(18765));
    }

    #[test]
    fn runtime_ports_are_projected_into_python_connection_fields() {
        let record = SandboxRecord::new(
            "s1".to_string(),
            "p1".to_string(),
            "t1".to_string(),
            SandboxProfile::Standard,
            0,
        );
        let info = ProjectSandboxInfo::from_record(
            record,
            ContainerStatus {
                id: "s1".to_string(),
                state: ContainerState::Running,
                running: true,
                exit_code: None,
                ports: vec![
                    PortBinding {
                        container_port: MCP_CONTAINER_PORT,
                        host_port: 18765,
                        host_ip: Some("127.0.0.1".to_string()),
                    },
                    PortBinding {
                        container_port: DESKTOP_CONTAINER_PORT,
                        host_port: 16080,
                        host_ip: Some("127.0.0.1".to_string()),
                    },
                    PortBinding {
                        container_port: TERMINAL_CONTAINER_PORT,
                        host_port: 17681,
                        host_ip: Some("127.0.0.1".to_string()),
                    },
                ],
            },
        );
        let response = ProjectSandboxResponse::from(info);
        assert_eq!(response.mcp_port, Some(18765));
        assert_eq!(response.endpoint.as_deref(), Some("ws://localhost:18765"));
        assert_eq!(response.desktop_port, Some(16080));
        assert_eq!(
            response.desktop_url.as_deref(),
            Some("https://localhost:16080")
        );
        assert_eq!(response.terminal_port, Some(17681));
        assert_eq!(
            response.terminal_url.as_deref(),
            Some("ws://localhost:17681")
        );
    }

    #[test]
    fn interactive_control_responses_match_python_wire_shape() {
        let mut info = sample_info();
        info.desktop_url = Some("https://localhost:16080".to_string());
        info.desktop_port = Some(16080);
        info.terminal_url = Some("ws://localhost:17681".to_string());
        info.terminal_port = Some(17681);

        let desktop =
            DesktopServiceResponse::from_info(&info, DESKTOP_DEFAULT_RESOLUTION.to_string());
        assert!(desktop.success);
        assert_eq!(desktop.url.as_deref(), Some("https://localhost:16080"));
        assert_eq!(desktop.display.as_str(), DESKTOP_DEFAULT_DISPLAY);
        assert_eq!(desktop.resolution.as_str(), DESKTOP_DEFAULT_RESOLUTION);
        assert_eq!(desktop.port, 16080);
        assert!(!desktop.audio_enabled);
        assert!(desktop.dynamic_resize);
        assert_eq!(desktop.encoding.as_str(), DESKTOP_DEFAULT_ENCODING);
        let desktop_golden: serde_json::Value = serde_json::from_str(include_str!(
            "../tests/golden/project_sandbox_desktop_start.json"
        ))
        .unwrap();
        agistack_parity::assert_parity(&desktop_golden, &serde_json::to_value(&desktop).unwrap());

        let custom_desktop = DesktopServiceResponse::from_info(&info, "1280x720".to_string());
        assert_eq!(custom_desktop.resolution, "1280x720");

        let terminal =
            TerminalServiceResponse::from_info_with_session(&info, Some("term-abc123".into()));
        assert!(terminal.success);
        assert_eq!(terminal.url.as_deref(), Some("ws://localhost:17681"));
        assert_eq!(terminal.port, 17681);
        assert_eq!(terminal.session_id.as_deref(), Some("term-abc123"));
        let terminal_golden: serde_json::Value = serde_json::from_str(include_str!(
            "../tests/golden/project_sandbox_terminal_start.json"
        ))
        .unwrap();
        agistack_parity::assert_parity(&terminal_golden, &serde_json::to_value(&terminal).unwrap());

        let stop = SandboxServiceStopResponse { success: true };
        let stop_golden: serde_json::Value = serde_json::from_str(include_str!(
            "../tests/golden/project_sandbox_service_stop.json"
        ))
        .unwrap();
        agistack_parity::assert_parity(&stop_golden, &serde_json::to_value(&stop).unwrap());

        let missing = sample_info();
        assert!(
            !DesktopServiceResponse::from_info(&missing, DESKTOP_DEFAULT_RESOLUTION.to_string())
                .success
        );
        assert!(!TerminalServiceResponse::from_info(&missing).success);
    }

    #[test]
    fn http_service_control_responses_match_python_wire_shape() {
        let service = HttpServiceProxyInfo {
            service_id: "web".to_string(),
            name: "Docs".to_string(),
            source_type: HttpServiceSourceType::SandboxInternal,
            status: "running".to_string(),
            service_url: "http://127.0.0.1:3000/docs".to_string(),
            preview_url: "http://web.p1.preview.localhost:8000/".to_string(),
            ws_preview_url: Some("ws://web.p1.preview.localhost:8000/".to_string()),
            sandbox_id: Some("s1".to_string()),
            auto_open: true,
            restart_token: Some("1700000000000".to_string()),
            updated_at: "1970-01-01T00:00:00.000+00:00".to_string(),
        };

        let response = HttpServiceResponse::from(service.clone());
        let golden: serde_json::Value = serde_json::from_str(include_str!(
            "../tests/golden/project_sandbox_http_service_response.json"
        ))
        .unwrap();
        agistack_parity::assert_parity(&golden, &serde_json::to_value(&response).unwrap());

        let list = ListHttpServicesResponse {
            services: vec![HttpServiceResponse::from(service.clone())],
            total: 1,
        };
        let list_golden: serde_json::Value = serde_json::from_str(include_str!(
            "../tests/golden/project_sandbox_http_services_list.json"
        ))
        .unwrap();
        agistack_parity::assert_parity(&list_golden, &serde_json::to_value(&list).unwrap());

        let mut stopped = service;
        stopped.status = "stopped".to_string();
        let action = HttpServiceActionResponse {
            success: true,
            message: "HTTP service web stopped".to_string(),
            service: Some(HttpServiceResponse::from(stopped)),
        };
        let action_golden: serde_json::Value = serde_json::from_str(include_str!(
            "../tests/golden/project_sandbox_http_service_action.json"
        ))
        .unwrap();
        agistack_parity::assert_parity(&action_golden, &serde_json::to_value(&action).unwrap());

        let preview = HttpServicePreviewSessionResponse {
            preview_url: append_query_param(
                "http://web.p1.preview.localhost:8000/",
                PREVIEW_SESSION_QUERY_PARAM,
                &agistack_adapters_secrets::generate_urlsafe_token(32),
            ),
            expires_in_seconds: 86_400,
        };
        let preview_golden: serde_json::Value = serde_json::from_str(include_str!(
            "../tests/golden/project_sandbox_http_service_preview_session.json"
        ))
        .unwrap();
        agistack_parity::assert_parity(&preview_golden, &serde_json::to_value(&preview).unwrap());

        assert_eq!(normalize_http_service_id(Some(" web:1 ")).unwrap(), "web:1");
        assert!(normalize_http_service_id(Some("bad/id")).is_err());
        assert_eq!(normalize_path_prefix("docs"), "/docs");
        assert!(validate_external_http_url("https://example.test/app").is_ok());
        assert!(validate_external_http_url("ftp://example.test/app").is_err());
    }

    #[tokio::test]
    async fn service_registers_lists_previews_and_stops_http_services() {
        let service =
            ProjectSandboxService::new(Arc::new(InMemoryContainerRuntime::new()), "redis:7-alpine");

        let registered = service
            .register_http_service(
                "p1",
                "t1",
                RegisterHttpServiceRequest {
                    service_id: Some("web".to_string()),
                    name: "Docs".to_string(),
                    source_type: HttpServiceSourceType::SandboxInternal,
                    internal_port: Some(3000),
                    internal_scheme: "http".to_string(),
                    path_prefix: "docs".to_string(),
                    external_url: None,
                    auto_open: true,
                },
            )
            .await
            .unwrap();
        assert_eq!(registered.service_id, "web");
        assert_eq!(registered.sandbox_id.as_deref(), Some("mem-000000"));
        assert_eq!(registered.service_url, "http://127.0.0.1:3000/docs");
        assert_eq!(
            registered.preview_url,
            build_http_preview_proxy_url("p1", "web")
        );
        assert_eq!(
            registered.ws_preview_url.as_deref(),
            Some(build_http_preview_ws_proxy_url("p1", "web").as_str())
        );

        let listed = service.list_http_services("p1").await.unwrap();
        assert_eq!(listed.len(), 1);
        assert_eq!(listed[0].service_id, "web");

        let preview = service.preview_session("p1", "web").await.unwrap();
        assert_eq!(preview.expires_in_seconds, preview_session_ttl_seconds());
        assert!(preview
            .preview_url
            .starts_with(&build_http_preview_proxy_url("p1", "web")));
        assert!(preview
            .preview_url
            .contains(&format!("{PREVIEW_SESSION_QUERY_PARAM}=")));

        let removed = service
            .remove_http_service("p1", "web")
            .await
            .unwrap()
            .unwrap();
        assert_eq!(removed.service_id, "web");
        assert!(service.list_http_services("p1").await.unwrap().is_empty());
        assert!(matches!(
            service.preview_session("p1", "web").await,
            Err(SandboxApiError {
                status: StatusCode::NOT_FOUND,
                ..
            })
        ));

        let external = service
            .register_http_service(
                "p1",
                "t1",
                RegisterHttpServiceRequest {
                    service_id: Some("external".to_string()),
                    name: "External".to_string(),
                    source_type: HttpServiceSourceType::ExternalUrl,
                    internal_port: None,
                    internal_scheme: "http".to_string(),
                    path_prefix: "/".to_string(),
                    external_url: Some("https://example.test/app".to_string()),
                    auto_open: false,
                },
            )
            .await
            .unwrap();
        assert_eq!(external.preview_url, "https://example.test/app");
        let external_preview = service.preview_session("p1", "external").await.unwrap();
        assert_eq!(external_preview.preview_url, "https://example.test/app");
        assert_eq!(external_preview.expires_in_seconds, 0);
    }

    #[test]
    fn http_service_proxy_helpers_match_python_path_contract() {
        assert_eq!(
            build_http_path_preview_proxy_url("p1", "web"),
            "/api/v1/projects/p1/sandbox/http-services/web/proxy/"
        );
        assert_eq!(
            build_http_path_preview_ws_proxy_url("p1", "web"),
            "/api/v1/projects/p1/sandbox/http-services/web/proxy/ws/"
        );
        assert_eq!(
            filter_proxy_query(Some("token=ms_sk_secret&q=hello+world&empty=")).as_deref(),
            Some("q=hello+world&empty=")
        );
        assert_eq!(
            build_upstream_http_url(
                "http://127.0.0.1:3000/docs",
                "assets/app.js",
                Some("token=ms_sk_secret&q=hello+world")
            )
            .unwrap(),
            "http://127.0.0.1:3000/docs/assets/app.js?q=hello+world"
        );
        assert_eq!(
            build_upstream_ws_url(
                "https://example.test/docs",
                "socket",
                Some("token=ms_sk_secret&q=hello+world")
            )
            .unwrap(),
            "wss://example.test/docs/socket?q=hello+world"
        );
        assert_eq!(
            build_upstream_preview_ws_url(
                "https://example.test/docs",
                "socket",
                Some("ms_preview_session=secret&q=hello+world")
            )
            .unwrap(),
            "wss://example.test/docs/socket?q=hello+world"
        );
        assert_eq!(
            parse_http_preview_host("web.p1.preview.localhost:8000"),
            Some(("p1".to_string(), "web".to_string()))
        );
        assert_eq!(parse_http_preview_host("web.p1.other.localhost:8000"), None);
        assert_eq!(
            filter_preview_host_query(Some("ms_preview_session=secret&q=hello+world&empty="))
                .as_deref(),
            Some("q=hello+world&empty=")
        );
        assert_eq!(
            build_upstream_preview_http_url(
                "http://127.0.0.1:3000/docs",
                "assets/app.js",
                Some("ms_preview_session=secret&q=hello+world")
            )
            .unwrap(),
            "http://127.0.0.1:3000/docs/assets/app.js?q=hello+world"
        );
        assert_eq!(
            rewrite_http_service_host_location(
                "http://127.0.0.1:3000/docs/login?next=%2F",
                "https",
                "web.p1.preview.localhost:8000",
                "http://127.0.0.1:3000/docs",
            ),
            "https://web.p1.preview.localhost:8000/docs/login?next=%2F"
        );

        let mut headers = HeaderMap::new();
        headers.insert(
            "authorization",
            HeaderValue::from_static("Bearer ms_sk_secret"),
        );
        headers.insert("cookie", HeaderValue::from_static("a=b"));
        headers.insert("x-trace-id", HeaderValue::from_static("trace-1"));
        headers.insert(
            "sec-websocket-protocol",
            HeaderValue::from_static("ms_sk_secret, memstack.auth"),
        );
        let filtered = filter_proxy_headers(&headers);
        assert!(!filtered.contains_key("authorization"));
        assert!(!filtered.contains_key("cookie"));
        assert_eq!(
            filtered
                .get("x-trace-id")
                .and_then(|value| value.to_str().ok()),
            Some("trace-1")
        );
        assert_eq!(
            select_websocket_auth_subprotocol(&headers),
            Some(WEBSOCKET_AUTH_SUBPROTOCOL)
        );
        assert_eq!(
            request_origin_from_headers(&headers, "http://127.0.0.1:3000"),
            "http://127.0.0.1:3000"
        );
        headers.insert("origin", HeaderValue::from_static("https://frontend.test"));
        assert_eq!(
            request_origin_from_headers(&headers, "http://127.0.0.1:3000"),
            "https://frontend.test"
        );

        let rewritten = rewrite_http_service_location(
            "http://127.0.0.1:3000/docs/login?next=%2F",
            "p1",
            "web",
            "ms_sk_secret",
            "http://127.0.0.1:3000/docs",
        );
        assert_eq!(
            rewritten,
            "/api/v1/projects/p1/sandbox/http-services/web/proxy/docs/login?next=%2F&token=ms_sk_secret"
        );
        assert_eq!(
            rewrite_http_service_location(
                "https://other.test/login",
                "p1",
                "web",
                "ms_sk_secret",
                "http://127.0.0.1:3000/docs",
            ),
            "https://other.test/login"
        );

        let body = br#"<link href="/assets/app.css"><script>fetch('/api/data');new WebSocket('/socket')</script>"#;
        let rewritten = rewrite_http_service_content(
            body,
            "text/html; charset=utf-8",
            "p1",
            "web",
            "ms_sk_secret",
        );
        let rewritten = String::from_utf8(rewritten).unwrap();
        assert!(rewritten.contains(
            r#"href="/api/v1/projects/p1/sandbox/http-services/web/proxy/assets/app.css?token=ms_sk_secret""#
        ));
        assert!(rewritten.contains(
            r#"fetch('/api/v1/projects/p1/sandbox/http-services/web/proxy/api/data?token=ms_sk_secret'"#
        ));
        assert!(rewritten.contains(
            r#"new WebSocket('/api/v1/projects/p1/sandbox/http-services/web/proxy/ws/socket?token=ms_sk_secret'"#
        ));
    }

    #[test]
    fn desktop_proxy_helpers_match_python_path_contract() {
        assert_eq!(
            build_desktop_path_proxy_url("p1"),
            "/api/v1/projects/p1/sandbox/desktop/proxy/"
        );
        assert_eq!(
            build_desktop_websockify_proxy_url("p1"),
            "/api/v1/projects/p1/sandbox/desktop/proxy/websockify"
        );
        assert_eq!(
            normalize_desktop_upstream_base("http://127.0.0.1:6080"),
            "https://127.0.0.1:6080"
        );
        assert_eq!(
            build_upstream_desktop_http_url(
                "http://127.0.0.1:6080/vnc",
                "index.html",
                Some("token=ms_sk_secret&q=hello+world")
            )
            .unwrap(),
            "https://127.0.0.1:6080/vnc/index.html?q=hello+world"
        );
        assert_eq!(
            build_desktop_websocket_target("http://127.0.0.1:6080/vnc").unwrap(),
            "wss://127.0.0.1:6080/vnc/websockify"
        );
        assert_eq!(
            build_desktop_websocket_target("https://localhost:6080").unwrap(),
            "wss://localhost:6080/websockify"
        );
        assert_eq!(
            build_desktop_websocket_target("ws://127.0.0.1:6080/base").unwrap(),
            "ws://127.0.0.1:6080/base/websockify"
        );
        assert_eq!(
            desktop_websocket_origin("http://127.0.0.1:6080", "wss://127.0.0.1:6080/websockify"),
            "https://127.0.0.1:6080"
        );
        assert_eq!(
            desktop_websocket_origin(
                "ws://127.0.0.1:6080/base",
                "ws://127.0.0.1:6080/base/websockify"
            ),
            "ws://127.0.0.1:6080/base"
        );
        assert_eq!(
            build_terminal_websocket_target("ws://127.0.0.1:7681?token=ms_sk_secret").unwrap(),
            "ws://127.0.0.1:7681/"
        );
        assert_eq!(
            build_terminal_websocket_target("https://127.0.0.1:7681/terminal").unwrap(),
            "wss://127.0.0.1:7681/terminal"
        );
        assert_eq!(
            terminal_websocket_origin(
                "https://127.0.0.1:7681/terminal",
                "wss://127.0.0.1:7681/terminal"
            ),
            "https://127.0.0.1:7681/terminal"
        );
        assert_eq!(
            build_mcp_websocket_target("ws://127.0.0.1:8765/mcp/sandbox?auth=keep").unwrap(),
            "ws://127.0.0.1:8765/mcp/sandbox?auth=keep"
        );
        assert!(build_mcp_websocket_target("http://127.0.0.1:8765/mcp").is_err());

        let mut headers = HeaderMap::new();
        headers.insert(ACCEPT, HeaderValue::from_static("text/html"));
        headers.insert(ACCEPT_ENCODING, HeaderValue::from_static("gzip"));
        headers.insert(ACCEPT_LANGUAGE, HeaderValue::from_static("en-US"));
        headers.insert(CACHE_CONTROL, HeaderValue::from_static("no-cache"));
        headers.insert(
            "authorization",
            HeaderValue::from_static("Bearer ms_sk_secret"),
        );
        headers.insert("cookie", HeaderValue::from_static("a=b"));
        headers.insert("x-trace-id", HeaderValue::from_static("trace-1"));
        let filtered = filter_desktop_proxy_headers(&headers);
        assert_eq!(
            filtered.get(ACCEPT).and_then(|value| value.to_str().ok()),
            Some("text/html")
        );
        assert_eq!(
            filtered
                .get(ACCEPT_ENCODING)
                .and_then(|value| value.to_str().ok()),
            Some("gzip")
        );
        assert_eq!(
            filtered
                .get(ACCEPT_LANGUAGE)
                .and_then(|value| value.to_str().ok()),
            Some("en-US")
        );
        assert_eq!(
            filtered
                .get(CACHE_CONTROL)
                .and_then(|value| value.to_str().ok()),
            Some("no-cache")
        );
        assert!(!filtered.contains_key("authorization"));
        assert!(!filtered.contains_key("cookie"));
        assert!(!filtered.contains_key("x-trace-id"));

        let cookie = desktop_proxy_token_cookie("p1", "ms_sk_secret").unwrap();
        assert_eq!(
            cookie.to_str().unwrap(),
            "desktop_token=ms_sk_secret; HttpOnly; SameSite=Strict; Max-Age=86400; Path=/api/v1/projects/p1/sandbox/desktop/proxy"
        );

        let body = br#"<link href="/assets/app.css"><script src="/app.js"></script><script>const ws = "ws://" + location.host + "/"; const wss = "wss://" + location.host + "/";</script>"#;
        let rewritten =
            rewrite_desktop_content(body, "text/html; charset=utf-8", "p1", "ms_sk_secret");
        let rewritten = String::from_utf8(rewritten).unwrap();
        assert!(rewritten.contains(
            r#"href="/api/v1/projects/p1/sandbox/desktop/proxy/assets/app.css?token=ms_sk_secret""#
        ));
        assert!(rewritten.contains(
            r#"src="/api/v1/projects/p1/sandbox/desktop/proxy/app.js?token=ms_sk_secret""#
        ));
        assert!(rewritten.contains(
            r#"ws://" + location.host + "/api/v1/projects/p1/sandbox/desktop/proxy/websockify?token=ms_sk_secret""#
        ));
        assert!(rewritten.contains(
            r#"wss://" + location.host + "/api/v1/projects/p1/sandbox/desktop/proxy/websockify?token=ms_sk_secret""#
        ));

        let css = br#"body { background: url("/wall.png"); }"#;
        assert_eq!(
            rewrite_desktop_content(css, "text/css", "p1", "ms_sk_secret"),
            css
        );
    }

    #[test]
    fn mcp_upstream_token_replaces_stale_query_token() {
        let target =
            build_mcp_websocket_target("ws://127.0.0.1:8765/mcp/sandbox?auth=keep&token=old&q=1")
                .unwrap();
        let signed = append_mcp_upstream_token(&target, "fresh-token").unwrap();
        let url = url::Url::parse(&signed).unwrap();
        let params: Vec<(String, String)> = url
            .query_pairs()
            .map(|(key, value)| (key.into_owned(), value.into_owned()))
            .collect();

        assert_eq!(url.path(), "/mcp/sandbox");
        assert_eq!(
            params,
            vec![
                ("auth".to_string(), "keep".to_string()),
                ("q".to_string(), "1".to_string()),
                ("token".to_string(), "fresh-token".to_string()),
            ]
        );
    }

    #[test]
    fn mcp_proxy_normalizes_html_resource_mime_type() {
        let response = json!({
            "jsonrpc": "2.0",
            "id": 7,
            "result": {
                "contents": [
                    {"uri": "ui://index.html", "mimeType": "text/html", "text": "<html></html>"},
                    {"uri": "ui://style.css", "mimeType": "text/css", "text": "body{}"}
                ]
            }
        })
        .to_string();
        let normalized = normalize_mcp_resource_mime_type(&response);
        let parsed: Value = serde_json::from_str(&normalized).unwrap();
        assert_eq!(
            parsed["result"]["contents"][0]["mimeType"],
            MCP_APP_MIME_TYPE
        );
        assert_eq!(parsed["result"]["contents"][1]["mimeType"], "text/css");

        let passthrough = r#"{"jsonrpc":"2.0","method":"tools/list"}"#;
        assert_eq!(normalize_mcp_resource_mime_type(passthrough), passthrough);
    }

    #[tokio::test]
    async fn desktop_proxy_requires_running_desktop_service() {
        let info = sample_info();
        let err = proxy_project_desktop_response(
            "p1",
            &info,
            "index.html",
            Some("token=ms_sk_secret"),
            HeaderMap::new(),
            false,
        )
        .await
        .unwrap_err();
        assert_eq!(err.status, StatusCode::SERVICE_UNAVAILABLE);
        assert_eq!(err.detail, DESKTOP_SERVICE_NOT_RUNNING);
    }

    fn spawn_http_proxy_fixture() -> (String, std::sync::mpsc::Receiver<String>) {
        let listener = std::net::TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let addr = listener.local_addr().unwrap();
        let (tx, rx) = std::sync::mpsc::channel();
        std::thread::spawn(move || {
            use std::io::{Read, Write};

            let (mut stream, _) = listener.accept().unwrap();
            let mut buf = [0_u8; 8192];
            let n = stream.read(&mut buf).unwrap();
            tx.send(String::from_utf8_lossy(&buf[..n]).into_owned())
                .unwrap();
            let body = r#"<html><link href="/assets/app.css"><script>fetch('/api/data');new WebSocket('/socket')</script></html>"#;
            let response = format!(
                "HTTP/1.1 302 Found\r\ncontent-type: text/html; charset=utf-8\r\ncache-control: no-store\r\nlocation: /login\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{}",
                body.len(),
                body
            );
            stream.write_all(response.as_bytes()).unwrap();
        });
        (format!("http://{addr}/base"), rx)
    }

    fn spawn_preview_host_proxy_fixture() -> (String, std::sync::mpsc::Receiver<String>) {
        let listener = std::net::TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let addr = listener.local_addr().unwrap();
        let (tx, rx) = std::sync::mpsc::channel();
        std::thread::spawn(move || {
            use std::io::{Read, Write};

            let (mut stream, _) = listener.accept().unwrap();
            let mut buf = [0_u8; 8192];
            let n = stream.read(&mut buf).unwrap();
            tx.send(String::from_utf8_lossy(&buf[..n]).into_owned())
                .unwrap();
            let body = "preview-host";
            let response = format!(
                "HTTP/1.1 302 Found\r\ncontent-type: text/plain\r\ncache-control: no-store\r\nlocation: http://{addr}/base/login?next=%2F\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{}",
                body.len(),
                body
            );
            stream.write_all(response.as_bytes()).unwrap();
        });
        (format!("http://{addr}/base"), rx)
    }

    #[tokio::test]
    async fn http_service_proxy_forwards_rewrites_and_filters_headers() {
        let (service_url, rx) = spawn_http_proxy_fixture();
        let service_info = HttpServiceProxyInfo {
            service_id: "web".to_string(),
            name: "Docs".to_string(),
            source_type: HttpServiceSourceType::SandboxInternal,
            status: "running".to_string(),
            service_url,
            preview_url: build_http_preview_proxy_url("p1", "web"),
            ws_preview_url: Some(build_http_preview_ws_proxy_url("p1", "web")),
            sandbox_id: Some("s1".to_string()),
            auto_open: true,
            restart_token: Some("1700000000000".to_string()),
            updated_at: "1970-01-01T00:00:00.000+00:00".to_string(),
        };
        let mut headers = HeaderMap::new();
        headers.insert(
            "authorization",
            HeaderValue::from_static("Bearer ms_sk_secret"),
        );
        headers.insert("cookie", HeaderValue::from_static("a=b"));
        headers.insert("x-forwarded-proto", HeaderValue::from_static("https"));
        headers.insert("x-trace-id", HeaderValue::from_static("trace-1"));

        let response = proxy_http_service_response(
            "p1",
            "web",
            &service_info,
            "echo",
            Some("token=ms_sk_secret&q=hello+world"),
            Method::POST,
            headers,
            b"payload".to_vec(),
            "ms_sk_secret",
            true,
        )
        .await
        .unwrap();

        assert_eq!(response.status(), StatusCode::FOUND);
        assert_eq!(
            response
                .headers()
                .get(CONTENT_TYPE)
                .and_then(|value| value.to_str().ok()),
            Some("text/html; charset=utf-8")
        );
        assert_eq!(
            response
                .headers()
                .get(CACHE_CONTROL)
                .and_then(|value| value.to_str().ok()),
            Some("no-store")
        );
        assert_eq!(
            response
                .headers()
                .get(LOCATION)
                .and_then(|value| value.to_str().ok()),
            Some("/api/v1/projects/p1/sandbox/http-services/web/proxy/login?token=ms_sk_secret")
        );
        let cookies = response
            .headers()
            .get_all(SET_COOKIE)
            .iter()
            .filter_map(|value| value.to_str().ok())
            .collect::<Vec<_>>();
        assert!(cookies.iter().any(|cookie| cookie.contains(
            "sandbox_proxy_token=ms_sk_secret; HttpOnly; SameSite=Strict; Max-Age=3600; Path=/api/v1/projects/p1/sandbox; Secure"
        )));
        assert!(cookies.iter().any(|cookie| cookie.contains(
            "desktop_token=ms_sk_secret; HttpOnly; SameSite=Strict; Max-Age=86400; Path=/api/v1/projects/p1/sandbox/http-services/web/proxy"
        )));

        let body = to_bytes(response.into_body(), HTTP_PROXY_BODY_LIMIT_BYTES)
            .await
            .unwrap();
        let body = String::from_utf8(body.to_vec()).unwrap();
        assert!(body.contains(
            r#"href="/api/v1/projects/p1/sandbox/http-services/web/proxy/assets/app.css?token=ms_sk_secret""#
        ));
        assert!(body.contains(
            r#"fetch('/api/v1/projects/p1/sandbox/http-services/web/proxy/api/data?token=ms_sk_secret'"#
        ));
        assert!(body.contains(
            r#"new WebSocket('/api/v1/projects/p1/sandbox/http-services/web/proxy/ws/socket?token=ms_sk_secret'"#
        ));

        let request = rx
            .recv_timeout(Duration::from_secs(2))
            .expect("upstream request");
        assert!(request.starts_with("POST /base/echo?q=hello+world HTTP/1.1"));
        assert!(request.contains("x-trace-id: trace-1"));
        assert!(!request.to_ascii_lowercase().contains("authorization:"));
        assert!(!request.to_ascii_lowercase().contains("cookie:"));
        assert!(request.ends_with("payload"));
    }

    #[tokio::test]
    async fn http_service_preview_host_sets_session_cookie_and_proxies() {
        let (service_url, rx) = spawn_preview_host_proxy_fixture();
        let service =
            ProjectSandboxService::new(Arc::new(InMemoryContainerRuntime::new()), "redis:7-alpine");
        service
            .upsert_http_service(
                "p1",
                HttpServiceProxyInfo {
                    service_id: "web".to_string(),
                    name: "Docs".to_string(),
                    source_type: HttpServiceSourceType::SandboxInternal,
                    status: "running".to_string(),
                    service_url,
                    preview_url: build_http_preview_proxy_url("p1", "web"),
                    ws_preview_url: Some(build_http_preview_ws_proxy_url("p1", "web")),
                    sandbox_id: Some("s1".to_string()),
                    auto_open: true,
                    restart_token: Some("1700000000000".to_string()),
                    updated_at: "1970-01-01T00:00:00.000+00:00".to_string(),
                },
            )
            .await
            .unwrap();
        let preview = service.preview_session("p1", "web").await.unwrap();
        let preview_url = url::Url::parse(&preview.preview_url).unwrap();
        let token = preview_session_token_from_query(preview_url.query()).unwrap();
        let host = "web.p1.preview.localhost:8000";

        let mut token_headers = HeaderMap::new();
        token_headers.insert(
            "host",
            HeaderValue::from_static("web.p1.preview.localhost:8000"),
        );
        token_headers.insert("x-forwarded-proto", HeaderValue::from_static("https"));
        let response = proxy_http_service_preview_host_response(
            &service,
            host,
            "/docs",
            Some(&format!("{PREVIEW_SESSION_QUERY_PARAM}={token}&q=1")),
            Method::GET,
            token_headers,
            Vec::new(),
        )
        .await
        .unwrap();
        assert_eq!(response.status(), StatusCode::FOUND);
        assert_eq!(
            response
                .headers()
                .get(LOCATION)
                .and_then(|value| value.to_str().ok()),
            Some("/docs?q=1")
        );
        let session_cookie = response
            .headers()
            .get(SET_COOKIE)
            .and_then(|value| value.to_str().ok())
            .unwrap();
        assert!(session_cookie.contains(&format!("{PREVIEW_SESSION_COOKIE_NAME}={token}")));
        assert!(session_cookie.contains("HttpOnly; SameSite=Lax"));
        assert!(session_cookie.ends_with("; Secure"));

        let mut headers = HeaderMap::new();
        headers.insert(
            "host",
            HeaderValue::from_static("web.p1.preview.localhost:8000"),
        );
        headers.insert(
            "cookie",
            HeaderValue::from_str(&format!("{PREVIEW_SESSION_COOKIE_NAME}={token}; other=1"))
                .unwrap(),
        );
        headers.insert(
            "authorization",
            HeaderValue::from_static("Bearer ms_sk_secret"),
        );
        headers.insert("x-forwarded-proto", HeaderValue::from_static("https"));
        headers.insert("x-trace-id", HeaderValue::from_static("trace-1"));
        let response = proxy_http_service_preview_host_response(
            &service,
            host,
            "/echo",
            Some("q=hello+world"),
            Method::POST,
            headers,
            b"payload".to_vec(),
        )
        .await
        .unwrap();

        assert_eq!(response.status(), StatusCode::FOUND);
        assert_eq!(
            response
                .headers()
                .get(CONTENT_TYPE)
                .and_then(|value| value.to_str().ok()),
            Some("text/plain")
        );
        assert_eq!(
            response
                .headers()
                .get(CACHE_CONTROL)
                .and_then(|value| value.to_str().ok()),
            Some("no-store")
        );
        assert_eq!(
            response
                .headers()
                .get(LOCATION)
                .and_then(|value| value.to_str().ok()),
            Some("https://web.p1.preview.localhost:8000/base/login?next=%2F")
        );
        let body = to_bytes(response.into_body(), HTTP_PROXY_BODY_LIMIT_BYTES)
            .await
            .unwrap();
        assert_eq!(body.as_ref(), b"preview-host");

        let request = rx
            .recv_timeout(Duration::from_secs(2))
            .expect("upstream request");
        assert!(request.starts_with("POST /base/echo?q=hello+world HTTP/1.1"));
        assert!(request.contains("x-trace-id: trace-1"));
        assert!(!request.to_ascii_lowercase().contains("authorization:"));
        assert!(!request.to_ascii_lowercase().contains("cookie:"));
        assert!(request.ends_with("payload"));
    }

    async fn spawn_http_service_ws_upstream(
    ) -> (String, std::sync::mpsc::Receiver<(String, Option<String>)>) {
        let listener = tokio::net::TcpListener::bind(("127.0.0.1", 0))
            .await
            .unwrap();
        let addr = listener.local_addr().unwrap();
        let (tx, rx) = std::sync::mpsc::channel();
        tokio::spawn(async move {
            let (stream, _) = listener.accept().await.unwrap();
            let ws = tokio_tungstenite::accept_hdr_async(
                stream,
                |req: &tokio_tungstenite::tungstenite::handshake::server::Request, response| {
                    let origin = req
                        .headers()
                        .get("origin")
                        .and_then(|value| value.to_str().ok())
                        .map(str::to_string);
                    tx.send((req.uri().to_string(), origin)).unwrap();
                    Ok::<_, tokio_tungstenite::tungstenite::handshake::server::ErrorResponse>(
                        response,
                    )
                },
            )
            .await
            .unwrap();
            let (mut sink, mut stream) = ws.split();
            while let Some(Ok(message)) = stream.next().await {
                match message {
                    TungsteniteMessage::Text(text) => {
                        sink.send(TungsteniteMessage::Text(format!("echo:{text}")))
                            .await
                            .unwrap();
                        break;
                    }
                    TungsteniteMessage::Binary(binary) => {
                        sink.send(TungsteniteMessage::Binary(binary)).await.unwrap();
                        break;
                    }
                    TungsteniteMessage::Close(close) => {
                        let _ = sink.send(TungsteniteMessage::Close(close)).await;
                        break;
                    }
                    _ => {}
                }
            }
        });
        (format!("http://{addr}/base"), rx)
    }

    async fn spawn_http_service_ws_proxy(ws_target: String, origin: String) -> String {
        let listener = tokio::net::TcpListener::bind(("127.0.0.1", 0))
            .await
            .unwrap();
        let addr = listener.local_addr().unwrap();
        let app = Router::new().route(
            "/proxy/ws",
            get(move |ws: WebSocketUpgrade| {
                let ws_target = ws_target.clone();
                let origin = origin.clone();
                async move {
                    ws.protocols([WEBSOCKET_AUTH_SUBPROTOCOL])
                        .on_upgrade(move |socket| {
                            proxy_http_service_ws_session(socket, ws_target, origin)
                        })
                        .into_response()
                }
            }),
        );
        tokio::spawn(async move {
            axum::serve(listener, app).await.unwrap();
        });
        format!("ws://{addr}/proxy/ws")
    }

    async fn spawn_desktop_ws_upstream() -> (
        String,
        std::sync::mpsc::Receiver<(String, Option<String>, Option<String>)>,
    ) {
        let listener = tokio::net::TcpListener::bind(("127.0.0.1", 0))
            .await
            .unwrap();
        let addr = listener.local_addr().unwrap();
        let (tx, rx) = std::sync::mpsc::channel();
        tokio::spawn(async move {
            let (stream, _) = listener.accept().await.unwrap();
            let ws = tokio_tungstenite::accept_hdr_async(
                stream,
                |req: &tokio_tungstenite::tungstenite::handshake::server::Request,
                 mut response: tokio_tungstenite::tungstenite::handshake::server::Response| {
                    let origin = req
                        .headers()
                        .get("origin")
                        .and_then(|value| value.to_str().ok())
                        .map(str::to_string);
                    let protocol = req
                        .headers()
                        .get("sec-websocket-protocol")
                        .and_then(|value| value.to_str().ok())
                        .map(str::to_string);
                    response.headers_mut().insert(
                        "sec-websocket-protocol",
                        HeaderValue::from_static(DESKTOP_WEBSOCKET_SUBPROTOCOL),
                    );
                    tx.send((req.uri().to_string(), origin, protocol)).unwrap();
                    Ok::<_, tokio_tungstenite::tungstenite::handshake::server::ErrorResponse>(
                        response,
                    )
                },
            )
            .await
            .unwrap();
            let (mut sink, mut stream) = ws.split();
            while let Some(Ok(message)) = stream.next().await {
                match message {
                    TungsteniteMessage::Text(text) => {
                        sink.send(TungsteniteMessage::Text(format!("echo:{text}")))
                            .await
                            .unwrap();
                        break;
                    }
                    TungsteniteMessage::Binary(binary) => {
                        sink.send(TungsteniteMessage::Binary(binary)).await.unwrap();
                        break;
                    }
                    TungsteniteMessage::Close(close) => {
                        let _ = sink.send(TungsteniteMessage::Close(close)).await;
                        break;
                    }
                    _ => {}
                }
            }
        });
        (format!("ws://{addr}/base"), rx)
    }

    async fn spawn_desktop_ws_proxy(ws_target: String, origin: String) -> String {
        let listener = tokio::net::TcpListener::bind(("127.0.0.1", 0))
            .await
            .unwrap();
        let addr = listener.local_addr().unwrap();
        let app = Router::new().route(
            "/desktop/proxy/websockify",
            get(move |ws: WebSocketUpgrade| {
                let ws_target = ws_target.clone();
                let origin = origin.clone();
                async move {
                    websocket_upgrade_with_desktop_protocol(ws)
                        .on_upgrade(move |socket| {
                            proxy_desktop_ws_session(socket, ws_target, origin)
                        })
                        .into_response()
                }
            }),
        );
        tokio::spawn(async move {
            axum::serve(listener, app).await.unwrap();
        });
        format!("ws://{addr}/desktop/proxy/websockify")
    }

    async fn spawn_terminal_ws_upstream() -> (
        String,
        std::sync::mpsc::Receiver<(String, Option<String>)>,
        std::sync::mpsc::Receiver<Vec<u8>>,
    ) {
        let listener = tokio::net::TcpListener::bind(("127.0.0.1", 0))
            .await
            .unwrap();
        let addr = listener.local_addr().unwrap();
        let (request_tx, request_rx) = std::sync::mpsc::channel();
        let (frame_tx, frame_rx) = std::sync::mpsc::channel();
        tokio::spawn(async move {
            let (stream, _) = listener.accept().await.unwrap();
            let ws = tokio_tungstenite::accept_hdr_async(
                stream,
                |req: &tokio_tungstenite::tungstenite::handshake::server::Request, response| {
                    let origin = req
                        .headers()
                        .get("origin")
                        .and_then(|value| value.to_str().ok())
                        .map(str::to_string);
                    request_tx.send((req.uri().to_string(), origin)).unwrap();
                    Ok::<_, tokio_tungstenite::tungstenite::handshake::server::ErrorResponse>(
                        response,
                    )
                },
            )
            .await
            .unwrap();
            let (mut sink, mut stream) = ws.split();
            while let Some(Ok(message)) = stream.next().await {
                match message {
                    TungsteniteMessage::Text(text) => {
                        let frame = text.as_bytes().to_vec();
                        frame_tx.send(frame.clone()).unwrap();
                        if frame.first() == Some(&TTYD_INPUT_COMMAND) {
                            let mut output = b"0echo:".to_vec();
                            output.extend_from_slice(&frame[1..]);
                            sink.send(TungsteniteMessage::Binary(output)).await.unwrap();
                            break;
                        }
                    }
                    TungsteniteMessage::Binary(binary) => {
                        let frame = binary.to_vec();
                        frame_tx.send(frame.clone()).unwrap();
                        if frame.first() == Some(&TTYD_INPUT_COMMAND) {
                            let mut output = b"0echo:".to_vec();
                            output.extend_from_slice(&frame[1..]);
                            sink.send(TungsteniteMessage::Binary(output)).await.unwrap();
                            break;
                        }
                    }
                    TungsteniteMessage::Close(close) => {
                        let _ = sink.send(TungsteniteMessage::Close(close)).await;
                        break;
                    }
                    _ => {}
                }
            }
        });
        (format!("ws://{addr}/term"), request_rx, frame_rx)
    }

    async fn spawn_terminal_ws_proxy(
        ws_target: String,
        origin: String,
        registry: SharedHttpServiceRegistry,
        project_id: String,
    ) -> String {
        let listener = tokio::net::TcpListener::bind(("127.0.0.1", 0))
            .await
            .unwrap();
        let addr = listener.local_addr().unwrap();
        let app = Router::new().route(
            "/terminal/proxy/ws",
            get(
                move |ws: WebSocketUpgrade,
                      headers: HeaderMap,
                      Query(query): Query<TerminalWsQuery>| {
                    let ws_target = ws_target.clone();
                    let origin = origin.clone();
                    let registry = registry.clone();
                    let project_id = project_id.clone();
                    async move {
                        let session_id = query.session_id.unwrap_or_else(new_terminal_session_id);
                        let initial_size = registry
                            .get_terminal_session(&project_id, &session_id)
                            .await
                            .unwrap()
                            .map(|session| session.size())
                            .unwrap_or_default();
                        let recorder = TerminalSessionRecorder {
                            registry,
                            project_id,
                            session_id: session_id.clone(),
                            ttl_seconds: terminal_session_ttl_seconds(),
                        };
                        websocket_upgrade_with_auth_protocol(ws, &headers)
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
                            .into_response()
                    }
                },
            ),
        );
        tokio::spawn(async move {
            axum::serve(listener, app).await.unwrap();
        });
        format!("ws://{addr}/terminal/proxy/ws")
    }

    async fn spawn_mcp_ws_upstream() -> (String, std::sync::mpsc::Receiver<String>) {
        let listener = tokio::net::TcpListener::bind(("127.0.0.1", 0))
            .await
            .unwrap();
        let addr = listener.local_addr().unwrap();
        let (tx, rx) = std::sync::mpsc::channel();
        tokio::spawn(async move {
            let (stream, _) = listener.accept().await.unwrap();
            let ws = tokio_tungstenite::accept_hdr_async(
                stream,
                |req: &tokio_tungstenite::tungstenite::handshake::server::Request, response| {
                    tx.send(req.uri().to_string()).unwrap();
                    Ok::<_, tokio_tungstenite::tungstenite::handshake::server::ErrorResponse>(
                        response,
                    )
                },
            )
            .await
            .unwrap();
            let (mut sink, mut stream) = ws.split();
            while let Some(Ok(message)) = stream.next().await {
                if matches!(message, TungsteniteMessage::Text(_)) {
                    let response = json!({
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {
                            "contents": [{
                                "uri": "ui://index.html",
                                "mimeType": "text/html",
                                "text": "<html></html>"
                            }]
                        }
                    });
                    sink.send(TungsteniteMessage::Text(response.to_string()))
                        .await
                        .unwrap();
                    break;
                }
            }
        });
        (format!("ws://{addr}/mcp/sandbox?auth=keep"), rx)
    }

    async fn spawn_mcp_ws_proxy(ws_target: String) -> String {
        let listener = tokio::net::TcpListener::bind(("127.0.0.1", 0))
            .await
            .unwrap();
        let addr = listener.local_addr().unwrap();
        let app = Router::new().route(
            "/sandbox/mcp/proxy",
            get(move |ws: WebSocketUpgrade, headers: HeaderMap| {
                let ws_target = ws_target.clone();
                async move {
                    websocket_upgrade_with_auth_protocol(ws, &headers)
                        .on_upgrade(move |socket| proxy_mcp_ws_session(socket, ws_target))
                        .into_response()
                }
            }),
        );
        tokio::spawn(async move {
            axum::serve(listener, app).await.unwrap();
        });
        format!("ws://{addr}/sandbox/mcp/proxy")
    }

    async fn spawn_http_preview_host_ws_proxy(sandboxes: Arc<ProjectSandboxService>) -> String {
        let listener = tokio::net::TcpListener::bind(("127.0.0.1", 0))
            .await
            .unwrap();
        let addr = listener.local_addr().unwrap();
        let app = Router::new().route(
            "/*path",
            get(move |ws: WebSocketUpgrade, headers: HeaderMap, uri: Uri| {
                let sandboxes = sandboxes.clone();
                async move {
                    let host_header = headers
                        .get("host")
                        .and_then(|value| value.to_str().ok())
                        .unwrap_or_default()
                        .to_string();
                    let raw_query = uri.query().map(str::to_string);
                    proxy_http_service_preview_host_ws_response(
                        &sandboxes,
                        &host_header,
                        uri.path(),
                        raw_query.as_deref(),
                        headers,
                        ws,
                    )
                    .await
                }
            }),
        );
        tokio::spawn(async move {
            axum::serve(listener, app).await.unwrap();
        });
        format!("ws://{addr}")
    }

    #[tokio::test]
    async fn http_service_ws_proxy_relays_frames_and_filters_token_query() {
        let (service_url, rx) = spawn_http_service_ws_upstream().await;
        let ws_target = build_upstream_ws_url(
            &service_url,
            "socket",
            Some("token=ms_sk_secret&q=hello+world"),
        )
        .unwrap();
        let proxy_url = spawn_http_service_ws_proxy(ws_target, service_url.clone()).await;
        let mut request = proxy_url.into_client_request().unwrap();
        request.headers_mut().insert(
            "sec-websocket-protocol",
            HeaderValue::from_static(WEBSOCKET_AUTH_SUBPROTOCOL),
        );

        let (mut client, response) = connect_async(request).await.unwrap();
        assert_eq!(
            response
                .headers()
                .get("sec-websocket-protocol")
                .and_then(|value| value.to_str().ok()),
            Some(WEBSOCKET_AUTH_SUBPROTOCOL)
        );

        client
            .send(TungsteniteMessage::Text("ping".into()))
            .await
            .unwrap();
        let reply = client.next().await.unwrap().unwrap();
        assert_eq!(reply, TungsteniteMessage::Text("echo:ping".into()));

        let (uri, origin) = rx
            .recv_timeout(Duration::from_secs(2))
            .expect("upstream ws request");
        assert_eq!(uri, "/base/socket?q=hello+world");
        assert_eq!(origin.as_deref(), Some(service_url.as_str()));
    }

    #[tokio::test]
    async fn desktop_ws_proxy_relays_binary_and_uses_binary_subprotocol() {
        let (desktop_url, rx) = spawn_desktop_ws_upstream().await;
        let ws_target = build_desktop_websocket_target(&desktop_url).unwrap();
        let origin = desktop_websocket_origin(&desktop_url, &ws_target);
        let proxy_url = spawn_desktop_ws_proxy(ws_target, origin).await;
        let mut request = proxy_url.into_client_request().unwrap();
        request.headers_mut().insert(
            "sec-websocket-protocol",
            HeaderValue::from_static(DESKTOP_WEBSOCKET_SUBPROTOCOL),
        );

        let (mut client, response) = connect_async(request).await.unwrap();
        assert_eq!(
            response
                .headers()
                .get("sec-websocket-protocol")
                .and_then(|value| value.to_str().ok()),
            Some(DESKTOP_WEBSOCKET_SUBPROTOCOL)
        );

        client
            .send(TungsteniteMessage::Binary(vec![1_u8, 2, 3]))
            .await
            .unwrap();
        let reply = client.next().await.unwrap().unwrap();
        assert_eq!(reply, TungsteniteMessage::Binary(vec![1_u8, 2, 3]));

        let (uri, origin, protocol) = rx
            .recv_timeout(Duration::from_secs(2))
            .expect("upstream desktop ws request");
        assert_eq!(uri, "/base/websockify");
        assert_eq!(origin.as_deref(), Some(desktop_url.as_str()));
        assert_eq!(protocol.as_deref(), Some(DESKTOP_WEBSOCKET_SUBPROTOCOL));
    }

    #[tokio::test]
    async fn terminal_ws_proxy_speaks_python_envelope_over_ttyd() {
        let (terminal_url, request_rx, frame_rx) = spawn_terminal_ws_upstream().await;
        let ws_target = build_terminal_websocket_target(&terminal_url).unwrap();
        let origin = terminal_websocket_origin(&terminal_url, &ws_target);
        let registry = in_memory_http_service_registry();
        let project_id = "project-terminal".to_string();
        registry
            .upsert_terminal_session(
                TerminalSessionRecord::new(
                    project_id.clone(),
                    "session-secret".to_string(),
                    TerminalSize {
                        cols: 100,
                        rows: 32,
                    },
                    false,
                    now_ms(),
                    terminal_session_ttl_seconds(),
                ),
                terminal_session_ttl_seconds(),
            )
            .await
            .unwrap();
        let proxy_url =
            spawn_terminal_ws_proxy(ws_target, origin, registry.clone(), project_id.clone()).await;
        let mut request = format!("{proxy_url}?session_id=session-secret")
            .into_client_request()
            .unwrap();
        request.headers_mut().insert(
            "sec-websocket-protocol",
            HeaderValue::from_static(WEBSOCKET_AUTH_SUBPROTOCOL),
        );

        let (mut client, response) = connect_async(request).await.unwrap();
        assert_eq!(
            response
                .headers()
                .get("sec-websocket-protocol")
                .and_then(|value| value.to_str().ok()),
            Some(WEBSOCKET_AUTH_SUBPROTOCOL)
        );

        let connected = client.next().await.unwrap().unwrap();
        let TungsteniteMessage::Text(connected) = connected else {
            panic!("expected connected text frame");
        };
        let connected: Value = serde_json::from_str(&connected).unwrap();
        assert_eq!(connected["type"], "connected");
        assert_eq!(connected["session_id"], "session-secret");
        assert_eq!(connected["cols"], 100);
        assert_eq!(connected["rows"], 32);
        let stored = registry
            .get_terminal_session(&project_id, "session-secret")
            .await
            .unwrap()
            .unwrap();
        assert!(stored.connected);
        assert_eq!(
            stored.size(),
            TerminalSize {
                cols: 100,
                rows: 32
            }
        );

        client
            .send(TungsteniteMessage::Text(
                json!({ "type": "ping" }).to_string(),
            ))
            .await
            .unwrap();
        let pong = client.next().await.unwrap().unwrap();
        let TungsteniteMessage::Text(pong) = pong else {
            panic!("expected pong text frame");
        };
        let pong: Value = serde_json::from_str(&pong).unwrap();
        assert_eq!(pong["type"], "pong");

        client
            .send(TungsteniteMessage::Text(
                json!({ "type": "resize", "cols": 120, "rows": 40 }).to_string(),
            ))
            .await
            .unwrap();
        client
            .send(TungsteniteMessage::Text(
                json!({ "type": "input", "data": "ls\n" }).to_string(),
            ))
            .await
            .unwrap();
        let output = client.next().await.unwrap().unwrap();
        let TungsteniteMessage::Text(output) = output else {
            panic!("expected output text frame");
        };
        let output: Value = serde_json::from_str(&output).unwrap();
        assert_eq!(output["type"], "output");
        assert_eq!(output["data"], "echo:ls\n");

        let (uri, origin) = request_rx
            .recv_timeout(Duration::from_secs(2))
            .expect("upstream terminal ws request");
        assert_eq!(uri, "/term");
        assert_eq!(origin.as_deref(), Some(terminal_url.as_str()));

        let init = frame_rx
            .recv_timeout(Duration::from_secs(2))
            .expect("ttyd init frame");
        let init: Value = serde_json::from_slice(&init).unwrap();
        assert_eq!(init["AuthToken"], "");
        assert_eq!(init["columns"], 100);
        assert_eq!(init["rows"], 32);

        let resize = frame_rx
            .recv_timeout(Duration::from_secs(2))
            .expect("ttyd resize frame");
        assert_eq!(resize.first().copied(), Some(TTYD_RESIZE_COMMAND));
        let resize: Value = serde_json::from_slice(&resize[1..]).unwrap();
        assert_eq!(resize["columns"], 120);
        assert_eq!(resize["rows"], 40);

        let input = frame_rx
            .recv_timeout(Duration::from_secs(2))
            .expect("ttyd input frame");
        assert_eq!(input.first().copied(), Some(TTYD_INPUT_COMMAND));
        assert_eq!(&input[1..], b"ls\n");
        drop(client);

        let mut final_session = None;
        for _ in 0..20 {
            let session = registry
                .get_terminal_session(&project_id, "session-secret")
                .await
                .unwrap()
                .unwrap();
            if !session.connected
                && session.size()
                    == (TerminalSize {
                        cols: 120,
                        rows: 40,
                    })
            {
                final_session = Some(session);
                break;
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
        let final_session = final_session.expect("terminal session should be marked disconnected");
        assert_eq!(final_session.session_id, "session-secret");
    }

    #[tokio::test]
    async fn mcp_ws_proxy_relays_jsonrpc_and_normalizes_app_resource_mime() {
        let (mcp_url, rx) = spawn_mcp_ws_upstream().await;
        let upstream_token = agistack_adapters_secrets::generate_urlsafe_token(32);
        let ws_target = append_mcp_upstream_token(
            &build_mcp_websocket_target(&mcp_url).unwrap(),
            &upstream_token,
        )
        .unwrap();
        let proxy_url = spawn_mcp_ws_proxy(ws_target).await;
        let (mut client, _response) = connect_async(&proxy_url).await.unwrap();
        client
            .send(TungsteniteMessage::Text(
                json!({ "jsonrpc": "2.0", "id": 1, "method": "resources/read" }).to_string(),
            ))
            .await
            .unwrap();

        let reply = client.next().await.unwrap().unwrap();
        let TungsteniteMessage::Text(text) = reply else {
            panic!("expected json-rpc text frame");
        };
        let parsed: Value = serde_json::from_str(&text).unwrap();
        assert_eq!(
            parsed["result"]["contents"][0]["mimeType"],
            MCP_APP_MIME_TYPE
        );

        let uri = rx
            .recv_timeout(Duration::from_secs(2))
            .expect("upstream mcp ws request");
        assert!(uri.starts_with("/mcp/sandbox?"), "unexpected uri: {uri}");
        let query = uri
            .split_once('?')
            .map(|(_, query)| query)
            .unwrap_or_default();
        let params: BTreeMap<String, String> = url::form_urlencoded::parse(query.as_bytes())
            .map(|(key, value)| (key.into_owned(), value.into_owned()))
            .collect();
        assert_eq!(params.get("auth").map(String::as_str), Some("keep"));
        assert_eq!(
            params.get(MCP_UPSTREAM_TOKEN_QUERY_PARAM),
            Some(&upstream_token)
        );
        assert!(agistack_parity::is_urlsafe_token_32(&upstream_token));
    }

    #[tokio::test]
    async fn http_service_preview_host_ws_proxy_relays_and_filters_session_query() {
        let (service_url, rx) = spawn_http_service_ws_upstream().await;
        let service = Arc::new(ProjectSandboxService::new(
            Arc::new(InMemoryContainerRuntime::new()),
            "redis:7-alpine",
        ));
        service
            .upsert_http_service(
                "p1",
                HttpServiceProxyInfo {
                    service_id: "web".to_string(),
                    name: "Docs".to_string(),
                    source_type: HttpServiceSourceType::SandboxInternal,
                    status: "running".to_string(),
                    service_url: service_url.clone(),
                    preview_url: build_http_preview_proxy_url("p1", "web"),
                    ws_preview_url: Some(build_http_preview_ws_proxy_url("p1", "web")),
                    sandbox_id: Some("s1".to_string()),
                    auto_open: true,
                    restart_token: Some("1700000000000".to_string()),
                    updated_at: "1970-01-01T00:00:00.000+00:00".to_string(),
                },
            )
            .await
            .unwrap();
        let preview = service.preview_session("p1", "web").await.unwrap();
        let preview_url = url::Url::parse(&preview.preview_url).unwrap();
        let token = preview_session_token_from_query(preview_url.query()).unwrap();
        let proxy_url = spawn_http_preview_host_ws_proxy(service.clone()).await;
        let mut request =
            format!("{proxy_url}/socket?{PREVIEW_SESSION_QUERY_PARAM}={token}&q=hello+world")
                .into_client_request()
                .unwrap();
        request.headers_mut().insert(
            "host",
            HeaderValue::from_static("web.p1.preview.localhost:8000"),
        );
        request
            .headers_mut()
            .insert("origin", HeaderValue::from_static("https://frontend.test"));
        request.headers_mut().insert(
            "sec-websocket-protocol",
            HeaderValue::from_static(WEBSOCKET_AUTH_SUBPROTOCOL),
        );

        let (mut client, response) = connect_async(request).await.unwrap();
        assert_eq!(
            response
                .headers()
                .get("sec-websocket-protocol")
                .and_then(|value| value.to_str().ok()),
            Some(WEBSOCKET_AUTH_SUBPROTOCOL)
        );

        client
            .send(TungsteniteMessage::Text("preview".into()))
            .await
            .unwrap();
        let reply = client.next().await.unwrap().unwrap();
        assert_eq!(reply, TungsteniteMessage::Text("echo:preview".into()));

        let (uri, origin) = rx
            .recv_timeout(Duration::from_secs(2))
            .expect("upstream preview host ws request");
        assert_eq!(uri, "/base/socket?q=hello+world");
        assert_eq!(origin.as_deref(), Some("https://frontend.test"));
    }

    #[test]
    fn proxy_auth_cookie_response_and_header_match_python_contract() {
        let response = SandboxProxyAuthCookieResponse {
            success: true,
            expires_in_seconds: SANDBOX_PROXY_AUTH_COOKIE_MAX_AGE_SECONDS,
        };
        let golden: serde_json::Value = serde_json::from_str(include_str!(
            "../tests/golden/project_sandbox_proxy_auth_cookie.json"
        ))
        .unwrap();
        agistack_parity::assert_parity(&golden, &serde_json::to_value(&response).unwrap());

        let cookie = sandbox_proxy_auth_cookie("p1", "ms_sk_test", false).unwrap();
        assert_eq!(
            cookie.to_str().unwrap(),
            "sandbox_proxy_token=ms_sk_test; HttpOnly; SameSite=Strict; Max-Age=3600; Path=/api/v1/projects/p1/sandbox"
        );

        let secure_cookie = sandbox_proxy_auth_cookie("p1", "ms_sk_test", true).unwrap();
        assert!(secure_cookie.to_str().unwrap().ends_with("; Secure"));
    }

    #[test]
    fn proxy_auth_cookie_secure_detection_honors_forwarded_proto() {
        let mut headers = HeaderMap::new();
        assert!(!proxy_auth_cookie_secure(&headers));

        headers.insert("x-forwarded-proto", HeaderValue::from_static("https,http"));
        assert!(proxy_auth_cookie_secure(&headers));

        let mut headers = HeaderMap::new();
        headers.insert(
            "forwarded",
            HeaderValue::from_static("for=127.0.0.1;proto=https;host=example.test"),
        );
        assert!(proxy_auth_cookie_secure(&headers));
    }

    #[test]
    fn health_stats_and_action_responses_match_goldens() {
        let info = sample_info();
        let health = HealthCheckResponse {
            project_id: "p1".to_string(),
            sandbox_id: "s1".to_string(),
            healthy: info.healthy(),
            status: info.status_str().to_string(),
            checked_at: rfc3339(0),
        };
        let health_golden: serde_json::Value =
            serde_json::from_str(include_str!("../tests/golden/project_sandbox_health.json"))
                .unwrap();
        agistack_parity::assert_parity(&health_golden, &serde_json::to_value(&health).unwrap());

        let stats = SandboxStatsResponse {
            project_id: "p1".to_string(),
            sandbox_id: "s1".to_string(),
            status: "running".to_string(),
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
            uptime_seconds: Some(12),
            created_at: Some(rfc3339(0)),
            collected_at: rfc3339(12_000),
        };
        let stats_golden: serde_json::Value =
            serde_json::from_str(include_str!("../tests/golden/project_sandbox_stats.json"))
                .unwrap();
        agistack_parity::assert_parity(&stats_golden, &serde_json::to_value(&stats).unwrap());

        let action = SandboxActionResponse {
            success: true,
            message: "Sandbox s1 restarted successfully".to_string(),
            sandbox: Some(ProjectSandboxResponse::from(sample_info())),
        };
        let action_golden: serde_json::Value =
            serde_json::from_str(include_str!("../tests/golden/project_sandbox_action.json"))
                .unwrap();
        agistack_parity::assert_parity(&action_golden, &serde_json::to_value(&action).unwrap());

        let list = ListProjectSandboxesResponse {
            sandboxes: vec![ProjectSandboxResponse::from(sample_info())],
            total: 1,
        };
        let list_golden: serde_json::Value =
            serde_json::from_str(include_str!("../tests/golden/project_sandbox_list.json"))
                .unwrap();
        agistack_parity::assert_parity(&list_golden, &serde_json::to_value(&list).unwrap());
    }
}
