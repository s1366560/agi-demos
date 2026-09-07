//! Provider snapshots come only from verified Workspace Core policy and the
//! existing runtime credential binding. No conversation or workspace is invented.

use super::*;
use crate::local_runtime::{
    llm_from_runtime_binding, routing_targets_for_role, workspace_core_bridge, LlmPort,
    LlmWorkloadRole, LocalRuntimeState, MeteredLlm, ProviderRuntimeKey,
};

pub(super) struct ProcessingProvider {
    pub(super) llm: Arc<dyn LlmPort>,
    pub(super) provider_id: String,
    pub(super) model_id: String,
}

pub(super) async fn resolve(
    operation: &KnowledgeOperationV2,
    state: &LocalRuntimeState,
    authenticated: &AuthenticatedContext,
    workspace_id: &str,
) -> Result<ProcessingProvider, KnowledgeAuthorityErrorV2> {
    super::processing_context::with_current(operation, state, authenticated, |_| Ok(()))?;
    workspace_core_bridge::validate_workspace_access(state, authenticated, workspace_id)
        .await
        .map_err(|_| KnowledgeAuthorityErrorV2::Forbidden)?;
    let policy = workspace_core_bridge::workspace_policy(
        state,
        &operation.scope.tenant_id,
        &operation.scope.project_id,
        workspace_id,
    )
    .await
    .map_err(|_| KnowledgeAuthorityErrorV2::Forbidden)?;
    super::processing_context::with_current(operation, state, authenticated, |_| Ok(()))?;
    let mut targets = routing_targets_for_role(&policy, LlmWorkloadRole::Default)
        .map_err(|_| KnowledgeAuthorityErrorV2::TransportUnavailable)?;
    if targets.is_empty() {
        if let Some(route) = state.selected_provider_route(&operation.scope.tenant_id) {
            targets.push(route);
        }
    }
    // One explicit candidate per durable attempt keeps the actual provider/model
    // identity auditable. A failed attempt is retried explicitly, not hidden in
    // an opaque failover wrapper that could call several providers under one log.
    for target in targets {
        if state
            .validate_conversation_llm_route(&operation.scope.tenant_id, &target)
            .is_err()
        {
            continue;
        }
        let runtime = state
            .provider_runtime
            .lock()
            .map_err(|_| KnowledgeAuthorityErrorV2::TransportUnavailable)?;
        let key = ProviderRuntimeKey {
            tenant_id: operation.scope.tenant_id.clone(),
            provider_id: target.provider_id.clone(),
        };
        let Some(mut binding) = runtime.bindings.get(&key).cloned() else {
            continue;
        };
        binding.model.clone_from(&target.model_id);
        let Some(inner) = llm_from_runtime_binding(binding, runtime.credentials.get(&key).cloned())
        else {
            continue;
        };
        return Ok(ProcessingProvider {
            llm: Arc::new(MeteredLlm {
                inner,
                session_store: state.session_store.clone(),
                provider_id: target.provider_id.clone(),
                tenant_id: operation.scope.tenant_id.clone(),
                model_name: target.model_id.clone(),
            }),
            provider_id: target.provider_id,
            model_id: target.model_id,
        });
    }
    Err(KnowledgeAuthorityErrorV2::TransportUnavailable)
}
