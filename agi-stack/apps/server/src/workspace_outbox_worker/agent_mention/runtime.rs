use std::sync::Arc;

use agistack_core::agent::types::AgentAction;
use agistack_core::ports::{CoreError, CoreResult, LlmPort};
use async_trait::async_trait;
use uuid::Uuid;

use super::super::bool_env;

const WORKSPACE_MENTION_RUNTIME_ENABLED_ENV: &str = "AGISTACK_WORKSPACE_MENTION_RUNTIME_ENABLED";

pub(crate) struct WorkspaceAgentMentionRuntimeInput {
    pub(crate) workspace_id: String,
    pub(crate) conversation_id: String,
    pub(crate) target_agent_id: String,
    pub(crate) agent_name: String,
    pub(crate) sender_name: Option<String>,
    pub(crate) user_prompt: String,
}

#[async_trait]
pub(crate) trait WorkspaceAgentMentionRuntime: Send + Sync {
    async fn complete(&self, input: WorkspaceAgentMentionRuntimeInput) -> CoreResult<String>;
}

pub(crate) fn workspace_agent_mention_runtime_from_env(
    llm: Arc<dyn LlmPort>,
) -> Option<Arc<dyn WorkspaceAgentMentionRuntime>> {
    if bool_env(WORKSPACE_MENTION_RUNTIME_ENABLED_ENV, false) {
        Some(Arc::new(LlmWorkspaceAgentMentionRuntime { llm }))
    } else {
        None
    }
}

struct LlmWorkspaceAgentMentionRuntime {
    llm: Arc<dyn LlmPort>,
}

#[async_trait]
impl WorkspaceAgentMentionRuntime for LlmWorkspaceAgentMentionRuntime {
    async fn complete(&self, input: WorkspaceAgentMentionRuntimeInput) -> CoreResult<String> {
        let goal = render_workspace_agent_mention_goal(&input);
        match self.llm.decide(&goal, 0, &[], &[]).await? {
            AgentAction::Finish { answer } => {
                let answer = answer.trim();
                if answer.is_empty() {
                    Err(CoreError::Llm(
                        "workspace mention runtime returned an empty answer".to_string(),
                    ))
                } else {
                    Ok(answer.to_string())
                }
            }
            AgentAction::CallTool { tool, .. } => Err(CoreError::Llm(format!(
                "workspace mention runtime requested unsupported tool call: {tool}"
            ))),
            AgentAction::RequestHuman { request } => Err(CoreError::Llm(format!(
                "workspace mention runtime requested HITL ({:?}): {}",
                request.kind, request.prompt
            ))),
        }
    }
}

fn render_workspace_agent_mention_goal(input: &WorkspaceAgentMentionRuntimeInput) -> String {
    let sender = input
        .sender_name
        .as_deref()
        .filter(|value| !value.trim().is_empty())
        .unwrap_or("workspace user");
    format!(
        "You are {agent_name} ({agent_id}) replying inside workspace {workspace_id}. \
Respond directly to {sender}'s message in the same language. \
Return a concise final answer for the workspace chat only; do not request tools or human input.\n\n\
Conversation: {conversation_id}\nUser message:\n{user_prompt}",
        agent_name = input.agent_name,
        agent_id = input.target_agent_id,
        workspace_id = input.workspace_id,
        sender = sender,
        conversation_id = input.conversation_id,
        user_prompt = input.user_prompt
    )
}

pub(crate) fn workspace_agent_conversation_id(
    workspace_id: &str,
    agent_id: &str,
    conversation_scope: Option<&str>,
) -> String {
    let scope_suffix = conversation_scope
        .map(|scope| format!(":scope:{scope}"))
        .unwrap_or_default();
    Uuid::new_v5(
        &Uuid::NAMESPACE_DNS,
        format!("workspace:{workspace_id}:agent:{agent_id}{scope_suffix}").as_bytes(),
    )
    .to_string()
}
