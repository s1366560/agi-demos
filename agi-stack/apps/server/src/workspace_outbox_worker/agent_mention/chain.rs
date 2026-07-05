use std::collections::{HashMap, HashSet};

use agistack_adapters_postgres::{
    WorkspaceAgentRecord, WorkspaceMessageRecord, WorkspacePlanOutboxRecord,
};
use agistack_adapters_secrets::generate_uuid_v4;
use agistack_core::ports::CoreResult;
use chrono::{DateTime, Utc};
use serde_json::{json, Map, Value};

use super::{
    string_from_map, workspace_agent_conversation_id, workspace_event_iso,
    WorkspaceAgentMentionBindingHandler, MAX_WORKSPACE_AGENT_MENTION_CHAIN_DEPTH,
    WORKSPACE_AGENT_CHAIN_MENTION_SOURCE, WORKSPACE_AGENT_CHAIN_MENTION_STAGE,
    WORKSPACE_AGENT_MENTION_EVENT, WORKSPACE_AGENT_MENTION_PENDING_RUNTIME_STATUS,
};

pub(super) struct WorkspaceAgentMentionChainInput<'a> {
    pub(super) payload: &'a Map<String, Value>,
    pub(super) message: &'a WorkspaceMessageRecord,
    pub(super) workspace_id: &'a str,
    pub(super) tenant_id: &'a str,
    pub(super) project_id: &'a str,
    pub(super) sender_user_id: &'a str,
    pub(super) source_agent_id: &'a str,
    pub(super) source_agent_name: &'a str,
    pub(super) now: DateTime<Utc>,
}

impl WorkspaceAgentMentionBindingHandler {
    pub(super) async fn enqueue_agent_chain_mentions(
        &self,
        input: WorkspaceAgentMentionChainInput<'_>,
    ) -> CoreResult<()> {
        if input.message.mentions_json.is_empty() {
            return Ok(());
        }
        let chain_depth = workspace_agent_mention_chain_depth(input.payload);
        if chain_depth >= MAX_WORKSPACE_AGENT_MENTION_CHAIN_DEPTH {
            return Ok(());
        }
        let conversation_scope = string_from_map(input.payload, "conversation_scope");
        let active_agents = self
            .store
            .list_active_workspace_agents(input.workspace_id)
            .await?;
        let active_agent_by_id: HashMap<&str, &WorkspaceAgentRecord> = active_agents
            .iter()
            .map(|agent| (agent.agent_id.as_str(), agent))
            .collect();
        let mut enqueued_agent_ids = HashSet::with_capacity(input.message.mentions_json.len());
        for mention in &input.message.mentions_json {
            let Some(agent) = active_agent_by_id.get(mention.as_str()).copied() else {
                continue;
            };
            if !enqueued_agent_ids.insert(agent.agent_id.as_str()) {
                continue;
            }
            let agent_name = workspace_agent_record_display_name(agent);
            let conversation_id = workspace_agent_conversation_id(
                input.workspace_id,
                &agent.agent_id,
                conversation_scope.as_deref(),
            );
            let next_chain_depth = chain_depth + 1;
            self.store
                .enqueue_plan_outbox(WorkspacePlanOutboxRecord {
                    id: generate_uuid_v4(),
                    plan_id: None,
                    workspace_id: input.workspace_id.to_string(),
                    event_type: WORKSPACE_AGENT_MENTION_EVENT.to_string(),
                    payload_json: json!({
                        "workspace_id": input.workspace_id,
                        "tenant_id": input.tenant_id,
                        "project_id": input.project_id,
                        "message_id": &input.message.id,
                        "parent_message_id": &input.message.parent_message_id,
                        "sender_user_id": input.sender_user_id,
                        "sender_name": input.source_agent_name,
                        "source_agent_id": input.source_agent_id,
                        "target_agent_id": &agent.agent_id,
                        "target_workspace_agent_id": &agent.id,
                        "agent_display_name": &agent.display_name,
                        "agent_name": agent_name,
                        "conversation_id": &conversation_id,
                        "conversation_scope": conversation_scope.clone(),
                        "user_prompt": format!(
                            "[Workspace Chat] {} mentioned you:\n\n{}",
                            input.source_agent_name, input.message.content
                        ),
                        "source_message": {
                            "id": &input.message.id,
                            "content": &input.message.content,
                            "created_at": workspace_event_iso(input.message.created_at),
                            "mentions": &input.message.mentions_json,
                        },
                        "chain_depth": next_chain_depth,
                        "source": WORKSPACE_AGENT_CHAIN_MENTION_SOURCE,
                        "workspace_llm_stage": WORKSPACE_AGENT_CHAIN_MENTION_STAGE,
                    }),
                    status: WORKSPACE_AGENT_MENTION_PENDING_RUNTIME_STATUS.to_string(),
                    attempt_count: 0,
                    max_attempts: 5,
                    lease_owner: None,
                    lease_expires_at: None,
                    last_error: None,
                    next_attempt_at: None,
                    processed_at: None,
                    metadata_json: json!({
                        "tenant_id": input.tenant_id,
                        "project_id": input.project_id,
                        "surface_owner": "workspace-chat",
                        "surface_boundary": "hosted",
                        "authority_class": "agent-runtime-admission",
                        "signal_role": "runtime-trigger",
                        "runtime_bridge": "p3_workspace_mention",
                        "source": WORKSPACE_AGENT_CHAIN_MENTION_SOURCE,
                        "source_agent_id": input.source_agent_id,
                        "target_agent_id": &agent.agent_id,
                        "conversation_id": &conversation_id,
                        "message_id": &input.message.id,
                        "chain_depth": next_chain_depth,
                    }),
                    created_at: input.now,
                    updated_at: None,
                })
                .await?;
        }
        Ok(())
    }
}

fn workspace_agent_mention_chain_depth(payload: &Map<String, Value>) -> i64 {
    payload
        .get("chain_depth")
        .and_then(Value::as_i64)
        .unwrap_or(0)
        .max(0)
}

fn workspace_agent_record_display_name(agent: &WorkspaceAgentRecord) -> &str {
    agent
        .display_name
        .as_deref()
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .unwrap_or(&agent.agent_id)
}
