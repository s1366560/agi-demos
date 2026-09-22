//! Child-scoped events never enter the parent's act/observe accounting.
use super::*;
use local_plugin_tool_host_v2::{identity::current_child, LocalPluginToolHostV2};

pub(in crate::local_runtime) struct ChildTimelineObserver {
    state: Arc<LocalRuntimeState>,
    conversation_id: String,
    run_id: String,
    revision: u64,
    subagent_id: String,
    native: Option<knowledge_authority_v2::agent_access::PluginNativeIdentityV2>,
    tools: Arc<dyn ToolHost>,
    plugin: Option<Arc<LocalPluginToolHostV2>>,
    mcp: std::collections::BTreeMap<String, tool_authority::ToolMetadata>,
}

impl ChildTimelineObserver {
    pub(in crate::local_runtime) fn new(
        state: Arc<LocalRuntimeState>,
        conversation: &LocalConversation,
        run: &DesktopRun,
        subagent_id: String,
        tools: Arc<dyn ToolHost>,
        plugin: Option<Arc<LocalPluginToolHostV2>>,
        mcp: std::collections::BTreeMap<String, tool_authority::ToolMetadata>,
    ) -> Self {
        let native = knowledge_authority_v2::agent_access::PluginNativeIdentityV2::capture(
            &state,
            conversation,
            Some(run),
        );
        Self {
            state,
            conversation_id: conversation.id.clone(),
            run_id: run.id.clone(),
            revision: run.revision,
            subagent_id,
            native,
            tools,
            plugin,
            mcp,
        }
    }

    fn current(&self, session_id: &str) -> bool {
        let Some(native) = self.native.as_ref() else {
            return false;
        };
        let auth = native.auth();
        if !self
            .state
            .session_store
            .session_context_is_current(auth, chrono::Utc::now().timestamp_millis())
            .unwrap_or(false)
            || !self
                .state
                .session_store
                .list_user_projects(&auth.user.user_id, &auth.workspace.tenant_id)
                .is_ok_and(|projects| {
                    projects
                        .iter()
                        .any(|project| project.id == auth.workspace.project_id)
                })
        {
            return false;
        }
        let Some(child) = current_child() else {
            return false;
        };
        if child.execution_id != session_id
            || child.run_id != self.run_id
            || child.revision != self.revision
            || child.subagent_id != self.subagent_id
            || !native.current(&self.state)
        {
            return false;
        }
        let Ok(Some(run)) = self.state.session_store.run(&self.run_id) else {
            return false;
        };
        run.revision == self.revision
            && self.state.subagent_controls.plugin_execution_current(
                session_id,
                &self.conversation_id,
                &run,
                &self.subagent_id,
                self.state.control_for_run(&run).as_ref(),
            )
    }

    fn redact(&self, tool: &str, payload: &str) -> String {
        let names = self.tools.list_tools();
        if !names.iter().any(|name| name == tool) {
            return "[UNAVAILABLE]".into();
        }
        if let Some(plugin) = self.plugin.as_ref() {
            if let Some(value) = plugin
                .timeline_metadata()
                .restrict_to(&names)
                .redact(tool, payload)
            {
                return value;
            }
        }
        let Some(metadata) = self.mcp.get(tool).filter(|metadata| metadata.name == tool) else {
            return authorized_tool_host::redact_tool_payload(tool, payload);
        };
        let Ok(value) = serde_json::from_str::<Value>(payload) else {
            return "[UNPARSEABLE]".into();
        };
        let mut fields = authorized_tool_host::sensitive_input_fields();
        fields.extend(metadata.sensitive_input_fields.iter().cloned());
        tool_authority::redact_sensitive_fields(&value, &fields).to_string()
    }

    fn publish(
        &self,
        session_id: &str,
        round: u64,
        tool: &str,
        input: &str,
        result: Option<&str>,
        failed: bool,
    ) {
        if !self.current(session_id) {
            return;
        }
        let kind = if failed {
            "subagent_tool_error"
        } else if result.is_some() {
            "subagent_tool_result"
        } else {
            "subagent_tool_call"
        };
        let mut payload = json!({
            "execution_id": session_id, "run_id": session_id,
            "tool_call_id": format!("{session_id}:tool:{round}"),
            "conversation_id": self.conversation_id,
            "parent_run_id": self.run_id, "parent_run_revision": self.revision,
            "subagent_id": self.subagent_id, "round": round,
            "tool_name": tool, "tool_input": self.redact(tool, input), "failed": failed,
        });
        if failed {
            payload["error"] = json!("SubAgent tool execution failed");
        }
        if let Some(result) = result {
            payload["tool_output"] = json!(self.redact(tool, result));
        }
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

#[async_trait]
impl ReActObserver for ChildTimelineObserver {
    async fn on_tool_call(
        &self,
        session: &str,
        round: u64,
        tool: &str,
        input: &str,
    ) -> CoreResult<()> {
        self.publish(session, round, tool, input, None, false);
        Ok(())
    }
    async fn on_tool_result(
        &self,
        session: &str,
        round: u64,
        tool: &str,
        input: &str,
        output: &str,
    ) -> CoreResult<()> {
        self.publish(
            session,
            round,
            tool,
            input,
            Some(output),
            timeline_presentation::tool_result_is_error(output),
        );
        Ok(())
    }
    async fn on_tool_error(
        &self,
        session: &str,
        round: u64,
        tool: &str,
        input: &str,
        _error: &CoreError,
    ) -> CoreResult<()> {
        self.publish(session, round, tool, input, None, true);
        Ok(())
    }
}
