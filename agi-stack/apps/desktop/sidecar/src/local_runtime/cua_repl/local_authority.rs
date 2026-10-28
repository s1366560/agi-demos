use super::super::{
    agent_boundary_v2::AgentBoundaryV2,
    authority_store::{DesktopRun, DesktopRunStatus},
    computer_use_v2::call_identity,
    execution_authority::{ExecutionScope, ScopedExecution},
    LocalConversation, LocalRuntimeState,
};
use agistack_core::{
    agent::tool_policy::ToolPolicyContext,
    ports::{CoreError, CoreResult, ToolHost, ToolResult},
};
use async_trait::async_trait;
use std::sync::{Arc, Weak};

#[derive(Clone)]
pub(super) struct LocalExecution {
    pub state: Weak<LocalRuntimeState>,
    pub owner: Option<super::super::auth_context::AuthenticatedContext>,
    pub scope: ExecutionScope,
    pub run: DesktopRun,
    pub conversation: LocalConversation,
    pub tools: Arc<dyn ToolHost>,
    pub boundary: Option<Arc<AgentBoundaryV2>>,
    pub allowed_servers: Vec<String>,
    pub allowed_tools: Vec<String>,
    pub agent_id: String,
    pub subagent_id: Option<String>,
    pub child: Option<super::super::local_plugin_tool_host_v2::identity::ChildIdentityV2>,
}

impl LocalExecution {
    pub(super) fn bind_child(
        &self,
        child: super::super::local_plugin_tool_host_v2::identity::ChildIdentityV2,
    ) -> CoreResult<Self> {
        let identity = call_identity::active()?;
        if self.subagent_id.as_deref() != Some(child.subagent_id.as_str())
            || child.run_id != self.run.id
            || child.revision != self.run.revision
            || child.execution_id != identity.engine_session_id()
        {
            return Err(CoreError::Tool("repl_child_scope_mismatch".into()));
        }
        let mut execution = self.clone();
        execution.scope.engine_session_id = child.execution_id.clone();
        execution.child = Some(child);
        execution.current()?;
        Ok(execution)
    }

    fn current_profile(
        &self,
        state: &LocalRuntimeState,
        conversation: &LocalConversation,
    ) -> CoreResult<super::super::execution_profile::ExecutionProfile> {
        use super::super::{
            execution_profile::ExecutionProfile, resource_registry::ManagedResourceKind,
        };
        let parent = state
            .execution_profile(conversation)
            .map_err(CoreError::Tool)?;
        let Some(subagent_id) = self.subagent_id.as_deref() else {
            return Ok(parent);
        };
        let selected = state
            .session_store
            .execution_selection(&conversation.id)
            .map_err(CoreError::Storage)?
            .and_then(|value| value.subagent_id);
        if selected
            .as_deref()
            .is_some_and(|selected| selected != subagent_id)
        {
            return Err(CoreError::Tool("repl_child_selection_changed".into()));
        }
        let agent = state
            .session_store
            .managed_resource(
                ManagedResourceKind::Agent,
                "project",
                &conversation.project_id,
                &parent.agent.id,
            )
            .map_err(CoreError::Storage)?
            .ok_or_else(|| CoreError::Tool("repl_agent_missing".into()))?;
        let resource = state
            .session_store
            .managed_resource(
                ManagedResourceKind::SubAgent,
                "tenant",
                &conversation.tenant_id,
                subagent_id,
            )
            .map_err(CoreError::Storage)?
            .ok_or_else(|| CoreError::Tool("repl_subagent_missing".into()))?;
        if !super::super::subagent_scope::is_visible_in_project(&resource, &conversation.project_id)
        {
            return Err(CoreError::Tool("repl_subagent_scope_changed".into()));
        }
        let skill = parent
            .skill
            .as_ref()
            .map(|skill| state.resolve_selected_skill(conversation, &skill.id))
            .transpose()
            .map_err(CoreError::Tool)?;
        ExecutionProfile::resolve(&parent.agent.id, &agent, skill.as_ref(), Some(&resource))
            .map_err(CoreError::Tool)
    }
}

#[async_trait]
impl ScopedExecution for LocalExecution {
    fn scope(&self) -> &ExecutionScope {
        &self.scope
    }
    fn allowed_mcp_servers(&self) -> Vec<String> {
        self.allowed_servers.clone()
    }
    fn current(&self) -> CoreResult<()> {
        let state = self
            .state
            .upgrade()
            .ok_or_else(|| CoreError::Tool("repl_runtime_stopped".into()))?;
        let owner = self
            .owner
            .as_ref()
            .ok_or_else(|| CoreError::Tool("repl_owner_session_required".into()))?;
        if !state
            .session_store
            .session_context_is_current(owner, chrono::Utc::now().timestamp_millis())
            .map_err(CoreError::Storage)?
        {
            return Err(CoreError::Tool("repl_owner_session_revoked".into()));
        }
        let run = state
            .session_store
            .run(&self.run.id)
            .map_err(CoreError::Storage)?
            .ok_or_else(|| CoreError::Tool("repl_run_missing".into()))?;
        if run.status != DesktopRunStatus::Running
            || run.revision != self.run.revision
            || run.permission_profile != self.run.permission_profile
            || run.plan_version_id != self.run.plan_version_id
            || run.conversation_id != self.run.conversation_id
            || run.environment != self.run.environment
            || run.project_id != self.scope.project_id
        {
            return Err(CoreError::Tool("repl_run_authority_changed".into()));
        }
        if self
            .boundary
            .as_ref()
            .is_some_and(|boundary| !boundary.current(&state))
        {
            return Err(CoreError::Tool("repl_plugin_generation_changed".into()));
        }
        let conversation = state
            .session_store
            .conversation(&self.conversation.id)
            .map_err(CoreError::Storage)?
            .ok_or_else(|| CoreError::Tool("repl_conversation_missing".into()))?;
        if conversation.tenant_id != self.scope.tenant_id
            || conversation.project_id != self.scope.project_id
        {
            return Err(CoreError::Tool("repl_owner_changed".into()));
        }
        if let Some(subagent_id) = &self.subagent_id {
            let child = self
                .child
                .as_ref()
                .ok_or_else(|| CoreError::Tool("repl_child_identity_required".into()))?;
            if !state.subagent_controls.plugin_execution_current(
                &child.execution_id,
                &conversation.id,
                &run,
                subagent_id,
                state.control_for_run(&run).as_ref(),
            ) {
                return Err(CoreError::Tool("repl_child_authority_revoked".into()));
            }
        } else if super::super::local_plugin_tool_host_v2::identity::current_child().is_some() {
            return Err(CoreError::Tool(
                "repl_parent_authority_forbidden_in_child".into(),
            ));
        }
        let profile = self.current_profile(&state, &conversation)?;
        if profile.allowed_mcp_servers != self.allowed_servers
            || profile.allowed_tools != self.allowed_tools
            || profile.agent.id != self.agent_id
        {
            return Err(CoreError::Tool("repl_agent_permissions_changed".into()));
        }
        Ok(())
    }
    async fn call(&self, tool: &str, input_json: &str) -> CoreResult<ToolResult> {
        self.current()?;
        if !self.tools.can_dispatch(tool) {
            return Err(CoreError::Tool("repl_tool_not_allowed".into()));
        }
        let identity = call_identity::active()?;
        let context = ToolPolicyContext {
            session_id: identity.engine_session_id(),
            round: identity.round(),
            tool,
        };
        if self
            .child
            .as_ref()
            .is_some_and(|child| child.execution_id != identity.engine_session_id())
        {
            return Err(CoreError::Tool("repl_child_engine_mismatch".into()));
        }
        let dispatch = async {
            if let Some(boundary) = &self.boundary {
                boundary
                    .execute_nested(&context, &*self.tools, input_json)
                    .await
            } else {
                call_identity::scope(&context, self.tools.call_with_content(tool, input_json)).await
            }
        };
        if let Some(child) = self.child.clone() {
            super::super::local_plugin_tool_host_v2::identity::child_scope(child, dispatch).await
        } else {
            dispatch.await
        }
    }
}
