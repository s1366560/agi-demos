use std::collections::HashSet;

use chrono::{DateTime, Utc};
use serde_json::{json, Value};
use uuid::Uuid;

use super::*;

pub(super) const WORKSPACE_AGENT_MENTION_EVENT: &str = "workspace_agent_mention";
pub(super) const WORKSPACE_AGENT_MENTION_STATUS: &str = "pending_runtime";
const WORKSPACE_AGENT_MENTION_SOURCE: &str = "workspace_chat_mention";
const WORKSPACE_AGENT_MENTION_STAGE: &str = "chat_mention";

pub(super) fn resolve_structured_mentions(
    requested: &[String],
    member_ids: &[String],
    agent_ids: &[String],
) -> Result<Vec<String>, WorkspaceApiError> {
    let requested: Vec<_> = requested
        .iter()
        .map(|mention| mention.trim())
        .filter(|mention| !mention.is_empty())
        .map(ToOwned::to_owned)
        .collect();
    if requested.is_empty() {
        return Ok(Vec::new());
    }
    if requested
        .iter()
        .any(|mention| mention.eq_ignore_ascii_case("all"))
    {
        return Ok(agent_ids.to_vec());
    }
    let valid: HashSet<&str> = member_ids
        .iter()
        .chain(agent_ids.iter())
        .map(String::as_str)
        .collect();
    let mut seen = HashSet::new();
    let mut mentions = Vec::new();
    for mention in requested {
        if !valid.contains(mention.as_str()) {
            return Err(WorkspaceApiError::bad_request(
                "Invalid workspace chat request",
            ));
        }
        if seen.insert(mention.clone()) {
            mentions.push(mention);
        }
    }
    Ok(mentions)
}

pub(super) struct WorkspaceAgentMentionOutboxInput<'a> {
    pub(super) tenant_id: &'a str,
    pub(super) project_id: &'a str,
    pub(super) workspace_id: &'a str,
    pub(super) sender_user_id: &'a str,
    pub(super) sender_name: &'a str,
    pub(super) message: &'a MessageView,
    pub(super) agents: &'a [WorkspaceAgentRecord],
    pub(super) now: DateTime<Utc>,
}

pub(super) fn workspace_agent_mention_outbox_records(
    input: WorkspaceAgentMentionOutboxInput<'_>,
) -> Vec<WorkspacePlanOutboxRecord> {
    let conversation_scope = workspace_message_conversation_scope(&input.message.metadata);
    input
        .message
        .mentions
        .iter()
        .filter_map(|mention| input.agents.iter().find(|agent| agent.agent_id == *mention))
        .map(|agent| {
            let agent_name = workspace_agent_display_name(agent).to_string();
            let conversation_id = workspace_conversation_id(
                input.workspace_id,
                &agent.agent_id,
                conversation_scope.as_deref(),
            );
            let payload_json = json!({
                "workspace_id": input.workspace_id,
                "tenant_id": input.tenant_id,
                "project_id": input.project_id,
                "message_id": &input.message.id,
                "parent_message_id": &input.message.parent_message_id,
                "sender_user_id": input.sender_user_id,
                "sender_name": input.sender_name,
                "target_agent_id": &agent.agent_id,
                "target_workspace_agent_id": &agent.id,
                "agent_display_name": &agent.display_name,
                "agent_name": &agent_name,
                "conversation_id": &conversation_id,
                "conversation_scope": conversation_scope.clone(),
                "user_prompt": format!(
                    "[Workspace Chat] {} mentioned you:\n\n{}",
                    input.sender_name, input.message.content
                ),
                "source_message": {
                    "id": &input.message.id,
                    "content": &input.message.content,
                    "created_at": &input.message.created_at,
                    "mentions": &input.message.mentions,
                },
                "chain_depth": 0,
                "source": WORKSPACE_AGENT_MENTION_SOURCE,
                "workspace_llm_stage": WORKSPACE_AGENT_MENTION_STAGE,
            });
            WorkspacePlanOutboxRecord {
                id: new_id(),
                plan_id: None,
                workspace_id: input.workspace_id.to_string(),
                event_type: WORKSPACE_AGENT_MENTION_EVENT.to_string(),
                payload_json,
                status: WORKSPACE_AGENT_MENTION_STATUS.to_string(),
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
                    "target_agent_id": &agent.agent_id,
                    "conversation_id": &conversation_id,
                    "message_id": &input.message.id,
                }),
                created_at: input.now,
                updated_at: None,
            }
        })
        .collect()
}

fn workspace_agent_display_name(agent: &WorkspaceAgentRecord) -> &str {
    agent
        .display_name
        .as_deref()
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .unwrap_or(&agent.agent_id)
}

fn workspace_message_conversation_scope(metadata: &Value) -> Option<String> {
    metadata
        .get("conversation_scope")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToOwned::to_owned)
}

pub(super) fn workspace_conversation_id(
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
