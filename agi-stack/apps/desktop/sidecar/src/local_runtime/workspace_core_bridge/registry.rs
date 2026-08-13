use std::sync::Arc;

use axum::{extract::State, http::HeaderMap, Json};
use serde_json::{json, Value};

use super::{
    authorize, bad_request,
    contracts::{AgentRegistryLookup, ProviderRegistryDefaultLookup, ProviderRegistryLookup},
    forbidden, store_error, BridgeResult, TokenKind,
};
use crate::local_runtime::{
    provider_supports_route_model, resource_registry::ManagedResourceKind, LocalRuntimeState,
    ProviderRuntimeKey,
};

pub(super) async fn resolve_agent(
    State(state): State<Arc<LocalRuntimeState>>,
    headers: HeaderMap,
    Json(lookup): Json<AgentRegistryLookup>,
) -> BridgeResult {
    authorize(&state, &headers, TokenKind::Registry)?;
    validate_identifier(&lookup.tenant_id, 128)?;
    validate_identifier(&lookup.project_id, 128)?;
    validate_identifier(&lookup.agent_id, 128)?;
    ensure_project_scope(&state, &lookup.tenant_id, &lookup.project_id)?;
    let agent = state
        .session_store
        .managed_resource(
            ManagedResourceKind::Agent,
            "project",
            &lookup.project_id,
            &lookup.agent_id,
        )
        .map_err(store_error)?;
    let Some(agent) = agent.filter(agent_available) else {
        return Ok(Json(json!({
            "available": false,
            "agent_id": null,
            "name": null,
            "display_name": null,
            "enabled": null
        })));
    };
    Ok(Json(json!({
        "available": true,
        "agent_id": agent["id"],
        "name": agent["name"],
        "display_name": agent.get("display_name"),
        "enabled": true
    })))
}

pub(super) async fn resolve_provider(
    State(state): State<Arc<LocalRuntimeState>>,
    headers: HeaderMap,
    Json(lookup): Json<ProviderRegistryLookup>,
) -> BridgeResult {
    authorize(&state, &headers, TokenKind::Registry)?;
    validate_identifier(&lookup.tenant_id, 128)?;
    validate_identifier(&lookup.provider_id, 128)?;
    validate_identifier(&lookup.model_id, 512)?;
    let provider = state
        .session_store
        .managed_resource(
            ManagedResourceKind::Provider,
            "tenant",
            &lookup.tenant_id,
            &lookup.provider_id,
        )
        .map_err(store_error)?;
    let available = provider
        .as_ref()
        .is_some_and(|provider| provider_available(provider, &lookup.model_id));
    Ok(Json(provider_response(
        available,
        &lookup.provider_id,
        &lookup.model_id,
    )))
}

pub(super) async fn default_provider(
    State(state): State<Arc<LocalRuntimeState>>,
    headers: HeaderMap,
    Json(lookup): Json<ProviderRegistryDefaultLookup>,
) -> BridgeResult {
    authorize(&state, &headers, TokenKind::Registry)?;
    validate_identifier(&lookup.tenant_id, 128)?;
    let selected = {
        let runtime = state
            .provider_runtime
            .lock()
            .expect("provider runtime state");
        runtime
            .selections
            .get(&lookup.tenant_id)
            .and_then(|provider_id| {
                let key = ProviderRuntimeKey {
                    tenant_id: lookup.tenant_id.clone(),
                    provider_id: provider_id.clone(),
                };
                runtime
                    .bindings
                    .get(&key)
                    .map(|binding| (provider_id.clone(), binding.model.clone()))
            })
    };
    let Some((provider_id, model_id)) = selected else {
        return Ok(Json(unavailable_provider_response()));
    };
    let provider = state
        .session_store
        .managed_resource(
            ManagedResourceKind::Provider,
            "tenant",
            &lookup.tenant_id,
            &provider_id,
        )
        .map_err(store_error)?;
    let available = provider
        .as_ref()
        .is_some_and(|provider| provider_available(provider, &model_id));
    Ok(Json(provider_response(available, &provider_id, &model_id)))
}

pub(super) fn ensure_agent_available(
    state: &LocalRuntimeState,
    project_id: &str,
    agent_id: &str,
) -> Result<(), super::BridgeError> {
    let agent = state
        .session_store
        .managed_resource(ManagedResourceKind::Agent, "project", project_id, agent_id)
        .map_err(store_error)?;
    if agent.as_ref().map_or(true, agent_available) {
        return agent.map_or_else(|| Err(super::not_found("Agent not found")), |_| Ok(()));
    }
    Err(forbidden("Agent is disabled"))
}

pub(super) fn ensure_project_scope(
    state: &LocalRuntimeState,
    tenant_id: &str,
    project_id: &str,
) -> Result<(), super::BridgeError> {
    let tenant = state
        .session_store
        .project_tenant_id(project_id)
        .map_err(store_error)?;
    if tenant.as_deref() == Some(tenant_id) {
        Ok(())
    } else {
        Err(forbidden("Request is outside the trusted project scope"))
    }
}

fn agent_available(agent: &Value) -> bool {
    agent.get("status").and_then(Value::as_str) == Some("active")
        && agent.get("enabled").and_then(Value::as_bool) == Some(true)
}

fn provider_available(provider: &Value, model_id: &str) -> bool {
    provider.get("is_active").and_then(Value::as_bool) == Some(true)
        && provider_supports_route_model(provider, model_id)
}

fn provider_response(available: bool, provider_id: &str, model_id: &str) -> Value {
    if available {
        json!({
            "available": true,
            "provider_id": provider_id,
            "model_id": model_id
        })
    } else {
        unavailable_provider_response()
    }
}

fn unavailable_provider_response() -> Value {
    json!({ "available": false, "provider_id": null, "model_id": null })
}

fn validate_identifier(value: &str, max_length: usize) -> Result<(), super::BridgeError> {
    if value.is_empty() || value != value.trim() || value.len() > max_length {
        Err(bad_request("Workspace Core identifier is invalid"))
    } else {
        Ok(())
    }
}
