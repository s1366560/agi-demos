//! Explicit native Provider route using the existing runtime/vault binding.
//! Credentials remain private in memory and are never formatted or persisted here.
use agistack_adapters_http_llm::HttpEmbedding;
use agistack_core::knowledge::{index::IndexProfile, KnowledgeResult};
use rusqlite::{params, Connection, OptionalExtension};
use std::num::NonZeroU32;

use super::*;
use crate::local_runtime::{
    provider_credentials::provider_credential_binding_digest, provider_supports_route_model,
    runtime_binding_from_provider, LocalRuntimeState, ProviderRuntimeKey,
};

#[derive(Clone, Debug, PartialEq, Eq)]
pub(super) struct EmbeddingRoute {
    pub(super) provider_id: String,
    pub(super) model_id: String,
    pub(super) provider_revision: u64,
}

// Deliberately no Debug/Serialize: private credential snapshots are only compared
// within this process. Revision + connection binding are the durable provenance;
// changing an environment variable's value across restart without a Provider
// revision is not detected by that existing credential-generation contract.
pub(super) struct EmbeddingProvider {
    route: EmbeddingRoute,
    binding_digest: String,
    provider_type: String,
    base_url: String,
    auth_method: String,
    credential: Option<String>,
}
impl EmbeddingProvider {
    pub(super) fn client(&self) -> HttpEmbedding {
        let client = HttpEmbedding::new(&self.base_url, &self.route.model_id);
        match &self.credential {
            Some(value) => client.with_api_key(value),
            None => client,
        }
    }
    pub(super) fn profile(&self, dimensions: NonZeroU32) -> IndexProfile {
        IndexProfile {
            provider_id: self.route.provider_id.clone(),
            provider_revision: self.route.provider_revision,
            credential_binding_digest: self.binding_digest.clone(),
            model_id: self.route.model_id.clone(),
            dimensions,
            input_contract_version: 1,
            normalization_version: 1,
        }
    }
}

pub(super) fn resolve(
    operation: &KnowledgeOperationV2,
    state: &LocalRuntimeState,
    auth: &AuthenticatedContext,
    route: &EmbeddingRoute,
    write: bool,
) -> Result<EmbeddingProvider, KnowledgeAuthorityErrorV2> {
    if write && !operation.writable {
        return Err(KnowledgeAuthorityErrorV2::Forbidden);
    }
    super::processing_context::with_read_current(operation, state, auth, |_| Ok(()))?;
    let provider = {
        let runtime = state
            .provider_runtime
            .lock()
            .map_err(|_| KnowledgeAuthorityErrorV2::TransportUnavailable)?;
        let connection = state
            .session_store
            .connection()
            .map_err(|_| KnowledgeAuthorityErrorV2::Forbidden)?;
        let value = read_provider(&connection, &operation.scope.tenant_id, route)?;
        let binding = runtime_binding_from_provider(&value).ok_or(KnowledgeError::Conflict)?;
        if !matches!(
            binding.provider_type.as_str(),
            "openai" | "openai_compatible"
        ) {
            return Err(KnowledgeAuthorityErrorV2::TransportUnavailable);
        }
        let key = ProviderRuntimeKey {
            tenant_id: operation.scope.tenant_id.clone(),
            provider_id: route.provider_id.clone(),
        };
        let credential = runtime.credentials.get(&key).cloned();
        if binding.auth_method == "none" && credential.is_some() {
            return Err(KnowledgeError::Conflict.into());
        }
        if binding.auth_method != "none"
            && credential.as_ref().map_or(true, |v| v.trim().is_empty())
        {
            return Err(KnowledgeAuthorityErrorV2::TransportUnavailable);
        }
        EmbeddingProvider {
            route: route.clone(),
            binding_digest: provider_credential_binding_digest(
                &binding.provider_type,
                &binding.base_url,
                &binding.auth_method,
            ),
            provider_type: binding.provider_type,
            base_url: binding.base_url,
            auth_method: binding.auth_method,
            credential,
        }
    };
    with_current(operation, state, auth, &provider, write, |_| Ok(()))?;
    Ok(provider)
}

fn read_provider(
    connection: &Connection,
    tenant: &str,
    route: &EmbeddingRoute,
) -> KnowledgeResult<Value> {
    if route.provider_id.trim().is_empty() || route.model_id.trim().is_empty() {
        return Err(KnowledgeError::InvalidInput);
    }
    let row:Option<(u64,String)>=connection.query_row(
        "SELECT revision,value_json FROM desktop_managed_resources WHERE kind='provider' AND scope_kind='tenant'
         AND scope_id=?1 AND id=?2 AND status='active'",params![tenant,route.provider_id],|r|Ok((r.get(0)?,r.get(1)?)),
    ).optional().map_err(|_|KnowledgeError::Conflict)?;
    let (revision, json) = row.ok_or(KnowledgeError::Conflict)?;
    let value: Value = serde_json::from_str(&json).map_err(|_| KnowledgeError::Conflict)?;
    if revision != route.provider_revision
        || value.get("revision").and_then(Value::as_u64) != Some(revision)
        || value.get("id").and_then(Value::as_str) != Some(route.provider_id.as_str())
        || value.get("tenant_id").and_then(Value::as_str) != Some(tenant)
        || value.get("is_active").and_then(Value::as_bool) != Some(true)
        || !provider_supports_route_model(&value, &route.model_id)
    {
        return Err(KnowledgeError::Conflict);
    }
    Ok(value)
}

/// Write lock order is runtime -> auth -> generation -> knowledge. Reads check
/// generation again after their action instead of retaining its lock. The
/// auth-held durable recheck covers deletion before runtime cleanup.
/// No lock crosses the network request. Unlike extraction's pinned completion,
/// index publication rejects a retired generation and relies on lease reclaim.
pub(super) fn with_current<T>(
    operation: &KnowledgeOperationV2,
    state: &LocalRuntimeState,
    auth: &AuthenticatedContext,
    provider: &EmbeddingProvider,
    write: bool,
    action: impl FnOnce(&dyn Fn() -> KnowledgeResult<i64>) -> KnowledgeResult<T>,
) -> Result<T, KnowledgeAuthorityErrorV2> {
    if write && !operation.writable {
        return Err(KnowledgeAuthorityErrorV2::Forbidden);
    }
    let runtime = state
        .provider_runtime
        .lock()
        .map_err(|_| KnowledgeAuthorityErrorV2::TransportUnavailable)?;
    let key = ProviderRuntimeKey {
        tenant_id: operation.scope.tenant_id.clone(),
        provider_id: provider.route.provider_id.clone(),
    };
    let binding = runtime.bindings.get(&key).ok_or(KnowledgeError::Conflict)?;
    if binding.provider_type != provider.provider_type
        || binding.base_url != provider.base_url
        || binding.auth_method != provider.auth_method
        || runtime.credentials.get(&key) != provider.credential.as_ref()
    {
        return Err(KnowledgeError::Conflict.into());
    }
    super::processing_context::with_read_current_checked(
        operation,
        state,
        auth,
        write,
        |connection| {
            let value = read_provider(connection, &operation.scope.tenant_id, &provider.route)?;
            let current = runtime_binding_from_provider(&value).ok_or(KnowledgeError::Conflict)?;
            let digest = provider_credential_binding_digest(
                &current.provider_type,
                &current.base_url,
                &current.auth_method,
            );
            if digest != provider.binding_digest {
                return Err(KnowledgeError::Conflict);
            }
            Ok(())
        },
        action,
    )
}
