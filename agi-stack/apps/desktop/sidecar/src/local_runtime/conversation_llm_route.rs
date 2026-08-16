use super::*;

impl LocalRuntimeState {
    pub(super) fn validate_conversation_llm_route(
        &self,
        tenant_id: &str,
        route: &LlmRouteTarget,
    ) -> Result<(), String> {
        ensure_stored_route_target(route)?;
        let provider = self
            .session_store
            .managed_resource(
                ManagedResourceKind::Provider,
                "tenant",
                tenant_id,
                &route.provider_id,
            )?
            .ok_or_else(|| "selected LLM provider is unavailable".to_string())?;
        if !provider_supports_route_model(&provider, &route.model_id) {
            return Err("selected LLM model is unavailable for this provider".to_string());
        }
        let key = ProviderRuntimeKey {
            tenant_id: tenant_id.to_string(),
            provider_id: route.provider_id.clone(),
        };
        let runtime = self
            .provider_runtime
            .lock()
            .map_err(|_| "provider runtime state is unavailable".to_string())?;
        let binding = runtime
            .bindings
            .get(&key)
            .ok_or_else(|| "selected LLM provider is not active".to_string())?;
        if binding.auth_method != "none" && !runtime.credentials.contains_key(&key) {
            return Err("selected LLM provider credentials are unavailable".to_string());
        }
        Ok(())
    }

    pub(super) fn selected_provider_route(&self, tenant_id: &str) -> Option<LlmRouteTarget> {
        let runtime = self.provider_runtime.lock().ok()?;
        let active: Vec<(&ProviderRuntimeKey, &ProviderRuntimeBinding)> = runtime
            .bindings
            .iter()
            .filter(|(key, _)| key.tenant_id == tenant_id)
            .collect();
        let selected_id = runtime.selections.get(tenant_id);
        let (key, binding) = match selected_id {
            Some(provider_id) => active
                .iter()
                .find(|(key, _)| &key.provider_id == provider_id)
                .map(|(key, binding)| (*key, *binding))?,
            None => {
                // No explicit runtime selection: local mode configures at most one
                // active provider per tenant, so the sole binding is the default.
                let (key, binding) = active.iter().next().copied()?;
                if active.len() > 1 {
                    return None;
                }
                (key, binding)
            }
        };
        if binding.auth_method != "none" && !runtime.credentials.contains_key(&key) {
            return None;
        }
        Some(LlmRouteTarget {
            provider_id: key.provider_id.clone(),
            model_id: binding.model.clone(),
        })
    }

    pub(super) fn llm_for_unbound_conversation(
        &self,
        conversation: &LocalConversation,
    ) -> Arc<dyn LlmPort> {
        let route = match self.session_store.conversation_llm_route(&conversation.id) {
            Ok(Some(route)) => route,
            Ok(None) => {
                // Unbound conversations have no workspace policy; fall back to the
                // tenant-selected provider binding so "project default model" works.
                match self.selected_provider_route(&conversation.tenant_id) {
                    Some(route) => route,
                    None => return Arc::new(UnconfiguredLocalLlm),
                }
            }
            Err(_) => return Arc::new(UnconfiguredLocalLlm),
        };
        if self
            .validate_conversation_llm_route(&conversation.tenant_id, &route)
            .is_err()
        {
            return Arc::new(UnconfiguredLocalLlm);
        }
        let key = ProviderRuntimeKey {
            tenant_id: conversation.tenant_id.clone(),
            provider_id: route.provider_id.clone(),
        };
        let runtime = match self.provider_runtime.lock() {
            Ok(runtime) => runtime,
            Err(_) => return Arc::new(UnconfiguredLocalLlm),
        };
        let Some(mut binding) = runtime.bindings.get(&key).cloned() else {
            return Arc::new(UnconfiguredLocalLlm);
        };
        binding.model.clone_from(&route.model_id);
        let Some(inner) = llm_from_runtime_binding(binding, runtime.credentials.get(&key).cloned())
        else {
            return Arc::new(UnconfiguredLocalLlm);
        };
        Arc::new(MeteredLlm {
            inner,
            session_store: self.session_store.clone(),
            provider_id: route.provider_id,
            tenant_id: conversation.tenant_id.clone(),
            model_name: route.model_id,
        })
    }
}

pub(super) fn normalized_conversation_llm_route(
    model_override: Option<String>,
    route_override: Option<LlmRouteTarget>,
) -> Result<Option<LlmRouteTarget>, String> {
    let model_override = model_override
        .map(|model| model.trim().to_string())
        .filter(|model| !model.is_empty());
    let Some(mut route) = route_override else {
        return if model_override.is_some() {
            Err("a provider-specific LLM route is required for a model override".to_string())
        } else {
            Ok(None)
        };
    };
    route.provider_id = route.provider_id.trim().to_string();
    route.model_id = route.model_id.trim().to_string();
    ensure_stored_route_target(&route)?;
    if model_override
        .as_deref()
        .is_some_and(|model| model != route.model_id)
    {
        return Err("LLM model override does not match its provider route".to_string());
    }
    Ok(Some(route))
}

pub(super) fn workload_role_for_capability(
    capability: ConversationCapabilityMode,
) -> LlmWorkloadRole {
    match capability {
        ConversationCapabilityMode::Code => LlmWorkloadRole::Coding,
        ConversationCapabilityMode::Work | ConversationCapabilityMode::Unavailable => {
            LlmWorkloadRole::Default
        }
    }
}
