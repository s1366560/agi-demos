use super::*;
#[path = "subagent_child_timeline.rs"]
pub(in crate::local_runtime) mod child_timeline;

impl LocalRuntimeState {
    pub(super) async fn subagent_agent_tool_host(
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
            if let Some(host) = knowledge_authority_v2::agent_access::tool_host(
                self,
                conversation,
                Some(run),
                resource_id,
            ) {
                child_tool_hosts.push(host);
            }
            let mcp_host = mcp_agent_tool_host::McpAgentToolHost::new(
                Arc::clone(&self.mcp_supervisor),
                mcp_supervisor::McpScope {
                    tenant_id: conversation.tenant_id.clone(),
                    project_id: conversation.project_id.clone(),
                },
                run.id.clone(),
                Some(&profile.allowed_mcp_servers),
            )?;
            let mut child_dynamic_metadata = mcp_host.authority_metadata_by_name();
            let child_mcp_metadata = child_dynamic_metadata.clone();
            let mut child_plugin_host = None;
            if let Some(host) = local_plugin_tool_host_v2::LocalPluginToolHostV2::new_child(
                self,
                conversation,
                run,
                resource_id,
            )
            .await?
            {
                child_dynamic_metadata.extend(host.metadata());
                let host = Arc::new(host);
                child_plugin_host = Some(host.clone());
                child_tool_hosts.push(host);
            }
            // Only factory-produced Read metadata can narrow the existing conservative classification.
            let effect = subagent_agent_tool_host::effect_for_execution_profile(
                &profile
                    .allowed_tools
                    .iter()
                    .filter(|name| {
                        !child_dynamic_metadata.get(*name).is_some_and(|metadata| {
                            metadata.name == **name
                                && metadata.effect == tool_authority::ToolEffect::Read
                        })
                    })
                    .cloned()
                    .collect::<Vec<_>>(),
                &profile.allowed_mcp_servers,
            );
            child_tool_hosts.push(Arc::new(mcp_host));
            let child_tool_host: Arc<dyn ToolHost> =
                Arc::new(fan_out_tool_host::FanOutToolHost::new(child_tool_hosts));
            let child_tool_host: Arc<dyn ToolHost> = Arc::new(
                execution_profile::ProfiledToolHost::new(child_tool_host, &profile),
            );
            let child_tool_host: Arc<dyn ToolHost> = if let Some(skills) =
                skill_discovery_tool_host::SkillDiscoveryToolHost::new(
                    self,
                    conversation,
                    Some(run),
                    &profile,
                    child_tool_host.clone(),
                )? {
                for name in ["skill_list", "skill_loader"] {
                    if let Some(metadata) = authorized_tool_host::tool_metadata(name) {
                        child_dynamic_metadata.insert(name.into(), metadata);
                    }
                }
                Arc::new(fan_out_tool_host::FanOutToolHost::new(vec![
                    child_tool_host,
                    Arc::new(skills),
                ]))
            } else {
                child_tool_host
            };
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
            let observer = child_timeline::ChildTimelineObserver::new(
                self.clone(),
                conversation,
                run,
                resource_id.to_owned(),
                child_tool_host.clone(),
                child_plugin_host,
                child_mcp_metadata,
            );
            let engine = ReActEngine::new(
                child_llm,
                child_tool_host,
                self.checkpoints.clone(),
                self.clock.clone(),
            )
            .with_max_rounds(max_rounds);
            targets.push(
                subagent_agent_tool_host::SubagentToolTarget::new(
                    resource,
                    effect,
                    engine,
                    conversation.project_id.clone(),
                    run.id.clone(),
                    run.revision,
                )?
                .with_observer(Arc::new(observer)),
            );
        }
        if targets.is_empty() {
            return Ok(None);
        }
        Ok(Some(
            subagent_agent_tool_host::SubagentAgentToolHost::new(targets)?.with_lifecycle_observer(
                Arc::new(LocalSubagentLifecycleObserver {
                    state: Arc::clone(self),
                    conversation_id: conversation.id.clone(),
                    parent_run_id: run.id.clone(),
                    parent_revision: run.revision,
                    parent_agent_id: parent_profile.agent.id.clone(),
                }),
            ),
        ))
    }
}

struct LocalSubagentLifecycleObserver {
    state: Arc<LocalRuntimeState>,
    conversation_id: String,
    parent_run_id: String,
    parent_revision: u64,
    parent_agent_id: String,
}

impl subagent_agent_tool_host::SubagentLifecycleObserver for LocalSubagentLifecycleObserver {
    fn control_for_execution(
        &self,
        execution_id: &str,
        subagent_id: &str,
        parent_run_id: &str,
        parent_revision: u64,
    ) -> CoreResult<Option<Arc<dyn ReActControl>>> {
        let run = self
            .state
            .session_store
            .run(parent_run_id)
            .map_err(CoreError::Tool)?
            .ok_or(CoreError::NotFound)?;
        if run.conversation_id != self.conversation_id || run.revision != parent_revision {
            return Err(CoreError::Tool(
                "SubAgent parent authority changed".to_string(),
            ));
        }
        let Some(parent) = self.state.control_for_run(&run) else {
            return Ok(None);
        };
        let control = self.state.subagent_controls.register(
            execution_id,
            &self.conversation_id,
            &run,
            subagent_id,
            &self.parent_agent_id,
            parent,
        )?;
        Ok(Some(control))
    }

    fn on_started(
        &self,
        subagent_id: &str,
        subagent_name: &str,
        subagent_display_name: &str,
        task: &subagent_agent_tool_host::LifecyclePayloadMetadata,
    ) {
        if self.state.subagent_controls.is_terminal(&task.execution_id) {
            return;
        }
        for (kind, payload) in [
            (
                "subagent_routed",
                json!({
                    "run_id": task.execution_id,
                    "parent_run_id": self.parent_run_id,
                    "parent_run_revision": self.parent_revision,
                    "control_registered": self.state.subagent_controls.is_registered(&task.execution_id),
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
                    "run_id": task.execution_id,
                    "parent_run_id": self.parent_run_id,
                    "parent_run_revision": self.parent_revision,
                    "control_registered": self.state.subagent_controls.is_registered(&task.execution_id),
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
        if self
            .state
            .subagent_controls
            .is_terminal(&result.execution_id)
        {
            return;
        }
        let cancelled = self.state.subagent_controls.complete(&result.execution_id) && !success;
        let status = if cancelled {
            "cancelled"
        } else if success {
            "completed"
        } else {
            "failed"
        };
        let summary = if cancelled {
            "SubAgent cancelled"
        } else if success {
            "SubAgent completed"
        } else {
            "SubAgent failed"
        };
        for (kind, payload) in [
            (
                "subagent_session_update",
                json!({
                    "run_id": result.execution_id,
                    "subagent_id": subagent_id,
                    "subagent_name": subagent_display_name,
                    "subagent_resource_name": subagent_name,
                    "progress": 1.0,
                    "status_message": status,
                }),
            ),
            (
                if cancelled {
                    "subagent_killed"
                } else {
                    "subagent_completed"
                },
                json!({
                    "run_id": result.execution_id,
                    "subagent_id": subagent_id,
                    "subagent_name": subagent_display_name,
                    "subagent_resource_name": subagent_name,
                    "summary": summary,
                    "result_bytes": result.bytes,
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

#[cfg(test)]
mod telemetry_tests {
    use super::*;
    use crate::local_runtime::subagent_agent_tool_host::SubagentLifecycleObserver;

    #[test]
    fn completed_lifecycle_omits_unmeasured_usage_instead_of_reporting_zero() {
        let state = super::super::tests::test_state("subagent-usage-session");
        let observer = LocalSubagentLifecycleObserver {
            state: Arc::clone(&state),
            conversation_id: "usage-conversation".into(),
            parent_run_id: "parent".into(),
            parent_revision: 1,
            parent_agent_id: "agent".into(),
        };
        observer.on_completed(
            "child",
            "child",
            "Child",
            &subagent_agent_tool_host::LifecyclePayloadMetadata {
                bytes: 12,
                execution_id: "usage-child".into(),
            },
            true,
            123,
        );
        let timeline = state
            .session_store
            .timeline("usage-conversation", 10)
            .unwrap();
        assert_eq!(timeline.len(), 2);
        for event in timeline {
            assert!(event["payload"].get("tokens_used").is_none());
            assert!(event["payload"].get("tool_calls_count").is_none());
        }
    }
}
