//! Private Workspace Core to Desktop LocalRuntime authority bridge.

use std::sync::{atomic::Ordering, Arc};

use axum::{
    http::{header::AUTHORIZATION, HeaderMap, StatusCode},
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

pub(super) type BridgeError = (StatusCode, Json<Value>);
pub(super) type BridgeResult = Result<Json<Value>, BridgeError>;

pub(super) struct WorkspaceCoreAuthority {
    generation: u64,
    core_api_base_url: String,
    agent_registry_token: Zeroizing<String>,
    provider_webhook_token: Zeroizing<String>,
    provider_event_token: Zeroizing<String>,
    client: reqwest::Client,
}

pub(super) fn install_authority(
    state: &LocalRuntimeState,
    core_api_base_url: String,
    agent_registry_token: String,
    provider_webhook_token: String,
    provider_event_token: String,
) -> Result<u64, String> {
    validate_authority(
        state,
        &core_api_base_url,
        &agent_registry_token,
        &provider_webhook_token,
        &provider_event_token,
    )?;
    let generation = state
        .workspace_core_generation
        .fetch_update(Ordering::AcqRel, Ordering::Acquire, |current| {
            current.checked_add(1)
        })
        .map_err(|_| "Workspace Core authority generation is exhausted".to_string())?
        + 1;
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
        agent_registry_token: Zeroizing::new(agent_registry_token),
        provider_webhook_token: Zeroizing::new(provider_webhook_token),
        provider_event_token: Zeroizing::new(provider_event_token),
        client,
    }));
    Ok(generation)
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
    state: &LocalRuntimeState,
    tenant_id: &str,
    project_id: &str,
    workspace_id: &str,
) -> Result<(), BridgeError> {
    let actual_project = state
        .session_store
        .workspace_project_id(workspace_id)
        .map_err(store_error)?;
    let actual_tenant = state
        .session_store
        .workspace_tenant_id(workspace_id)
        .map_err(store_error)?;
    if actual_project.is_none() || actual_tenant.is_none() {
        return Err(not_found("Workspace not found"));
    }
    if actual_project.as_deref() != Some(project_id) || actual_tenant.as_deref() != Some(tenant_id)
    {
        return Err(forbidden(
            "Request is outside the trusted Workspace Core scope",
        ));
    }
    Ok(())
}

fn validate_authority(
    state: &LocalRuntimeState,
    core_api_base_url: &str,
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
        Json(json!({ "detail": detail })),
    )
}

pub(super) fn store_error(error: String) -> BridgeError {
    tracing::error!(error = %error, "Workspace Core Desktop store operation failed");
    unavailable("Workspace Core Desktop store is unavailable")
}

#[cfg(test)]
mod tests;
