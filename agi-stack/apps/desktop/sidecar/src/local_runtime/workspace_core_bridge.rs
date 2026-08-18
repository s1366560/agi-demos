//! Private Workspace Core to Desktop LocalRuntime authority bridge.

use std::{
    collections::HashMap,
    sync::{atomic::Ordering, Arc, Mutex, OnceLock},
    time::Duration,
};

use axum::{
    body::{to_bytes, Body},
    extract::{Extension, Path, State},
    http::{header::AUTHORIZATION, HeaderMap, HeaderName, Request, StatusCode},
    middleware::Next,
    response::{IntoResponse, Response},
    routing::{get, post},
    Json, Router,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use tokio::{
    io::AsyncReadExt,
    sync::{OwnedSemaphorePermit, Semaphore},
};
use url::Url;
use zeroize::Zeroizing;

use agistack_adapters_wasmtime::{WasmtimeTool, DEFAULT_FUEL, DEFAULT_MEMORY_BYTES};
use agistack_plugin_host::tool::Tool;

use super::{
    mcp_supervisor::McpScope,
    session_store::{DesktopWorkspaceCoreRequestClaim, DesktopWorkspaceCoreRequestClaimError},
    LocalRuntimeState,
};
use crate::plugin_snapshots::{
    plugin_billing_usd_micros_per_call, plugin_quota_limits, PluginQuotaLimits,
    RequestedPluginSnapshot,
};

mod contracts;
mod judge;
#[cfg(test)]
mod plugin_snapshot_routes_tests;
mod provider;
mod registry;

const CALLBACK_TIMEOUT_SECONDS: u64 = 10;
const MAX_PROXY_REQUEST_BYTES: usize = 64 * 1024 * 1024;
const MAX_PLATFORM_PLUGIN_MCP_INPUT_BYTES: usize = 256 * 1024;
const DEFAULT_MAX_CONCURRENT_PLUGIN_CALLS: usize = 16;
const LOCAL_DESKTOP_USER_ID: &str = "local-user";
pub(super) const CUTOVER_GENERATION_BIT: u64 = 1 << 63;
const AUTHORITY_GENERATION_MASK: u64 = CUTOVER_GENERATION_BIT - 1;
const FORWARDED_REQUEST_HEADERS: &[&str] = &[
    "accept",
    "content-type",
    "idempotency-key",
    "x-idempotency-key",
    "if-match",
    "range",
    "x-expected-revision",
    "x-memstack-actor-id",
    "x-memstack-actor-type",
    "x-memstack-workspace-id",
];

#[derive(Debug, Serialize)]
pub(super) struct WorkspaceCoreTaskSessionRequest {
    pub(super) workspace: Value,
    pub(super) conversation_id: String,
    pub(super) initial_message: Value,
    pub(super) workspace_policy: Option<Value>,
    pub(super) capability_mode: super::task_session::TaskSessionCapabilityMode,
}

pub(super) type BridgeError = (StatusCode, Json<Value>);
pub(super) type BridgeResult = Result<Json<Value>, BridgeError>;
type WorkspaceProxyScope<'a> = (Option<&'a str>, Option<&'a str>, Option<&'a str>);

pub(super) struct WorkspaceCoreAuthority {
    generation: u64,
    core_api_base_url: String,
    service_token: Zeroizing<String>,
    agent_registry_token: Zeroizing<String>,
    provider_webhook_token: Zeroizing<String>,
    provider_event_token: Zeroizing<String>,
    client: reqwest::Client,
}

pub(super) fn install_authority(
    state: &LocalRuntimeState,
    core_api_base_url: String,
    service_token: String,
    agent_registry_token: String,
    provider_webhook_token: String,
    provider_event_token: String,
) -> Result<u64, String> {
    validate_authority(
        state,
        &core_api_base_url,
        &service_token,
        &agent_registry_token,
        &provider_webhook_token,
        &provider_event_token,
    )?;
    let previous_generation = state
        .workspace_core_generation
        .fetch_update(Ordering::AcqRel, Ordering::Acquire, |current| {
            let next = (current & AUTHORITY_GENERATION_MASK).checked_add(1)?;
            (next <= AUTHORITY_GENERATION_MASK).then_some(next | CUTOVER_GENERATION_BIT)
        })
        .map_err(|_| "Workspace Core authority generation is exhausted".to_string())?;
    let generation = (previous_generation & AUTHORITY_GENERATION_MASK) + 1;
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(CALLBACK_TIMEOUT_SECONDS))
        .build()
        .map_err(|error| {
            format!("Workspace Core callback client initialization failed: {error}")
        })?;
    *state
        .workspace_core_authority
        .lock()
        .expect("Workspace Core authority") = Some(Arc::new(WorkspaceCoreAuthority {
        generation,
        core_api_base_url: core_api_base_url.trim_end_matches('/').to_string(),
        service_token: Zeroizing::new(service_token),
        agent_registry_token: Zeroizing::new(agent_registry_token),
        provider_webhook_token: Zeroizing::new(provider_webhook_token),
        provider_event_token: Zeroizing::new(provider_event_token),
        client,
    }));
    Ok(generation)
}

pub(super) async fn proxy_workspace_if_authoritative(
    State(state): State<Arc<LocalRuntimeState>>,
    request: Request<Body>,
    next: Next,
) -> Response {
    if workspace_core_cutover_started(&state)
        && workspace_proxy_scope(request.uri().path()).is_ok()
        && !is_task_session_scope(request.uri().path())
    {
        return proxy_installed_workspace_request(&state, request).await;
    }
    next.run(request).await
}

pub(super) async fn proxy_workspace_fallback(
    State(state): State<Arc<LocalRuntimeState>>,
    request: Request<Body>,
) -> Response {
    if workspace_proxy_scope(request.uri().path()).is_ok() {
        return proxy_installed_workspace_request(&state, request).await;
    }
    not_found("Local runtime route is not available").into_response()
}

pub(super) fn workspace_core_cutover_started(state: &LocalRuntimeState) -> bool {
    state.workspace_core_generation.load(Ordering::Acquire) & CUTOVER_GENERATION_BIT != 0
}

pub(super) fn mark_workspace_core_cutover(state: &LocalRuntimeState) {
    state
        .workspace_core_generation
        .fetch_or(CUTOVER_GENERATION_BIT, Ordering::AcqRel);
}

async fn proxy_installed_workspace_request(
    state: &LocalRuntimeState,
    request: Request<Body>,
) -> Response {
    proxy_workspace_request_inner(state, request)
        .await
        .unwrap_or_else(IntoResponse::into_response)
}

async fn proxy_workspace_request_inner(
    state: &LocalRuntimeState,
    request: Request<Body>,
) -> Result<Response, BridgeError> {
    let authenticated = request
        .extensions()
        .get::<super::AuthenticatedContext>()
        .cloned()
        .ok_or_else(|| forbidden("Authenticated Desktop scope is unavailable"))?;
    let authority = state
        .workspace_core_authority
        .lock()
        .expect("Workspace Core authority")
        .clone()
        .ok_or_else(|| unavailable("Workspace Core Desktop authority is not installed"))?;
    let path = request.uri().path().to_string();
    let (tenant_id, project_id, _) = workspace_proxy_scope(&path)?;
    if tenant_id.is_some_and(|tenant_id| tenant_id != authenticated.workspace.tenant_id)
        || project_id.is_some_and(|project_id| project_id != authenticated.workspace.project_id)
    {
        return Err(forbidden(
            "Request is outside the trusted Workspace Core scope",
        ));
    }
    let upstream_path = workspace_core_upstream_path(request.uri())?;
    let upstream_url = format!("{}{}", authority.core_api_base_url, upstream_path);
    let mut upstream = authority
        .client
        .request(request.method().clone(), upstream_url)
        .bearer_auth(authority.service_token.as_str())
        .header("x-memstack-user-id", authenticated.user.user_id.as_str())
        .header(
            "x-memstack-user-is-superuser",
            authenticated.user.is_superuser.to_string(),
        )
        .header("x-memstack-user-email", authenticated.user.email.as_str())
        .header(
            "x-memstack-tenant-id",
            authenticated.workspace.tenant_id.as_str(),
        )
        .header(
            "x-memstack-project-membership-role",
            authenticated.membership_role.as_str(),
        );
    for name in FORWARDED_REQUEST_HEADERS {
        if let Some(value) = request.headers().get(*name) {
            upstream = upstream.header(*name, value);
        }
    }
    let body = to_bytes(request.into_body(), MAX_PROXY_REQUEST_BYTES)
        .await
        .map_err(|_| bad_request("Workspace Core request body is invalid"))?;
    let upstream_response = upstream.body(body).send().await.map_err(|error| {
        tracing::warn!(
            error_kind = workspace_core_transport_error_kind(&error),
            is_connect = error.is_connect(),
            is_timeout = error.is_timeout(),
            is_request = error.is_request(),
            "Workspace Core Desktop proxy request failed"
        );
        unavailable("Workspace Core is unavailable")
    })?;
    let status = upstream_response.status();
    let response_headers = upstream_response.headers().clone();
    let response_body = upstream_response.bytes().await.map_err(|error| {
        tracing::warn!(error = %error, "Workspace Core Desktop proxy response failed");
        unavailable("Workspace Core response is unavailable")
    })?;
    if is_task_session_scope(&path)
        && matches!(
            status,
            StatusCode::NOT_FOUND | StatusCode::METHOD_NOT_ALLOWED
        )
    {
        return Err(unavailable(
            "Workspace Core task-session authority is unavailable",
        ));
    }
    let mut response = Response::builder().status(status);
    for (name, value) in &response_headers {
        if !is_hop_by_hop_header(name) {
            response = response.header(name, value);
        }
    }
    response
        .body(Body::from(response_body))
        .map_err(|_| unavailable("Workspace Core response could not be constructed"))
}

fn workspace_proxy_scope(path: &str) -> Result<WorkspaceProxyScope<'_>, BridgeError> {
    let segments = path.trim_matches('/').split('/').collect::<Vec<_>>();
    match segments.as_slice() {
        ["api", "v1", "tenants", tenant_id, "projects", project_id, "workspaces"] => {
            Ok((Some(tenant_id), Some(project_id), None))
        }
        ["api", "v1", "tenants", tenant_id, "projects", project_id, "workspaces", workspace_id, ..] => {
            Ok((Some(tenant_id), Some(project_id), Some(workspace_id)))
        }
        ["api", "v1", "tenants", tenant_id, "projects", project_id, "task-sessions", ..] => {
            Ok((Some(tenant_id), Some(project_id), None))
        }
        ["api", "v1", "llm-providers", "routing-policy"] => Ok((None, None, None)),
        ["api", "v1", "workspaces", workspace_id, ..] => Ok((None, None, Some(workspace_id))),
        _ => Err(not_found("Workspace Core route is not available")),
    }
}

fn is_task_session_scope(path: &str) -> bool {
    let segments = path.trim_matches('/').split('/').collect::<Vec<_>>();
    matches!(
        segments.as_slice(),
        [
            "api",
            "v1",
            "tenants",
            _,
            "projects",
            _,
            "task-sessions",
            ..
        ]
    )
}

fn workspace_core_upstream_path(uri: &axum::http::Uri) -> Result<String, BridgeError> {
    if !is_task_session_scope(uri.path()) {
        return Ok(uri.to_string());
    }
    let segments = uri.path().trim_matches('/').split('/').collect::<Vec<_>>();
    let ["api", "v1", "tenants", tenant_id, "projects", project_id, "task-sessions"] =
        segments.as_slice()
    else {
        return Err(not_found("Workspace Core route is not available"));
    };
    Ok(format!(
        "/internal/v1/tenants/{tenant_id}/projects/{project_id}/task-sessions"
    ))
}

pub(super) async fn create_task_session(
    state: &LocalRuntimeState,
    authenticated: &super::AuthenticatedContext,
    tenant_id: &str,
    project_id: &str,
    idempotency_key: &str,
    request: WorkspaceCoreTaskSessionRequest,
) -> Result<Value, BridgeError> {
    let authority = state
        .workspace_core_authority
        .lock()
        .expect("Workspace Core authority")
        .clone()
        .ok_or_else(|| unavailable("Workspace Core Desktop authority is not installed"))?;
    let mut url = Url::parse(&authority.core_api_base_url)
        .map_err(|_| unavailable("Workspace Core Desktop authority is invalid"))?;
    url.path_segments_mut()
        .map_err(|_| unavailable("Workspace Core Desktop authority is invalid"))?
        .extend([
            "internal",
            "v1",
            "tenants",
            tenant_id,
            "projects",
            project_id,
            "task-sessions",
        ]);
    let response = authority
        .client
        .post(url)
        .bearer_auth(authority.service_token.as_str())
        .header("x-idempotency-key", idempotency_key)
        .header("x-memstack-user-id", authenticated.user.user_id.as_str())
        .header(
            "x-memstack-user-is-superuser",
            authenticated.user.is_superuser.to_string(),
        )
        .header("x-memstack-user-email", authenticated.user.email.as_str())
        .header("x-memstack-tenant-id", tenant_id)
        .header(
            "x-memstack-project-membership-role",
            authenticated.membership_role.as_str(),
        )
        .json(&request)
        .send()
        .await
        .map_err(|_| unavailable("Workspace Core is unavailable"))?;
    let status = response.status();
    let body = response
        .bytes()
        .await
        .map_err(|_| unavailable("Workspace Core response is unavailable"))?;
    let value = serde_json::from_slice(&body).unwrap_or_else(|_| {
        json!({
            "detail": String::from_utf8_lossy(&body),
        })
    });
    if status.is_success() {
        return Ok(value);
    }
    match status {
        StatusCode::BAD_REQUEST | StatusCode::UNPROCESSABLE_ENTITY => Err((status, Json(value))),
        StatusCode::FORBIDDEN => Err(forbidden("Workspace access is denied")),
        StatusCode::NOT_FOUND
            if value.get("detail").and_then(Value::as_str) == Some("Workspace not found") =>
        {
            Err(not_found("Workspace not found"))
        }
        StatusCode::NOT_FOUND => Err(unavailable(
            "Workspace Core task-session authority is unavailable",
        )),
        StatusCode::CONFLICT => Err((status, Json(value))),
        StatusCode::METHOD_NOT_ALLOWED => Err(unavailable(
            "Workspace Core task-session authority is unavailable",
        )),
        _ => Err(unavailable(
            "Workspace Core task-session authority is unavailable",
        )),
    }
}

pub(super) async fn validate_workspace_access(
    state: &LocalRuntimeState,
    authenticated: &super::AuthenticatedContext,
    workspace_id: &str,
) -> Result<(), BridgeError> {
    let authority = state
        .workspace_core_authority
        .lock()
        .expect("Workspace Core authority")
        .clone()
        .ok_or_else(|| unavailable("Workspace Core Desktop authority is not installed"))?;
    let mut url = Url::parse(&authority.core_api_base_url)
        .map_err(|_| unavailable("Workspace Core Desktop authority is invalid"))?;
    url.path_segments_mut()
        .map_err(|_| unavailable("Workspace Core Desktop authority is invalid"))?
        .extend([
            "api",
            "v1",
            "tenants",
            authenticated.workspace.tenant_id.as_str(),
            "projects",
            authenticated.workspace.project_id.as_str(),
            "workspaces",
            workspace_id,
        ]);
    let response = authority
        .client
        .get(url)
        .bearer_auth(authority.service_token.as_str())
        .header("x-memstack-user-id", authenticated.user.user_id.as_str())
        .header(
            "x-memstack-user-is-superuser",
            authenticated.user.is_superuser.to_string(),
        )
        .header("x-memstack-user-email", authenticated.user.email.as_str())
        .header(
            "x-memstack-tenant-id",
            authenticated.workspace.tenant_id.as_str(),
        )
        .header(
            "x-memstack-project-membership-role",
            authenticated.membership_role.as_str(),
        )
        .send()
        .await
        .map_err(|_| unavailable("Workspace Core is unavailable"))?;
    match response.status() {
        StatusCode::OK => {}
        StatusCode::NOT_FOUND => return Err(not_found("Workspace not found")),
        StatusCode::FORBIDDEN => return Err(forbidden("Workspace access is denied")),
        _ => {
            return Err(unavailable(
                "Workspace Core workspace authority is unavailable",
            ))
        }
    }
    let value: Value = response
        .json()
        .await
        .map_err(|_| unavailable("Workspace Core workspace authority is invalid"))?;
    if value.get("id").and_then(Value::as_str) != Some(workspace_id)
        || value.get("tenant_id").and_then(Value::as_str)
            != Some(authenticated.workspace.tenant_id.as_str())
        || value.get("project_id").and_then(Value::as_str)
            != Some(authenticated.workspace.project_id.as_str())
    {
        return Err(unavailable("Workspace Core workspace authority is invalid"));
    }
    Ok(())
}

pub(super) async fn workspace_policy(
    state: &LocalRuntimeState,
    tenant_id: &str,
    project_id: &str,
    workspace_id: &str,
) -> Result<Value, BridgeError> {
    let authority = state
        .workspace_core_authority
        .lock()
        .expect("Workspace Core authority")
        .clone()
        .ok_or_else(|| unavailable("Workspace Core Desktop authority is not installed"))?;
    let mut url = Url::parse(&authority.core_api_base_url)
        .map_err(|_| unavailable("Workspace Core Desktop authority is invalid"))?;
    url.path_segments_mut()
        .map_err(|_| unavailable("Workspace Core Desktop authority is invalid"))?
        .extend([
            "api",
            "v1",
            "tenants",
            tenant_id,
            "projects",
            project_id,
            "workspaces",
            workspace_id,
            "agent-policy",
        ]);
    let response = authority
        .client
        .get(url)
        .bearer_auth(authority.service_token.as_str())
        .header("x-memstack-user-id", LOCAL_DESKTOP_USER_ID)
        .send()
        .await
        .map_err(|_| unavailable("Workspace Core is unavailable"))?;
    match response.status() {
        StatusCode::OK => {}
        StatusCode::NOT_FOUND => return Err(not_found("Workspace not found")),
        StatusCode::FORBIDDEN => return Err(forbidden("Workspace access is denied")),
        _ => {
            return Err(unavailable(
                "Workspace Core policy authority is unavailable",
            ))
        }
    }
    let policy: Value = response
        .json()
        .await
        .map_err(|_| unavailable("Workspace Core policy authority is invalid"))?;
    if policy.get("tenant_id").and_then(Value::as_str) != Some(tenant_id)
        || policy.get("project_id").and_then(Value::as_str) != Some(project_id)
        || policy.get("workspace_id").and_then(Value::as_str) != Some(workspace_id)
        || !policy.get("roles").is_some_and(Value::is_object)
        || !policy.get("fallbacks").is_some_and(Value::is_array)
    {
        return Err(unavailable("Workspace Core policy authority is invalid"));
    }
    Ok(policy)
}

pub(super) async fn validate_workspace_scope(
    state: &LocalRuntimeState,
    tenant_id: &str,
    project_id: &str,
    workspace_id: &str,
) -> Result<(), &'static str> {
    workspace_policy(state, tenant_id, project_id, workspace_id)
        .await
        .map(|_| ())
        .map_err(|_| "local_automation_workspace_core_unavailable")
}

fn is_hop_by_hop_header(name: &HeaderName) -> bool {
    matches!(
        name.as_str(),
        "connection"
            | "keep-alive"
            | "proxy-authenticate"
            | "proxy-authorization"
            | "te"
            | "trailer"
            | "transfer-encoding"
            | "upgrade"
    )
}

fn workspace_core_transport_error_kind(error: &reqwest::Error) -> &'static str {
    if error.is_connect() {
        "connect"
    } else if error.is_timeout() {
        "timeout"
    } else if error.is_request() {
        "request"
    } else if error.is_body() {
        "body"
    } else if error.is_decode() {
        "decode"
    } else {
        "other"
    }
}

pub(super) fn clear_authority(state: &LocalRuntimeState, generation: u64) {
    let mut authority = state
        .workspace_core_authority
        .lock()
        .expect("Workspace Core authority");
    if authority
        .as_ref()
        .is_some_and(|authority| authority.generation == generation)
    {
        authority.take();
    }
}

pub(super) async fn replay_pending_terminal_callbacks(
    state: Arc<LocalRuntimeState>,
) -> Result<usize, String> {
    provider::replay_pending_terminal_callbacks(state).await
}

pub(super) async fn resume_recovered_workspace_task_runs(
    state: Arc<LocalRuntimeState>,
) -> Result<usize, String> {
    provider::resume_recovered_workspace_task_runs(state).await
}

pub(super) fn router(state: Arc<LocalRuntimeState>) -> Router {
    Router::new()
        .route(
            "/internal/v1/workspace-core/agent-registry/resolve",
            post(registry::resolve_agent),
        )
        .route(
            "/internal/v1/workspace-core/provider-registry/resolve",
            post(registry::resolve_provider),
        )
        .route(
            "/internal/v1/workspace-core/provider-registry/default",
            post(registry::default_provider),
        )
        .route(
            "/internal/v1/workspace-core/context-judge",
            post(judge::context),
        )
        .route("/internal/v1/workspace-core/plan-judge", post(judge::plan))
        .route(
            "/internal/v1/workspace-core/autonomy-judge",
            post(judge::autonomy),
        )
        .route(
            "/internal/v1/workspace-core/provider",
            post(provider::webhook),
        )
        .route(
            "/internal/v1/workspace-core/plan-dispatch",
            post(provider::dispatch_plan),
        )
        .with_state(state)
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "snake_case")]
struct PlatformPluginSnapshotRequest {
    version: u64,
    nonce: String,
    digest: String,
    payload: Value,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "snake_case")]
struct PlatformPluginAckRequest {
    version: u64,
    digest: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "snake_case")]
struct PlatformPluginNackRequest {
    reason: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "snake_case")]
struct PlatformPluginToolInvocationRequest {
    plugin_id: String,
    tool_id: String,
    input: Value,
}

pub(super) fn platform_plugin_router(
    state: Arc<LocalRuntimeState>,
) -> Router<Arc<LocalRuntimeState>> {
    Router::new()
        .route(
            "/api/v1/platform-plugins/snapshot",
            get(platform_plugin_snapshot).post(submit_platform_plugin_snapshot),
        )
        .route(
            "/api/v1/platform-plugins/apply-state",
            get(platform_plugin_apply_state),
        )
        .route(
            "/api/v1/platform-plugins/tools/invoke",
            post(invoke_platform_plugin_tool),
        )
        .route(
            "/api/v1/platform-plugins/frontend/:plugin_id/module",
            get(platform_plugin_frontend_module),
        )
        .route("/api/v1/platform-plugins/ack", post(platform_plugin_ack))
        .route("/api/v1/platform-plugins/nack", post(platform_plugin_nack))
        .layer(axum::middleware::from_fn_with_state(
            state.clone(),
            require_platform_plugin_session,
        ))
        .with_state(state)
}

async fn require_platform_plugin_session(
    State(state): State<Arc<LocalRuntimeState>>,
    mut request: Request<Body>,
    next: Next,
) -> Response {
    let credential = request
        .headers()
        .get(AUTHORIZATION)
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.strip_prefix("Bearer "));
    let authenticated = credential.and_then(|credential| {
        state
            .session_store
            .validate_session_credential(credential, chrono::Utc::now().timestamp_millis())
            .ok()
            .flatten()
    });
    let Some(authenticated) = authenticated else {
        return (
            StatusCode::UNAUTHORIZED,
            Json(json!({"detail": "authenticated desktop session required"})),
        )
            .into_response();
    };
    request.extensions_mut().insert(authenticated);
    next.run(request).await
}

async fn platform_plugin_snapshot(
    State(state): State<Arc<LocalRuntimeState>>,
) -> Result<Json<Value>, BridgeError> {
    let connection = state.session_store.connection().map_err(store_error)?;
    crate::plugin_snapshots::initialize_schema(&connection).map_err(store_error)?;
    if let Some(payload) =
        crate::plugin_snapshots::read_last_good(&connection).map_err(store_error)?
    {
        return Ok(Json(json!({"source": "last_good", "snapshot": payload})));
    }
    let requested = crate::plugin_snapshots::read_requested(&connection)
        .map_err(store_error)?
        .ok_or_else(|| not_found("platform plugin snapshot is unavailable"))?;
    Ok(Json(json!({
        "source": "requested",
        "version": requested.version,
        "nonce": requested.nonce,
        "digest": requested.digest,
        "payload": requested.payload,
    })))
}

async fn submit_platform_plugin_snapshot(
    State(state): State<Arc<LocalRuntimeState>>,
    Json(request): Json<PlatformPluginSnapshotRequest>,
) -> Result<Json<Value>, BridgeError> {
    validate_platform_plugin_snapshot(&request).map_err(|detail| bad_request(&detail))?;
    let mut connection = state.session_store.connection().map_err(store_error)?;
    crate::plugin_snapshots::initialize_schema(&connection).map_err(store_error)?;
    if let Some(record) =
        crate::plugin_snapshots::read_apply_record(&connection).map_err(store_error)?
    {
        let same_version = record.requested_version == request.version;
        let stale =
            request.version <= record.applied_version || request.version < record.requested_version;
        let same_snapshot = same_version && record.requested_digest == request.digest;
        if same_snapshot {
            return Ok(Json(json!({
                "status": record.status.as_str(),
                "idempotent": true,
            })));
        }
        if same_version || stale {
            let reason = if same_version {
                "snapshot version already belongs to another digest"
            } else {
                "snapshot version is stale"
            };
            crate::plugin_snapshots::record_nack(&connection, reason).map_err(store_error)?;
            return Err(conflict(reason));
        }
    }
    crate::plugin_snapshots::record_requested(
        &connection,
        request.version,
        &request.nonce,
        &request.digest,
        &request.payload.to_string(),
    )
    .map_err(store_error)?;
    let requested = RequestedPluginSnapshot {
        version: request.version,
        nonce: request.nonce.clone(),
        digest: request.digest.clone(),
        payload: request.payload.clone(),
    };
    activate_platform_plugin_snapshot(&mut connection, requested)
}

async fn platform_plugin_apply_state(
    State(state): State<Arc<LocalRuntimeState>>,
) -> Result<Json<Value>, BridgeError> {
    let connection = state.session_store.connection().map_err(store_error)?;
    crate::plugin_snapshots::initialize_schema(&connection).map_err(store_error)?;
    let record = crate::plugin_snapshots::read_apply_record(&connection)
        .map_err(store_error)?
        .ok_or_else(|| not_found("platform plugin apply state is unavailable"))?;
    let mut value = serde_json::to_value(&record)
        .map(Json)
        .map_err(|error| store_error(error.to_string()))?;
    if let (Some(object), Some(applied_digest)) =
        (value.as_object_mut(), record.applied_digest.as_deref())
    {
        let plugins = crate::plugin_snapshots::read_active_plugins(&connection, applied_digest)
            .map_err(store_error)?;
        let quota_usage = plugins
            .iter()
            .map(|plugin| {
                let quotas = plugin_quota_limits(&plugin.config).map_err(store_error)?;
                let monthly_usage = crate::plugin_snapshots::read_monthly_plugin_usage(
                    &connection,
                    &plugin.plugin_id,
                )
                .map_err(store_error)?;
                Ok::<Value, BridgeError>(json!({
                    "plugin_id": plugin.plugin_id,
                    "call_charge_usd_micros":
                        plugin_billing_usd_micros_per_call(&plugin.config)
                            .map_err(store_error)?,
                    "monthly_period": monthly_usage.as_ref().map(|usage| usage.period.as_str()),
                    "monthly_usd_micros_used":
                        monthly_usage.as_ref().map_or(0, |usage| usage.usd_micros),
                    "monthly_usd_micros_limit": quotas.max_monthly_usd_micros,
                    "artifact_storage_bytes":
                        crate::plugin_snapshots::runtime_artifact_storage_bytes(
                            &connection,
                            &plugin.plugin_id,
                        )
                        .map_err(store_error)?,
                    "artifact_storage_bytes_limit": quotas.max_storage_bytes,
                }))
            })
            .collect::<Result<Vec<_>, _>>()?;
        let plugins =
            serde_json::to_value(plugins).map_err(|error| store_error(error.to_string()))?;
        object.insert("active_plugins".to_string(), plugins);
        object.insert("quota_usage".to_string(), json!(quota_usage));
    }
    Ok(value)
}

async fn invoke_platform_plugin_tool(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<super::AuthenticatedContext>,
    Json(request): Json<PlatformPluginToolInvocationRequest>,
) -> Result<Json<Value>, BridgeError> {
    let plugin_id = request.plugin_id;
    let tool_id = request.tool_id;
    if !request.input.is_object() {
        return Err(bad_request("platform plugin tool input must be an object"));
    }
    let (plugin, artifact) = {
        let connection = state.session_store.connection().map_err(store_error)?;
        crate::plugin_snapshots::initialize_schema(&connection).map_err(store_error)?;
        let record = crate::plugin_snapshots::read_apply_record(&connection)
            .map_err(store_error)?
            .ok_or_else(|| unavailable("no platform plugin snapshot is active"))?;
        let applied_digest = record
            .applied_digest
            .as_deref()
            .ok_or_else(|| unavailable("no platform plugin snapshot is active"))?;
        let plugin = crate::plugin_snapshots::read_active_plugins(&connection, applied_digest)
            .map_err(store_error)?
            .into_iter()
            .find(|plugin| plugin.plugin_id == plugin_id)
            .ok_or_else(|| not_found("platform plugin is not active"))?;
        if !matches!(plugin.runtime.as_str(), "wasm" | "subprocess" | "mcp") {
            return Err(unavailable(
                "platform plugin runtime cannot execute locally",
            ));
        }
        if !plugin.capabilities.iter().any(|capability| {
            capability.get("kind").and_then(Value::as_str) == Some("tool")
                && capability.get("id").and_then(Value::as_str) == Some(tool_id.as_str())
        }) {
            return Err(not_found("platform plugin tool is not active"));
        }
        let artifact_digest = plugin
            .config
            .get("artifact")
            .and_then(Value::as_object)
            .and_then(|artifact| artifact.get("layer_sha256"))
            .and_then(Value::as_str)
            .ok_or_else(|| unavailable("platform plugin has no runtime artifact"))?;
        let artifact = crate::plugin_snapshots::read_runtime_artifact(
            &connection,
            &plugin_id,
            artifact_digest,
        )
        .map_err(store_error)?
        .ok_or_else(|| unavailable("platform plugin runtime artifact is unavailable"))?;
        (plugin, artifact)
    };

    let quotas = plugin_quota_limits(&plugin.config).map_err(|error| conflict(&error))?;
    let concurrency_permit = acquire_plugin_concurrency_permit(
        &plugin_id,
        quotas
            .max_concurrent_calls
            .unwrap_or(DEFAULT_MAX_CONCURRENT_PLUGIN_CALLS),
    )
    .await
    .map_err(|error| conflict(&error))?;
    if matches!(plugin.runtime.as_str(), "mcp" | "subprocess") {
        reserve_plugin_network_request(&plugin_id, quotas.max_network_requests_per_minute)
            .map_err(|error| conflict(&error))?;
    }
    reserve_plugin_monthly_usage(
        &state,
        &plugin_id,
        plugin_billing_usd_micros_per_call(&plugin.config).map_err(|error| conflict(&error))?,
        quotas.max_monthly_usd_micros,
    )
    .map_err(|error| conflict(&error))?;
    let max_output_bytes = quotas.max_output_bytes.unwrap_or(1024 * 1024);
    let input = request.input.to_string();
    let output = if plugin.runtime == "wasm" {
        invoke_wasm_plugin_tool(&tool_id, &plugin, &quotas, &artifact, &input).await?
    } else if plugin.runtime == "mcp" {
        return invoke_mcp_plugin_tool(
            &state,
            &authenticated,
            &plugin_id,
            &tool_id,
            request.input,
            &artifact,
            &quotas,
        )
        .await;
    } else {
        invoke_subprocess_plugin_tool(&tool_id, &plugin, &quotas, &artifact).await?
    };
    if output.len() > max_output_bytes {
        return Err(conflict("platform plugin tool exceeded its output quota"));
    }
    let result = serde_json::from_str::<Value>(&output)
        .map_err(|_| conflict("platform plugin tool returned invalid JSON"))?;
    drop(concurrency_permit);
    Ok(Json(result))
}

async fn acquire_plugin_concurrency_permit(
    plugin_id: &str,
    limit: usize,
) -> Result<OwnedSemaphorePermit, String> {
    static SEMAPHORES: OnceLock<Mutex<HashMap<String, Arc<Semaphore>>>> = OnceLock::new();
    let semaphores = SEMAPHORES.get_or_init(Mutex::default);
    let key = format!("{plugin_id}:{limit}");
    let semaphore = {
        let mut semaphores = semaphores.lock().expect("plugin concurrency quota lock");
        Arc::clone(
            semaphores
                .entry(key)
                .or_insert_with(|| Arc::new(Semaphore::new(limit))),
        )
    };
    semaphore
        .try_acquire_owned()
        .map_err(|_| "platform plugin exceeded its concurrent-call quota".to_string())
}

fn reserve_plugin_network_request(plugin_id: &str, limit: Option<u64>) -> Result<(), String> {
    let Some(limit) = limit else {
        return Ok(());
    };
    static WINDOWS: OnceLock<Mutex<HashMap<String, (std::time::Instant, u64)>>> = OnceLock::new();
    let windows = WINDOWS.get_or_init(Mutex::default);
    let mut windows = windows.lock().expect("plugin network quota lock");
    let now = std::time::Instant::now();
    let window = windows.entry(plugin_id.to_string()).or_insert((now, 0));
    if now.duration_since(window.0) >= Duration::from_secs(60) {
        *window = (now, 0);
    }
    if window.1 >= limit {
        return Err("platform plugin exceeded its network quota".to_string());
    }
    window.1 += 1;
    Ok(())
}

fn reserve_plugin_monthly_usage(
    state: &Arc<LocalRuntimeState>,
    plugin_id: &str,
    charge_usd_micros: u64,
    max_usd_micros: Option<u64>,
) -> Result<(), String> {
    let connection = state
        .session_store
        .connection()
        .map_err(|error| error.to_string())?;
    crate::plugin_snapshots::initialize_schema(&connection)?;
    let period = chrono::Utc::now().format("%Y-%m").to_string();
    crate::plugin_snapshots::reserve_monthly_plugin_usage(
        &connection,
        plugin_id,
        &period,
        charge_usd_micros,
        max_usd_micros,
    )
}

async fn invoke_mcp_plugin_tool(
    state: &Arc<LocalRuntimeState>,
    authenticated: &super::AuthenticatedContext,
    plugin_id: &str,
    tool_id: &str,
    input: Value,
    artifact: &crate::plugin_snapshots::RuntimeArtifact,
    quotas: &PluginQuotaLimits,
) -> Result<Json<Value>, BridgeError> {
    let encoded_input = serde_json::to_string(&input)
        .map_err(|_| bad_request("platform plugin MCP input is invalid"))?;
    if encoded_input.len() > MAX_PLATFORM_PLUGIN_MCP_INPUT_BYTES {
        return Err(conflict(
            "platform plugin MCP request exceeds its input quota",
        ));
    }
    let scope = McpScope {
        tenant_id: authenticated.workspace.tenant_id.clone(),
        project_id: authenticated.workspace.project_id.clone(),
    };
    super::platform_plugin_sync::ensure_platform_mcp_runtime(
        state,
        &scope,
        &json!({"id": plugin_id}),
        artifact,
    )
    .map_err(|error| unavailable(&error))?;
    let server_name = format!("platform-plugin-{plugin_id}");
    let server = state
        .mcp_supervisor
        .server_by_name(&scope, &server_name)
        .map_err(|error| unavailable(&format!("{}: {}", error.reason_code(), error.detail())))?
        .ok_or_else(|| unavailable("platform plugin MCP server is unavailable"))?;
    let request_hash = Sha256::digest(
        format!(
            "{}\n{}\n{}",
            plugin_id,
            tool_id,
            serde_json::to_string(&input)
                .map_err(|_| bad_request("platform plugin tool input is invalid"))?
        )
        .as_bytes(),
    );
    let idempotency_key = format!(
        "platform-plugin-call-{}",
        request_hash
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>()
    );
    let call = state
        .mcp_supervisor
        .call_tool(&scope, &server.id, tool_id, input, &idempotency_key);
    let outcome = match quotas.max_wall_time_ms {
        Some(limit) => tokio::time::timeout(std::time::Duration::from_millis(limit), call)
            .await
            .map_err(|_| conflict("platform plugin MCP tool exceeded its wall-time quota"))?,
        None => call.await,
    }
    .map_err(|error| conflict(&format!("{}: {}", error.reason_code(), error.detail())))?;
    if outcome.is_error {
        return Err(conflict("platform plugin MCP tool failed"));
    }
    let result = serde_json::to_value(&outcome.result)
        .map_err(|_| conflict("platform plugin MCP tool returned invalid JSON"))?;
    if serde_json::to_string(&result)
        .map(|encoded| encoded.len())
        .unwrap_or(usize::MAX)
        > quotas.max_output_bytes.unwrap_or(1024 * 1024)
    {
        return Err(conflict(
            "platform plugin MCP tool exceeded its output quota",
        ));
    }
    Ok(Json(result))
}

async fn invoke_wasm_plugin_tool(
    tool_id: &str,
    plugin: &crate::plugin_snapshots::PluginActivationRecord,
    quotas: &PluginQuotaLimits,
    artifact: &crate::plugin_snapshots::RuntimeArtifact,
    input: &str,
) -> Result<String, BridgeError> {
    let fuel = quotas.max_wasm_fuel.unwrap_or(DEFAULT_FUEL);
    let memory = quotas.max_wasm_memory_bytes.unwrap_or(DEFAULT_MEMORY_BYTES);
    let wall_time = quotas
        .max_wall_time_ms
        .map(std::time::Duration::from_millis)
        .unwrap_or(std::time::Duration::from_secs(5));
    let tool = WasmtimeTool::from_bytes_with_limits(
        tool_id.to_string(),
        plugin.plugin_version.clone(),
        &artifact.bytes,
        fuel,
        memory,
        Some(wall_time),
    )
    .map_err(|error| unavailable(&format!("platform plugin tool cannot start: {error}")))?;
    tool.invoke(input)
        .await
        .map_err(|error| conflict(&format!("platform plugin tool failed: {error}")))
}

async fn invoke_subprocess_plugin_tool(
    tool_id: &str,
    plugin: &crate::plugin_snapshots::PluginActivationRecord,
    quotas: &PluginQuotaLimits,
    artifact: &crate::plugin_snapshots::RuntimeArtifact,
) -> Result<String, BridgeError> {
    let definition = serde_json::from_slice::<Value>(&artifact.bytes)
        .map_err(|_| bad_request("subprocess plugin runtime JSON is invalid"))?;
    let command = definition
        .get("command")
        .and_then(Value::as_array)
        .and_then(|items| {
            items
                .iter()
                .map(|item| item.as_str().map(str::to_string))
                .collect::<Option<Vec<_>>>()
        })
        .filter(|command| !command.is_empty() && command.len() <= 64)
        .ok_or_else(|| bad_request("subprocess plugin command is invalid"))?;
    if command.iter().any(|argument| {
        argument.is_empty()
            || argument.len() > 4096
            || argument.chars().any(|character| character.is_control())
    }) {
        return Err(bad_request("subprocess plugin command is invalid"));
    }
    let mut timeout_ms = definition
        .get("timeout_ms")
        .and_then(Value::as_u64)
        .unwrap_or(1_000)
        .min(5_000);
    if let Some(quota_ms) = quotas.max_wall_time_ms {
        timeout_ms = timeout_ms.min(quota_ms);
    }
    if timeout_ms == 0 {
        return Err(bad_request("subprocess plugin timeout must be positive"));
    }

    let mut command_builder = tokio::process::Command::new(&command[0]);
    command_builder
        .args(&command[1..])
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .kill_on_drop(true);
    #[cfg(unix)]
    {
        command_builder.process_group(0);
    }
    let mut child = command_builder
        .spawn()
        .map_err(|error| conflict(&format!("subprocess plugin failed to start: {error}")))?;
    let mut stdout = child.stdout.take();
    let mut stderr = child.stderr.take();
    let read_stdout = async {
        let mut bytes = Vec::new();
        if let Some(stdout) = stdout.as_mut() {
            let _ = stdout.read_to_end(&mut bytes).await;
        }
        bytes
    };
    let read_stderr = async {
        let mut bytes = Vec::new();
        if let Some(stderr) = stderr.as_mut() {
            let _ = stderr.read_to_end(&mut bytes).await;
        }
        bytes
    };
    let wait = child.wait();
    let (status, stdout, stderr) =
        tokio::time::timeout(std::time::Duration::from_millis(timeout_ms), async {
            tokio::join!(wait, read_stdout, read_stderr)
        })
        .await
        .map_err(|_| conflict("subprocess plugin exceeded its wall-time quota"))?;
    let status = status.map_err(|error| conflict(&format!("subprocess plugin failed: {error}")))?;
    if stdout.len() > 1024 * 1024 || stderr.len() > 1024 * 1024 {
        return Err(conflict("subprocess plugin exceeded its output quota"));
    }
    Ok(json!({
        "tool": tool_id,
        "plugin_id": plugin.plugin_id,
        "exit_code": status.code(),
        "stdout": String::from_utf8_lossy(&stdout),
        "stderr": String::from_utf8_lossy(&stderr),
    })
    .to_string())
}

async fn platform_plugin_frontend_module(
    State(state): State<Arc<LocalRuntimeState>>,
    Path(plugin_id): Path<String>,
) -> Result<Json<Value>, BridgeError> {
    let (plugin, artifact) = {
        let connection = state.session_store.connection().map_err(store_error)?;
        crate::plugin_snapshots::initialize_schema(&connection).map_err(store_error)?;
        let record = crate::plugin_snapshots::read_apply_record(&connection)
            .map_err(store_error)?
            .ok_or_else(|| unavailable("no platform plugin snapshot is active"))?;
        let applied_digest = record
            .applied_digest
            .as_deref()
            .ok_or_else(|| unavailable("no platform plugin snapshot is active"))?;
        let plugin = crate::plugin_snapshots::read_active_plugins(&connection, applied_digest)
            .map_err(store_error)?
            .into_iter()
            .find(|plugin| plugin.plugin_id == plugin_id)
            .ok_or_else(|| not_found("platform plugin is not active"))?;
        if plugin.runtime != "frontend" || !matches!(plugin.trust.as_str(), "builtin" | "signed") {
            return Err(unavailable(
                "platform plugin frontend runtime is unavailable",
            ));
        }
        let artifact_digest = plugin
            .config
            .get("artifact")
            .and_then(Value::as_object)
            .and_then(|artifact| artifact.get("layer_sha256"))
            .and_then(Value::as_str)
            .ok_or_else(|| unavailable("platform plugin has no runtime artifact"))?;
        let artifact = crate::plugin_snapshots::read_runtime_artifact(
            &connection,
            &plugin_id,
            artifact_digest,
        )
        .map_err(store_error)?
        .ok_or_else(|| unavailable("platform plugin runtime artifact is unavailable"))?;
        (plugin, artifact)
    };
    let module = serde_json::from_slice::<Value>(&artifact.bytes)
        .map_err(|_| unavailable("platform plugin frontend module is invalid"))?;
    let html = module
        .get("html")
        .and_then(Value::as_str)
        .ok_or_else(|| unavailable("platform plugin frontend module has no html payload"))?;
    let quotas = plugin_quota_limits(&plugin.config).map_err(|error| conflict(&error))?;
    if html.len() > quotas.max_output_bytes.unwrap_or(1024 * 1024) {
        return Err(conflict(
            "platform plugin frontend module exceeds its quota",
        ));
    }
    Ok(Json(json!({
        "plugin_id": plugin_id,
        "digest": artifact.digest,
        "trust": plugin.trust,
        "html": html,
        "slots": module.get("slots").cloned().unwrap_or_else(|| json!([])),
    })))
}

async fn platform_plugin_ack(
    State(state): State<Arc<LocalRuntimeState>>,
    Json(request): Json<PlatformPluginAckRequest>,
) -> Result<Json<Value>, BridgeError> {
    let mut connection = state.session_store.connection().map_err(store_error)?;
    crate::plugin_snapshots::initialize_schema(&connection).map_err(store_error)?;
    let requested = crate::plugin_snapshots::read_requested(&connection)
        .map_err(store_error)?
        .ok_or_else(|| conflict("platform plugin snapshot has not been requested"))?;
    if requested.version != request.version || requested.digest != request.digest {
        let reason = "ACK does not match the requested platform plugin snapshot";
        crate::plugin_snapshots::record_nack(&connection, reason).map_err(store_error)?;
        return Err(conflict(reason));
    }
    activate_platform_plugin_snapshot(&mut connection, requested)
}

fn activate_platform_plugin_snapshot(
    connection: &mut std::sync::MutexGuard<'_, rusqlite::Connection>,
    requested: RequestedPluginSnapshot,
) -> Result<Json<Value>, BridgeError> {
    match crate::plugin_snapshots::record_ack(connection, &requested) {
        Ok(activated) => {
            let activated =
                serde_json::to_value(activated).map_err(|error| store_error(error.to_string()))?;
            Ok(Json(json!({
                "status": "ack",
                "activated_plugins": activated,
            })))
        }
        Err(error) => {
            crate::plugin_snapshots::record_nack(connection, &error).map_err(store_error)?;
            Err(conflict(&error))
        }
    }
}

async fn platform_plugin_nack(
    State(state): State<Arc<LocalRuntimeState>>,
    Json(request): Json<PlatformPluginNackRequest>,
) -> Result<Json<Value>, BridgeError> {
    if request.reason.trim().is_empty() || request.reason.len() > 2048 {
        return Err(bad_request("NACK reason must contain 1..2048 characters"));
    }
    let connection = state.session_store.connection().map_err(store_error)?;
    crate::plugin_snapshots::initialize_schema(&connection).map_err(store_error)?;
    if crate::plugin_snapshots::read_requested(&connection)
        .map_err(store_error)?
        .is_none()
    {
        return Err(conflict("platform plugin snapshot has not been requested"));
    }
    crate::plugin_snapshots::record_nack(&connection, request.reason.trim())
        .map_err(store_error)?;
    Ok(Json(json!({"status": "nack"})))
}

fn validate_platform_plugin_snapshot(
    request: &PlatformPluginSnapshotRequest,
) -> Result<(), String> {
    if request.version == 0 {
        return Err("snapshot version must be positive".to_string());
    }
    if request.nonce.trim().is_empty() || request.nonce.len() > 128 {
        return Err("snapshot nonce must contain 1..128 characters".to_string());
    }
    if request.digest.len() != 64 || !request.digest.chars().all(|ch| ch.is_ascii_hexdigit()) {
        return Err("snapshot digest must be 64 hexadecimal characters".to_string());
    }
    let Some(payload) = request.payload.as_object() else {
        return Err("snapshot payload must be an object".to_string());
    };
    if payload.get("schema_version").and_then(Value::as_u64) != Some(1) {
        return Err("snapshot schema_version must be 1".to_string());
    }
    if !payload
        .get("profile_id")
        .and_then(Value::as_str)
        .is_some_and(|value| !value.trim().is_empty())
    {
        return Err("snapshot profile_id is required".to_string());
    }
    if !payload.get("plugins").is_some_and(Value::is_array) {
        return Err("snapshot plugins must be an array".to_string());
    }
    if payload.get("digest").and_then(Value::as_str) != Some(request.digest.as_str()) {
        return Err("snapshot payload digest does not match the envelope".to_string());
    }
    let actual_digest = platform_plugin_payload_digest(&request.payload)?;
    if actual_digest != request.digest {
        return Err("snapshot digest does not match its canonical payload".to_string());
    }
    Ok(())
}

pub(super) fn platform_plugin_payload_digest(payload: &Value) -> Result<String, String> {
    let mut canonical = payload.clone();
    if let Some(object) = canonical.as_object_mut() {
        object.remove("digest");
    }
    super::tool_authority::canonical_json_digest(&canonical).map_err(|error| error.to_string())
}

#[derive(Clone, Copy)]
pub(super) enum TokenKind {
    Registry,
    Provider,
}

pub(super) fn authorize(
    state: &LocalRuntimeState,
    headers: &HeaderMap,
    kind: TokenKind,
) -> Result<Arc<WorkspaceCoreAuthority>, BridgeError> {
    let authority = state
        .workspace_core_authority
        .lock()
        .expect("Workspace Core authority")
        .clone()
        .ok_or_else(|| unavailable("Workspace Core Desktop authority is not installed"))?;
    let expected = match kind {
        TokenKind::Registry => authority.agent_registry_token.as_str(),
        TokenKind::Provider => authority.provider_webhook_token.as_str(),
    };
    let supplied = headers
        .get(AUTHORIZATION)
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.strip_prefix("Bearer "));
    if supplied.map_or(true, |supplied| !secret_matches(supplied, expected)) {
        return Err((
            StatusCode::UNAUTHORIZED,
            Json(json!({ "detail": "Unauthorized" })),
        ));
    }
    Ok(authority)
}

pub(super) enum RequestClaim {
    Claimed,
    Duplicate(Value),
}

pub(super) fn claim_request(
    state: &LocalRuntimeState,
    request_id: &str,
    channel: &str,
    request: &impl Serialize,
    response: &Value,
) -> Result<RequestClaim, BridgeError> {
    let encoded = serde_json::to_vec(request)
        .map_err(|_| bad_request("Workspace Core request cannot be encoded"))?;
    let request_hash = Sha256::digest(encoded)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    match state.session_store.claim_workspace_core_request(
        request_id,
        channel,
        &request_hash,
        response,
        &super::now_iso(),
    ) {
        Ok(DesktopWorkspaceCoreRequestClaim::Claimed) => Ok(RequestClaim::Claimed),
        Ok(DesktopWorkspaceCoreRequestClaim::Duplicate(response)) => {
            Ok(RequestClaim::Duplicate(response))
        }
        Err(DesktopWorkspaceCoreRequestClaimError::PayloadConflict) => Err(conflict(
            "Workspace Core request id is already bound to another payload",
        )),
        Err(DesktopWorkspaceCoreRequestClaimError::Storage(error)) => Err(store_error(error)),
    }
}

pub(super) fn ensure_workspace_scope(
    _state: &LocalRuntimeState,
    tenant_id: &str,
    project_id: &str,
    workspace_id: &str,
) -> Result<(), BridgeError> {
    for value in [tenant_id, project_id, workspace_id] {
        if value.trim().is_empty() || value.len() > 255 {
            return Err(bad_request("Workspace Core callback scope is invalid"));
        }
    }
    Ok(())
}

fn validate_authority(
    state: &LocalRuntimeState,
    core_api_base_url: &str,
    service_token: &str,
    agent_registry_token: &str,
    provider_webhook_token: &str,
    provider_event_token: &str,
) -> Result<(), String> {
    let url = Url::parse(core_api_base_url)
        .map_err(|_| "Workspace Core API base URL is invalid".to_string())?;
    if url.scheme() != "http"
        || url.host_str() != Some("127.0.0.1")
        || url.port().is_none()
        || !url.username().is_empty()
        || url.password().is_some()
        || url.path() != "/"
        || url.query().is_some()
        || url.fragment().is_some()
    {
        return Err("Workspace Core API base URL must be an exact loopback origin".to_string());
    }
    let tokens = [
        service_token,
        agent_registry_token,
        provider_webhook_token,
        provider_event_token,
        state.api_token.as_str(),
    ];
    if tokens.iter().any(|token| token.trim().is_empty())
        || tokens
            .iter()
            .enumerate()
            .any(|(index, token)| tokens[index + 1..].contains(token))
    {
        return Err(
            "Workspace Core bridge credentials must be non-empty and mutually distinct".to_string(),
        );
    }
    Ok(())
}

fn secret_matches(left: &str, right: &str) -> bool {
    let left = Sha256::digest(left.as_bytes());
    let right = Sha256::digest(right.as_bytes());
    left.iter()
        .zip(right.iter())
        .fold(0_u8, |difference, (a, b)| difference | (a ^ b))
        == 0
}

pub(super) fn bad_request(detail: &str) -> BridgeError {
    (StatusCode::BAD_REQUEST, Json(json!({ "detail": detail })))
}

pub(super) fn forbidden(detail: &str) -> BridgeError {
    (StatusCode::FORBIDDEN, Json(json!({ "detail": detail })))
}

pub(super) fn not_found(detail: &str) -> BridgeError {
    (StatusCode::NOT_FOUND, Json(json!({ "detail": detail })))
}

pub(super) fn conflict(detail: &str) -> BridgeError {
    (StatusCode::CONFLICT, Json(json!({ "detail": detail })))
}

pub(super) fn unavailable(detail: &str) -> BridgeError {
    (
        StatusCode::SERVICE_UNAVAILABLE,
        Json(json!({
            "detail": detail,
            "reason_code": "workspace_core_unavailable",
        })),
    )
}

pub(super) fn store_error(error: String) -> BridgeError {
    tracing::error!(error = %error, "Workspace Core Desktop store operation failed");
    unavailable("Workspace Core Desktop store is unavailable")
}

#[cfg(test)]
mod tests;
