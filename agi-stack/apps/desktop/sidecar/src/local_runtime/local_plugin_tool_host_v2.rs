//! A project-scoped native ToolHost backed by the actual signed generation and fresh approvals.
pub(super) mod identity;
mod operation_guard;
mod timeline_metadata;
pub(super) use timeline_metadata::PluginTimelineMetadataV2;
use super::knowledge_authority_v2::agent_access::PluginNativeIdentityV2;
use super::{
    tool_authority::{ToolEffect, ToolMetadata},
    DesktopRun, LocalConversation, LocalRuntimeState,
};
use agistack_core::ports::{CoreError, CoreResult, ToolDefinition, ToolHost};
use agistack_plugin_host::protocol_v2::{
    wasm_runtime::{
        WasmOperationAuthorityV2, WasmOperationV2, WasmToolAttributionV2, WasmToolSetV2,
        WASM_TOOL_SET_SERVICE_V2,
    },
    ScopeKindV2, ScopeV2,
};
use async_trait::async_trait;
use identity::Binding;
pub(super) use operation_guard::OperationReleaseGuardV2;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    sync::Arc,
};

struct Authority {
    state: Arc<LocalRuntimeState>,
    native: PluginNativeIdentityV2,
    binding: Binding,
    conversation_id: String,
    scope: ScopeV2,
}
impl Authority {
    fn current(&self) -> bool {
        if !self
            .state
            .session_store
            .session_context_is_current(self.native.auth(), chrono::Utc::now().timestamp_millis())
            .unwrap_or(false)
        {
            return false;
        }
        if !self
            .state
            .session_store
            .list_user_projects(
                &self.native.auth().user.user_id,
                &self.native.auth().workspace.tenant_id,
            )
            .is_ok_and(|projects| {
                projects
                    .iter()
                    .any(|project| project.id == self.native.auth().workspace.project_id)
            })
        {
            return false;
        }
        self.native.current(&self.state)
            && self.binding.current(&self.state, &self.conversation_id)
            && self
                .state
                .platform_plugin_authority_v2
                .acquire_generation()
                .is_ok_and(|lease| lease.descriptor().publication_version.is_none())
    }
}
#[async_trait]
impl WasmOperationAuthorityV2 for Authority {
    async fn authorize(&self, operation: &WasmOperationV2, tool: &WasmToolAttributionV2) -> bool {
        if self.binding.operation_id().as_deref() != Some(operation.id())
            || operation.scope() != &self.scope
            || !self.current()
        {
            return false;
        }
        let Ok(keys) = self.state.local_plugin_signing_keys.as_ref() else {
            return false;
        };
        let Ok(db) = self.state.session_store.connection() else {
            return false;
        };
        crate::local_plugin_installations_v2::authorizes(&db, keys, &self.scope, tool)
    }
}
struct Tool {
    set: Arc<WasmToolSetV2>,
    definition: ToolDefinition,
    attribution: WasmToolAttributionV2,
}
pub(super) struct LocalPluginToolHostV2 {
    authority: Arc<Authority>,
    tools: BTreeMap<String, Tool>,
}
impl LocalPluginToolHostV2 {
    pub(super) async fn new(
        state: &Arc<LocalRuntimeState>,
        conversation: &LocalConversation,
        run: &DesktopRun,
    ) -> Result<Option<Self>, String> {
        Self::create(state, conversation, Some(run), Binding::build(run)).await
    }
    pub(super) async fn new_plan(
        state: &Arc<LocalRuntimeState>,
        conversation: &LocalConversation,
    ) -> Result<Option<Self>, String> {
        let Some(native) = PluginNativeIdentityV2::capture(state, conversation, None) else {
            return Ok(None);
        };
        let control = state
            .agent_runs
            .lock()
            .map_err(|_| "Plan control unavailable")?
            .get(&conversation.id)
            .filter(|active| active.run_id.is_none())
            .map(|active| active.control.clone());
        let Some(control) = control else {
            return Ok(None);
        };
        Self::create(
            state,
            conversation,
            None,
            Binding::Plan {
                message_id: native.message_id().to_owned(),
                control,
            },
        )
        .await
    }
    pub(super) async fn new_child(
        state: &Arc<LocalRuntimeState>,
        conversation: &LocalConversation,
        run: &DesktopRun,
        subagent_id: &str,
    ) -> Result<Option<Self>, String> {
        // Discover verified definitions under the real parent operation before exposing any child tool.
        let Some(mut host) = Self::new(state, conversation, run).await? else {
            return Ok(None);
        };
        host.authority = Arc::new(Authority {
            state: state.clone(),
            native: host.authority.native.clone(),
            binding: Binding::Child {
                run_id: run.id.clone(),
                revision: run.revision,
                subagent_id: subagent_id.to_owned(),
            },
            conversation_id: conversation.id.clone(),
            scope: host.authority.scope.clone(),
        });
        Ok(Some(host))
    }
    async fn create(
        state: &Arc<LocalRuntimeState>,
        conversation: &LocalConversation,
        run: Option<&DesktopRun>,
        binding: Binding,
    ) -> Result<Option<Self>, String> {
        let Some(native) = PluginNativeIdentityV2::capture(state, conversation, run) else {
            return Ok(None);
        };
        let scope = ScopeV2 {
            kind: ScopeKindV2::Project,
            tenant_id: Some(conversation.tenant_id.clone()),
            project_id: Some(conversation.project_id.clone()),
            session_id: None,
        };
        let authority = Arc::new(Authority {
            state: state.clone(),
            native,
            binding,
            conversation_id: conversation.id.clone(),
            scope: scope.clone(),
        });
        if !authority.current() {
            return Ok(None);
        }
        let manager = state.platform_plugin_authority_v2.manager();
        let lease = manager.acquire().map_err(|error| error.to_string())?;
        let generation = lease.generation().map_err(|error| error.to_string())?;
        let sets: Vec<_> = generation
            .snapshot
            .entries
            .iter()
            .filter(|entry| {
                entry.enabled
                    && entry.scope == scope
                    && entry.isolate.get(WASM_TOOL_SET_SERVICE_V2) == Some(&entry.entry_id)
            })
            .map(|entry| {
                generation.resolve::<WasmToolSetV2>(
                    WASM_TOOL_SET_SERVICE_V2,
                    &scope,
                    Some(&entry.entry_id),
                )
            })
            .collect();
        let operation = OperationReleaseGuardV2::new(WasmOperationV2::new(
            lease,
            scope,
            authority
                .binding
                .operation_id()
                .ok_or("Plugin operation identity unavailable")?,
            Some(authority.clone()),
        ));
        let mut tools = BTreeMap::new();
        for set in sets {
            let set = match set {
                Ok(value) => value,
                Err(error) => {
                    operation.close().await.map_err(|error| error.to_string())?;
                    return Err(error.to_string());
                }
            };
            for tool in set.prepare(&operation).await {
                let attribution = tool.attribution().clone();
                let mut definition = tool.definition();
                definition.description = Some(format!(
                    "Signed local package {} tool {}. {}",
                    attribution.bundle.bundle_id,
                    attribution.tool_name,
                    definition.description.as_deref().unwrap_or_default()
                ));
                definition.name = format!(
                    "plugin__{}",
                    &format!("{:x}", Sha256::digest(attribution.entry_id.as_bytes()))[..40]
                );
                tools.insert(
                    definition.name.clone(),
                    Tool {
                        set: set.clone(),
                        definition,
                        attribution,
                    },
                );
            }
        }
        operation.close().await.map_err(|error| error.to_string())?;
        Ok(Some(Self { authority, tools }))
    }
    pub(super) fn timeline_metadata(self: &Arc<Self>) -> PluginTimelineMetadataV2 {
        PluginTimelineMetadataV2::capture(self.clone())
    }
    pub(super) fn metadata(&self) -> BTreeMap<String, ToolMetadata> {
        self.tools
            .keys()
            .map(|name| {
                (
                    name.clone(),
                    ToolMetadata {
                        name: name.clone(),
                        effect: ToolEffect::Read,
                        sensitive_input_fields: BTreeSet::new(),
                    },
                )
            })
            .collect()
    }
}
#[async_trait]
impl ToolHost for LocalPluginToolHostV2 {
    fn list_tools(&self) -> Vec<String> {
        if !self.authority.current() {
            return vec![];
        }
        let Ok(keys) = self.authority.state.local_plugin_signing_keys.as_ref() else {
            return vec![];
        };
        let Ok(db) = self.authority.state.session_store.connection() else {
            return vec![];
        };
        self.tools
            .iter()
            .filter(|(_, tool)| {
                crate::local_plugin_installations_v2::authorizes(
                    &db,
                    keys,
                    &self.authority.scope,
                    &tool.attribution,
                )
            })
            .map(|(name, _)| name.clone())
            .collect()
    }
    fn tool_definition(&self, name: &str) -> Option<ToolDefinition> {
        if !self.list_tools().iter().any(|available| available == name) {
            return None;
        }
        self.tools.get(name).map(|tool| tool.definition.clone())
    }
    async fn call(&self, name: &str, args_json: &str) -> CoreResult<String> {
        if !self.authority.binding.invocation_current() {
            return Err(CoreError::Tool(
                "Local plugin call requires an authorized tool invocation".into(),
            ));
        }
        let tool = self
            .tools
            .get(name)
            .ok_or_else(|| CoreError::Tool("Unknown local plugin tool".into()))?;
        if !self.authority.current() {
            return Err(CoreError::Tool(
                "Local plugin operation authority is no longer current".into(),
            ));
        }
        let args: Value =
            serde_json::from_str(args_json).map_err(|error| CoreError::Tool(error.to_string()))?;
        let lease = self
            .authority
            .state
            .platform_plugin_authority_v2
            .manager()
            .acquire()
            .map_err(|error| CoreError::Tool(error.to_string()))?;
        let operation = OperationReleaseGuardV2::new(WasmOperationV2::new(
            lease,
            self.authority.scope.clone(),
            self.authority
                .binding
                .operation_id()
                .ok_or_else(|| CoreError::Tool("Plugin operation identity unavailable".into()))?,
            Some(self.authority.clone()),
        ));
        let prepared = tool.set.prepare(&operation).await;
        let result = match prepared
            .iter()
            .find(|item| item.attribution() == &tool.attribution)
        {
            Some(authorized) => authorized
                .invoke(args)
                .await
                .map_err(|error| CoreError::Tool(error.to_string())),
            None => Err(CoreError::Tool(
                "Local plugin installation, scope or generation is no longer authorized".into(),
            )),
        };
        operation
            .close()
            .await
            .map_err(|error| CoreError::Tool(error.to_string()))?;
        let value = result?;
        if !self.authority.current() {
            return Err(CoreError::Tool(
                "Local plugin operation authority changed".into(),
            ));
        }
        serde_json::to_string(&value).map_err(|error| CoreError::Tool(error.to_string()))
    }
}
