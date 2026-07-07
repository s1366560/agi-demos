use std::sync::Arc;

use agistack_core::agent::types::AgentAction;
use agistack_core::ports::{CoreError, CoreResult, LlmPort};
use async_trait::async_trait;
use uuid::Uuid;

use super::super::bool_env;

const WORKSPACE_MENTION_RUNTIME_ENABLED_ENV: &str = "AGISTACK_WORKSPACE_MENTION_RUNTIME_ENABLED";
const WORKSPACE_MENTION_RUNTIME_PRODUCTION_READY_ENV: &str =
    "AGISTACK_WORKSPACE_MENTION_RUNTIME_PRODUCTION_READY";
const WORKSPACE_AGENT_MENTION_RUNTIME_CHUNK_CHARS: usize = 512;

pub(crate) struct WorkspaceAgentMentionRuntimeInput {
    pub(crate) workspace_id: String,
    pub(crate) conversation_id: String,
    pub(crate) target_agent_id: String,
    pub(crate) agent_name: String,
    pub(crate) sender_name: Option<String>,
    pub(crate) user_prompt: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct WorkspaceAgentMentionRuntimeOutput {
    pub(crate) final_content: String,
    pub(crate) token_chunks: Vec<String>,
}

impl WorkspaceAgentMentionRuntimeOutput {
    pub(crate) fn from_final_content(final_content: impl Into<String>) -> CoreResult<Self> {
        let final_content = final_content.into();
        let final_content = final_content.trim();
        if final_content.is_empty() {
            return Err(CoreError::Llm(
                "workspace mention runtime returned an empty answer".to_string(),
            ));
        }
        Ok(Self {
            final_content: final_content.to_string(),
            token_chunks: chunk_runtime_content(final_content),
        })
    }
}

#[async_trait]
pub(crate) trait WorkspaceAgentMentionRuntime: Send + Sync {
    async fn complete(
        &self,
        input: WorkspaceAgentMentionRuntimeInput,
    ) -> CoreResult<WorkspaceAgentMentionRuntimeOutput>;
}

pub(crate) fn workspace_agent_mention_runtime_from_env(
    llm: Arc<dyn LlmPort>,
) -> Option<Arc<dyn WorkspaceAgentMentionRuntime>> {
    if workspace_mention_runtime_gate_enabled() {
        Some(Arc::new(LlmWorkspaceAgentMentionRuntime { llm }))
    } else {
        None
    }
}

fn workspace_mention_runtime_gate_enabled() -> bool {
    workspace_mention_runtime_gate_from_values(
        bool_env(WORKSPACE_MENTION_RUNTIME_ENABLED_ENV, false),
        bool_env(WORKSPACE_MENTION_RUNTIME_PRODUCTION_READY_ENV, false),
    )
}

fn workspace_mention_runtime_gate_from_values(enabled: bool, production_ready: bool) -> bool {
    enabled && production_ready
}

struct LlmWorkspaceAgentMentionRuntime {
    llm: Arc<dyn LlmPort>,
}

#[async_trait]
impl WorkspaceAgentMentionRuntime for LlmWorkspaceAgentMentionRuntime {
    async fn complete(
        &self,
        input: WorkspaceAgentMentionRuntimeInput,
    ) -> CoreResult<WorkspaceAgentMentionRuntimeOutput> {
        let goal = render_workspace_agent_mention_goal(&input);
        match self.llm.decide(&goal, 0, &[], &[]).await? {
            AgentAction::Finish { answer } => {
                WorkspaceAgentMentionRuntimeOutput::from_final_content(answer)
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

fn chunk_runtime_content(content: &str) -> Vec<String> {
    let mut chunks = Vec::new();
    let mut chunk = String::new();
    let mut len = 0_usize;
    for ch in content.chars() {
        if len >= WORKSPACE_AGENT_MENTION_RUNTIME_CHUNK_CHARS {
            chunks.push(chunk);
            chunk = String::new();
            len = 0;
        }
        chunk.push(ch);
        len += 1;
    }
    if !chunk.is_empty() {
        chunks.push(chunk);
    }
    chunks
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

#[cfg(test)]
mod tests {
    use super::{
        chunk_runtime_content, workspace_mention_runtime_gate_from_values,
        WORKSPACE_AGENT_MENTION_RUNTIME_CHUNK_CHARS,
    };

    #[test]
    fn workspace_mention_runtime_requires_enabled_and_production_ready_gates() {
        assert!(!workspace_mention_runtime_gate_from_values(false, false));
        assert!(!workspace_mention_runtime_gate_from_values(true, false));
        assert!(!workspace_mention_runtime_gate_from_values(false, true));
        assert!(workspace_mention_runtime_gate_from_values(true, true));
    }

    #[test]
    fn workspace_mention_runtime_chunks_final_content_deterministically() {
        let content = "a".repeat(WORKSPACE_AGENT_MENTION_RUNTIME_CHUNK_CHARS + 3);
        let chunks = chunk_runtime_content(&content);
        assert_eq!(chunks.len(), 2);
        assert_eq!(
            chunks[0].chars().count(),
            WORKSPACE_AGENT_MENTION_RUNTIME_CHUNK_CHARS
        );
        assert_eq!(chunks[1], "aaa");
    }
}
