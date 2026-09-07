//! Generation-owned local knowledge authority. Production publication remains
//! closed until knowledge and synchronization jointly satisfy the release gate.

use std::{
    collections::BTreeMap,
    path::PathBuf,
    sync::{Arc, Mutex},
};

use agistack_adapters_device::knowledge::SqliteKnowledgeRepository;
use agistack_core::knowledge::{
    KnowledgeError, KnowledgeScope, MemoryChange, MemoryMutation, MemoryMutationOutcome,
    ScopedMemoryRepository,
};
use agistack_core::Memory;
use agistack_plugin_host::protocol_v2::{plugin_contract_digest_v2, PluginContractV2};
use agistack_plugin_host::{
    ContextV2, PluginDefinitionV2, PluginModuleRuntimeV2, RuntimeV2Error, ScopeKindV2, ScopeV2,
};
use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use super::{
    auth_context::AuthenticatedContext,
    platform_plugin_authority_v2::ActivePlatformPluginGenerationLeaseV2,
};

mod routes;
mod storage_lifecycle;
mod sync;
mod sync_transport;
#[cfg(test)]
mod tests;

pub(super) const MODULE_REF: &str = "builtin://memstack/desktop-sidecar/knowledge-authority";
pub(super) const SERVICE: &str = "service:desktop-sidecar.knowledge-authority";
pub(super) const VERSION: &str = "1.0.0";
const RELEASE_CONTRACT: &str = "knowledge-and-sync-v1";

pub(super) fn router() -> axum::Router<Arc<super::LocalRuntimeState>> {
    routes::router()
}

pub(super) fn contract() -> Result<PluginContractV2, RuntimeV2Error> {
    serde_json::from_value(json!({
        "services": {"provides": [{"service": SERVICE, "version": VERSION}], "requires": []},
        "events": {"emits": [], "handles": []},
        "config_schema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object", "additionalProperties": false,
            "properties": {
                "release_contract": {"type": "string", "const": RELEASE_CONTRACT},
                "release_state": {"type": "string", "const": "closed"}
            },
            "required": ["release_contract", "release_state"]
        }
    }))
    .map_err(|error| RuntimeV2Error::Module(error.to_string()))
}

pub(super) fn definition(
    app_data_dir: Option<PathBuf>,
) -> Result<PluginDefinitionV2, RuntimeV2Error> {
    Ok(PluginDefinitionV2 {
        module_ref: MODULE_REF.into(),
        contract_digest: plugin_contract_digest_v2(&contract()?)
            .map_err(|error| RuntimeV2Error::Module(error.to_string()))?,
        module: Arc::new(KnowledgeModuleV2 {
            app_data_dir,
            #[cfg(test)]
            internal_validation: false,
        }),
    })
}

struct KnowledgeModuleV2 {
    app_data_dir: Option<PathBuf>,
    #[cfg(test)]
    internal_validation: bool,
}

#[async_trait]
impl PluginModuleRuntimeV2 for KnowledgeModuleV2 {
    async fn apply(
        &self,
        context: &mut ContextV2,
        config: &BTreeMap<String, Value>,
    ) -> Result<(), RuntimeV2Error> {
        if config.len() != 2
            || config.get("release_contract") != Some(&json!(RELEASE_CONTRACT))
            || config.get("release_state") != Some(&json!("closed"))
        {
            return Err(RuntimeV2Error::Module(
                "knowledge release contract must remain closed".into(),
            ));
        }
        #[cfg(test)]
        let validation = self.internal_validation;
        #[cfg(not(test))]
        let validation = false;
        let inner = Arc::new(Mutex::new(KnowledgeState {
            app_data_dir: self.app_data_dir.clone(),
            repository: None,
            disposed: false,
            admitted_for_validation: validation,
        }));
        let service = KnowledgeAuthorityV2 {
            inner: Arc::clone(&inner),
        };
        context.effect(
            "knowledge-storage-lifetime",
            Box::new(move || {
                Box::pin(async move {
                    let mut state = inner.lock().map_err(|_| {
                        RuntimeV2Error::Module("knowledge lifecycle lock is poisoned".into())
                    })?;
                    state.disposed = true;
                    state.repository.take();
                    Ok(())
                })
            }),
        )?;
        context.provide_versioned(SERVICE, VERSION, service)
    }
}

struct KnowledgeState {
    app_data_dir: Option<PathBuf>,
    repository: Option<Arc<SqliteKnowledgeRepository>>,
    disposed: bool,
    admitted_for_validation: bool,
}

pub(super) struct KnowledgeAuthorityV2 {
    inner: Arc<Mutex<KnowledgeState>>,
}

impl KnowledgeAuthorityV2 {
    fn repository(&self) -> Result<Arc<SqliteKnowledgeRepository>, KnowledgeAuthorityErrorV2> {
        let mut state = self.inner.lock().map_err(|_| {
            KnowledgeAuthorityErrorV2::Storage("knowledge lifecycle lock is poisoned".into())
        })?;
        if state.disposed {
            return Err(KnowledgeAuthorityErrorV2::Disposed);
        }
        if !state.admitted_for_validation {
            return Err(KnowledgeAuthorityErrorV2::ReleaseClosed);
        }
        if let Some(repository) = &state.repository {
            return Ok(Arc::clone(repository));
        }
        let app_data_dir = state.app_data_dir.as_ref().ok_or_else(|| {
            KnowledgeAuthorityErrorV2::Storage("knowledge data directory is unavailable".into())
        })?;
        let repository =
            storage_lifecycle::open(app_data_dir).map_err(KnowledgeAuthorityErrorV2::Storage)?;
        state.repository = Some(Arc::clone(&repository));
        Ok(repository)
    }
}

#[derive(Debug, thiserror::Error)]
pub(super) enum KnowledgeAuthorityErrorV2 {
    #[error("trusted cloud synchronization transport is unavailable")]
    TransportUnavailable,
    #[error("cloud synchronization request failed")]
    RemoteRejected,
    #[error("knowledge and synchronization release is closed")]
    ReleaseClosed,
    #[error("knowledge authority is disposed")]
    Disposed,
    #[error("knowledge request does not match the authenticated workspace")]
    ScopeMismatch,
    #[error("knowledge request does not match the admitted generation")]
    GenerationMismatch,
    #[error("knowledge mutation permission required")]
    Forbidden,
    #[error("knowledge service is unavailable: {0}")]
    Service(#[from] RuntimeV2Error),
    #[error("knowledge storage failed: {0}")]
    Storage(String),
    #[error(transparent)]
    Knowledge(#[from] KnowledgeError),
}

/// The wire-facing operation scope must match both the authenticated local
/// context and the generation lease acquired by route admission.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct KnowledgeOperationScopeV2 {
    pub(super) tenant_id: String,
    pub(super) project_id: String,
    pub(super) context_revision: u64,
    pub(super) profile_id: String,
    pub(super) generation: u64,
    pub(super) digest: String,
}

pub(super) struct KnowledgeOperationV2 {
    authority: Arc<KnowledgeAuthorityV2>,
    scope: KnowledgeScope,
    actor_id: String,
    writable: bool,
    _lease: Arc<ActivePlatformPluginGenerationLeaseV2>,
}

impl KnowledgeOperationV2 {
    pub(super) fn admit(
        lease: Arc<ActivePlatformPluginGenerationLeaseV2>,
        authenticated: &AuthenticatedContext,
        requested: &KnowledgeOperationScopeV2,
    ) -> Result<Self, KnowledgeAuthorityErrorV2> {
        if !authenticated.user.is_active
            || requested.tenant_id != authenticated.workspace.tenant_id
            || requested.project_id != authenticated.workspace.project_id
            || requested.context_revision != authenticated.workspace.revision
        {
            return Err(KnowledgeAuthorityErrorV2::ScopeMismatch);
        }
        let descriptor = lease.descriptor();
        if requested.profile_id != descriptor.profile_id
            || requested.generation != descriptor.generation
            || requested.digest != descriptor.digest
        {
            return Err(KnowledgeAuthorityErrorV2::GenerationMismatch);
        }
        let scope = KnowledgeScope {
            tenant_id: requested.tenant_id.clone(),
            project_id: requested.project_id.clone(),
        };
        let authority = lease.knowledge_authority(&ScopeV2 {
            kind: ScopeKindV2::Project,
            tenant_id: Some(scope.tenant_id.clone()),
            project_id: Some(scope.project_id.clone()),
            session_id: None,
        })?;
        // Closed releases never reach filesystem or durable storage.
        authority.repository()?;
        Ok(Self {
            authority,
            scope,
            actor_id: authenticated.user.user_id.clone(),
            writable: matches!(
                authenticated.membership_role.as_str(),
                "owner" | "admin" | "member" | "contributor"
            ),
            _lease: lease,
        })
    }

    pub(super) async fn get(&self, id: &str) -> Result<Option<Memory>, KnowledgeAuthorityErrorV2> {
        Ok(self.authority.repository()?.get(&self.scope, id).await?)
    }

    pub(super) async fn list(
        &self,
        limit: usize,
        offset: usize,
    ) -> Result<Vec<Memory>, KnowledgeAuthorityErrorV2> {
        Ok(self
            .authority
            .repository()?
            .list(&self.scope, limit, offset)
            .await?)
    }

    pub(super) async fn mutate(
        &self,
        idempotency_key: &str,
        mutation: MemoryMutation,
    ) -> Result<MemoryMutationOutcome, KnowledgeAuthorityErrorV2> {
        if !self.writable {
            return Err(KnowledgeAuthorityErrorV2::Forbidden);
        }
        if matches!(&mutation, MemoryMutation::Create { memory } if memory.author_id != self.actor_id)
        {
            return Err(KnowledgeAuthorityErrorV2::Forbidden);
        }
        Ok(self
            .authority
            .repository()?
            .mutate(&self.scope, &self.actor_id, idempotency_key, mutation)
            .await?)
    }

    pub(super) async fn changes(
        &self,
        after_sequence: u64,
        limit: usize,
    ) -> Result<Vec<MemoryChange>, KnowledgeAuthorityErrorV2> {
        Ok(self
            .authority
            .repository()?
            .changes(&self.scope, after_sequence, limit)
            .await?)
    }

    pub(super) async fn change(
        &self,
        sequence: u64,
    ) -> Result<Option<MemoryChange>, KnowledgeAuthorityErrorV2> {
        Ok(self
            .authority
            .repository()?
            .change(&self.scope, sequence)
            .await?)
    }
}
