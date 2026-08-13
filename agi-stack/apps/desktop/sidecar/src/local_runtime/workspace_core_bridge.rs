//! Private Workspace Core to Desktop LocalRuntime authority bridge.

use std::sync::{atomic::Ordering, Arc};

use axum::{
    body::{to_bytes, Body},
    extract::State,
    http::{header::AUTHORIZATION, HeaderMap, HeaderName, Request, StatusCode},
    middleware::Next,
    response::{IntoResponse, Response},
    routing::post,
    Json, Router,
};
use serde::Serialize;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use url::Url;
use zeroize::Zeroizing;

use super::{
    session_store::{DesktopWorkspaceCoreRequestClaim, DesktopWorkspaceCoreRequestClaimError},
    LocalRuntimeState,
};

mod contracts;
mod judge;
mod provider;
mod registry;

const CALLBACK_TIMEOUT_SECONDS: u64 = 10;
const MAX_PROXY_REQUEST_BYTES: usize = 64 * 1024 * 1024;
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
    if workspace_core_cutover_started(&state) && workspace_proxy_scope(request.uri().path()).is_ok()
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
    mut request: Request<Body>,
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
    if is_task_session_scope(&path) {
        prepare_task_session_request(&mut request)?;
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

fn prepare_task_session_request(request: &mut Request<Body>) -> Result<(), BridgeError> {
    let idempotency_key = request
        .headers()
        .get("x-idempotency-key")
        .or_else(|| request.headers().get("idempotency-key"))
        .cloned();
    if let Some(idempotency_key) = idempotency_key {
        request
            .headers_mut()
            .insert("x-idempotency-key", idempotency_key);
    }
    Ok(())
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
