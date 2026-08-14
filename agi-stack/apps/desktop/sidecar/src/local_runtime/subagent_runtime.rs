use super::*;

impl LocalRuntimeState {
    pub(super) fn subagent_agent_tool_host(
        self: &Arc<Self>,
        conversation: &LocalConversation,
        run: &DesktopRun,
        parent_profile: &execution_profile::ExecutionProfile,
        base_tool_hosts: &[Arc<dyn ToolHost>],
        base_llm: Arc<dyn LlmPort>,
        max_rounds: u64,
    ) -> Result<Option<subagent_agent_tool_host::SubagentAgentToolHost>, String> {
        let agent = self
            .session_store
            .managed_resource(
                ManagedResourceKind::Agent,
                "project",
                &conversation.project_id,
                &parent_profile.agent.id,
            )?
            .ok_or_else(|| format!("selected Agent was not found: {}", parent_profile.agent.id))?;
        let resources = self.session_store.list_managed_resources(
            ManagedResourceKind::SubAgent,
            "tenant",
            &conversation.tenant_id,
        )?;
        let resources = subagent_agent_tool_host::authorized_subagent_resources(
            &agent,
            &resources,
            &conversation.project_id,
        )?;
        let attached_subagent_id = self
            .session_store
            .execution_selection(&conversation.id)?
            .and_then(|selection| selection.subagent_id);
        let resources = if let Some(attached_subagent_id) = attached_subagent_id.as_deref() {
            let attached = resources
                .into_iter()
                .filter(|resource| {
                    resource.get("id").and_then(Value::as_str) == Some(attached_subagent_id)
                })
                .collect::<Vec<_>>();
            if attached.len() != 1 {
                return Err(format!(
                    "attached SubAgent is not uniquely authorized for delegation: {attached_subagent_id}"
                ));
            }
            attached
        } else {
            resources
        };
        if resources.is_empty() {
            return Ok(None);
        }
        let selected_skill = parent_profile
            .skill
            .as_ref()
            .map(|skill| self.resolve_selected_skill(conversation, &skill.id))
            .transpose()?;
        let mut targets = Vec::new();
        for resource in resources {
            let resource_id = resource
                .get("id")
                .and_then(Value::as_str)
                .unwrap_or("<unknown>");
            let profile = execution_profile::ExecutionProfile::resolve(
                &parent_profile.agent.id,
                &agent,
                selected_skill.as_ref(),
                Some(&resource),
            )
            .map_err(|error| {
                format!("SubAgent execution profile is invalid for {resource_id}: {error}")
            })?;
            let mut child_tool_hosts = base_tool_hosts.to_vec();
            let mcp_host = mcp_agent_tool_host::McpAgentToolHost::new(
                Arc::clone(&self.mcp_supervisor),
                mcp_supervisor::McpScope {
                    tenant_id: conversation.tenant_id.clone(),
                    project_id: conversation.project_id.clone(),
                },
                run.id.clone(),
                Some(&profile.allowed_mcp_servers),
            )?;
            let child_dynamic_metadata = mcp_host.authority_metadata_by_name();
            child_tool_hosts.push(Arc::new(mcp_host));
            let child_tool_host: Arc<dyn ToolHost> =
                Arc::new(fan_out_tool_host::FanOutToolHost::new(child_tool_hosts));
            let child_tool_host: Arc<dyn ToolHost> = Arc::new(
                execution_profile::ProfiledToolHost::new(child_tool_host, &profile),
            );
            let child_tool_host: Arc<dyn ToolHost> =
                Arc::new(AuthorizedRunToolHost::with_dynamic_metadata(
                    child_tool_host,
                    self.session_store.clone(),
                    run.clone(),
                    child_dynamic_metadata,
                ));
            let child_llm: Arc<dyn LlmPort> = Arc::new(execution_profile::ProfiledLlm::new(
                Arc::clone(&base_llm),
                &profile,
            ));
            let engine = ReActEngine::new(
                child_llm,
                child_tool_host,
                self.checkpoints.clone(),
                self.clock.clone(),
            )
            .with_max_rounds(max_rounds);
            let effect = subagent_agent_tool_host::effect_for_execution_profile(
                &profile.allowed_tools,
                &profile.allowed_mcp_servers,
            );
            targets.push(subagent_agent_tool_host::SubagentToolTarget::new(
                resource,
                effect,
                engine,
                conversation.project_id.clone(),
                run.id.clone(),
                run.revision,
            )?);
        }
        if targets.is_empty() {
            return Ok(None);
        }
        Ok(Some(
            subagent_agent_tool_host::SubagentAgentToolHost::new(targets)?.with_lifecycle_observer(
                Arc::new(LocalSubagentLifecycleObserver {
                    state: Arc::clone(self),
                    conversation_id: conversation.id.clone(),
                }),
            ),
        ))
    }
}

struct LocalSubagentLifecycleObserver {
    state: Arc<LocalRuntimeState>,
    conversation_id: String,
}

impl subagent_agent_tool_host::SubagentLifecycleObserver for LocalSubagentLifecycleObserver {
    fn on_started(
        &self,
        subagent_id: &str,
        subagent_name: &str,
        subagent_display_name: &str,
        task: &subagent_agent_tool_host::LifecyclePayloadMetadata,
    ) {
        for (kind, payload) in [
            (
                "subagent_routed",
                json!({
                    "subagent_id": subagent_id,
                    "subagent_name": subagent_display_name,
                    "subagent_resource_name": subagent_name,
                    "confidence": 1.0,
                    "reason": "structured_tool_delegation",
                }),
            ),
            (
                "subagent_started",
                json!({
                    "subagent_id": subagent_id,
                    "subagent_name": subagent_display_name,
                    "subagent_resource_name": subagent_name,
                    "task": "Delegated SubAgent task",
                    "task_bytes": task.bytes,
                }),
            ),
        ] {
            let item = self.state.timeline_item(
                kind,
                self.conversation_id.clone(),
                None,
                None,
                None,
                payload,
            );
            self.state.append_timeline(&self.conversation_id, item);
        }
    }

    fn on_completed(
        &self,
        subagent_id: &str,
        subagent_name: &str,
        subagent_display_name: &str,
        result: &subagent_agent_tool_host::LifecyclePayloadMetadata,
        success: bool,
        execution_time_ms: u64,
    ) {
        let status = if success { "completed" } else { "failed" };
        let summary = if success {
            "SubAgent completed"
        } else {
            "SubAgent failed"
        };
        for (kind, payload) in [
            (
                "subagent_session_update",
                json!({
                    "subagent_id": subagent_id,
                    "subagent_name": subagent_display_name,
                    "subagent_resource_name": subagent_name,
                    "progress": 1.0,
                    "status_message": status,
                    "tokens_used": 0,
                    "tool_calls_count": 0,
                }),
            ),
            (
                "subagent_completed",
                json!({
                    "subagent_id": subagent_id,
                    "subagent_name": subagent_display_name,
                    "subagent_resource_name": subagent_name,
                    "summary": summary,
                    "result_bytes": result.bytes,
                    "tokens_used": 0,
                    "execution_time_ms": execution_time_ms,
                    "success": success,
                }),
            ),
        ] {
            let item = self.state.timeline_item(
                kind,
                self.conversation_id.clone(),
                None,
                None,
                None,
                payload,
            );
            self.state.append_timeline(&self.conversation_id, item);
        }
    }
}
