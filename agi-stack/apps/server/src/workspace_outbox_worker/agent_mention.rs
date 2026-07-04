use std::collections::{HashMap, HashSet};
use std::sync::Arc;

use agistack_adapters_postgres::{
    BlackboardOutboxRecord, WorkspaceAgentRecord, WorkspaceMessageRecord, WorkspacePlanOutboxRecord,
};
use agistack_adapters_secrets::generate_uuid_v4;
use agistack_core::agent::types::AgentAction;
use agistack_core::ports::{CoreError, CoreResult, LlmPort};
use async_trait::async_trait;
use chrono::{DateTime, Utc};
use serde_json::{json, Map, Value};
use uuid::Uuid;

use super::{
    bool_env, compact_text, metadata_string_values, object_or_empty, required_string,
    string_from_map, workspace_event_iso, workspace_message_event_payload,
    WorkspacePlanDispatchStore, WorkspacePlanOutboxHandler, WorkspacePlanOutboxHandlerOutcome,
};

pub(super) const WORKSPACE_AGENT_MENTION_EVENT: &str = "workspace_agent_mention";
pub(super) const WORKSPACE_AGENT_MENTION_PENDING_RUNTIME_STATUS: &str = "pending_runtime";
pub(super) const WORKSPACE_AGENT_MENTION_RUNTIME_BOUND_STATUS: &str = "runtime_bound";
pub(super) const WORKSPACE_AGENT_MENTION_RESPONSE_READY_STATUS: &str = "runtime_response_ready";
pub(super) const WORKSPACE_AGENT_MENTION_ERROR_READY_STATUS: &str = "runtime_error_ready";
pub(super) const WORKSPACE_MESSAGE_CREATED_EVENT: &str = "workspace_message_created";
const WORKSPACE_MENTION_RUNTIME_ENABLED_ENV: &str = "AGISTACK_WORKSPACE_MENTION_RUNTIME_ENABLED";
pub(super) const MAX_WORKSPACE_AGENT_MENTION_CHAIN_DEPTH: i64 = 3;
pub(super) const WORKSPACE_AGENT_CHAIN_MENTION_SOURCE: &str = "workspace_agent_chain_mention";
pub(super) const WORKSPACE_AGENT_CHAIN_MENTION_STAGE: &str = "agent_chain_mention";

pub(crate) struct WorkspaceAgentMentionRuntimeInput {
    pub(crate) workspace_id: String,
    pub(crate) conversation_id: String,
    pub(crate) target_agent_id: String,
    pub(crate) agent_name: String,
    pub(crate) sender_name: Option<String>,
    pub(crate) user_prompt: String,
}

struct WorkspaceAgentMentionChainInput<'a> {
    payload: &'a Map<String, Value>,
    message: &'a WorkspaceMessageRecord,
    workspace_id: &'a str,
    tenant_id: &'a str,
    project_id: &'a str,
    sender_user_id: &'a str,
    source_agent_id: &'a str,
    source_agent_name: &'a str,
    now: DateTime<Utc>,
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

pub(crate) struct WorkspaceAgentMentionBindingHandler {
    store: Arc<dyn WorkspacePlanDispatchStore>,
    runtime: Option<Arc<dyn WorkspaceAgentMentionRuntime>>,
}

impl WorkspaceAgentMentionBindingHandler {
    pub(crate) fn new(store: Arc<dyn WorkspacePlanDispatchStore>) -> Self {
        Self {
            store,
            runtime: None,
        }
    }

    pub(crate) fn with_runtime(
        store: Arc<dyn WorkspacePlanDispatchStore>,
        runtime: Arc<dyn WorkspaceAgentMentionRuntime>,
    ) -> Self {
        Self {
            store,
            runtime: Some(runtime),
        }
    }

    async fn enqueue_agent_chain_mentions(
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

    #[allow(clippy::too_many_arguments)]
    async fn post_terminal_message(
        &self,
        payload: &Map<String, Value>,
        workspace_id: &str,
        tenant_id: &str,
        project_id: &str,
        sender_user_id: &str,
        target_agent_id: &str,
        agent_name: &str,
        content: String,
        now: DateTime<Utc>,
    ) -> CoreResult<WorkspacePlanOutboxHandlerOutcome> {
        let members = self
            .store
            .list_workspace_member_user_ids(workspace_id)
            .await?;
        if !members.iter().any(|member| member == sender_user_id) {
            return Ok(WorkspacePlanOutboxHandlerOutcome::Complete);
        }

        let parent_message_id = string_from_map(payload, "message_id")
            .or_else(|| string_from_map(payload, "parent_message_id"));
        let mentions = metadata_string_values(payload.get("response_mentions"));
        let message = self
            .store
            .create_workspace_message(WorkspaceMessageRecord {
                id: generate_uuid_v4(),
                workspace_id: workspace_id.to_string(),
                sender_id: target_agent_id.to_string(),
                sender_type: "agent".to_string(),
                content,
                mentions_json: mentions,
                parent_message_id,
                metadata_json: json!({ "sender_name": agent_name }),
                created_at: now,
            })
            .await?;
        self.store
            .enqueue_blackboard_outbox(BlackboardOutboxRecord {
                id: generate_uuid_v4(),
                workspace_id: workspace_id.to_string(),
                tenant_id: tenant_id.to_string(),
                project_id: project_id.to_string(),
                event_type: WORKSPACE_MESSAGE_CREATED_EVENT.to_string(),
                payload_json: json!({
                    "message": workspace_message_event_payload(&message)
                }),
                metadata_json: json!({
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "surface_owner": "workspace-chat",
                    "surface_boundary": "hosted",
                    "authority_class": "non-authoritative",
                    "signal_role": "sensing-capable",
                    "runtime_bridge": "p3_workspace_mention"
                }),
                correlation_id: None,
            })
            .await?;
        self.enqueue_agent_chain_mentions(WorkspaceAgentMentionChainInput {
            payload,
            message: &message,
            workspace_id,
            tenant_id,
            project_id,
            sender_user_id,
            source_agent_id: target_agent_id,
            source_agent_name: agent_name,
            now,
        })
        .await?;

        Ok(WorkspacePlanOutboxHandlerOutcome::Complete)
    }
}

#[async_trait]
impl WorkspacePlanOutboxHandler for WorkspaceAgentMentionBindingHandler {
    async fn handle(
        &self,
        item: WorkspacePlanOutboxRecord,
    ) -> CoreResult<WorkspacePlanOutboxHandlerOutcome> {
        let payload = object_or_empty(item.payload_json.clone());
        let now = Utc::now();
        let workspace_id =
            string_from_map(&payload, "workspace_id").unwrap_or_else(|| item.workspace_id.clone());
        let project_id = required_string(&payload, "project_id")?;
        let tenant_id = required_string(&payload, "tenant_id")?;
        let sender_user_id = required_string(&payload, "sender_user_id")?;
        let target_agent_id = required_string(&payload, "target_agent_id")?;
        let conversation_id = required_string(&payload, "conversation_id")?;
        let agent_name = string_from_map(&payload, "agent_name")
            .or_else(|| string_from_map(&payload, "agent_display_name"))
            .unwrap_or_else(|| target_agent_id.clone());
        if let Some(error_detail) = workspace_agent_mention_error_detail(&payload) {
            return self
                .post_terminal_message(
                    &payload,
                    &workspace_id,
                    &tenant_id,
                    &project_id,
                    &sender_user_id,
                    &target_agent_id,
                    &agent_name,
                    format!("[Error] {agent_name} could not process your request: {error_detail}"),
                    now,
                )
                .await;
        }
        if let Some(final_content) = workspace_agent_mention_final_content(&payload) {
            return self
                .post_terminal_message(
                    &payload,
                    &workspace_id,
                    &tenant_id,
                    &project_id,
                    &sender_user_id,
                    &target_agent_id,
                    &agent_name,
                    final_content,
                    now,
                )
                .await;
        }
        let linked_workspace_task_id = string_from_map(&payload, "linked_workspace_task_id")
            .or_else(|| string_from_map(&payload, "workspace_task_id"));
        let source = string_from_map(&payload, "source");
        let workspace_llm_stage = string_from_map(&payload, "workspace_llm_stage");

        let mut conversation_metadata = Map::new();
        conversation_metadata.insert("workspace_id".to_string(), json!(workspace_id));
        conversation_metadata.insert("agent_id".to_string(), json!(target_agent_id));
        conversation_metadata.insert("created_at".to_string(), json!(now.to_rfc3339()));
        if let Some(task_id) = linked_workspace_task_id.as_deref() {
            conversation_metadata.insert("workspace_task_id".to_string(), json!(task_id));
            conversation_metadata.insert("linked_workspace_task_id".to_string(), json!(task_id));
        }
        if let Some(source) = source.as_deref() {
            conversation_metadata.insert("source".to_string(), json!(source));
        }
        if let Some(stage) = workspace_llm_stage.as_deref() {
            conversation_metadata.insert("workspace_llm_stage".to_string(), json!(stage));
        }

        self.store
            .ensure_workspace_agent_conversation(
                &conversation_id,
                &project_id,
                &tenant_id,
                &sender_user_id,
                &format!("Workspace Chat - {agent_name}"),
                &json!({ "selected_agent_id": target_agent_id }),
                &Value::Object(conversation_metadata),
                &workspace_id,
                linked_workspace_task_id.as_deref(),
                now,
            )
            .await?;

        let base_metadata_patch = json!({
            "runtime_bound_at": now.to_rfc3339(),
            "runtime_binding": "workspace_agent_mention_conversation",
            "runtime_bridge": "p3_workspace_mention",
            "conversation_id": conversation_id,
            "target_agent_id": target_agent_id,
            "workspace_llm_stage": workspace_llm_stage,
        });
        if let Some(runtime) = self.runtime.as_ref() {
            let user_prompt = workspace_agent_mention_user_prompt(&payload);
            let status;
            let payload_patch;
            let mut metadata_patch = object_or_empty(base_metadata_patch);
            metadata_patch.insert("runtime_writer".to_string(), json!("llm_port_single_turn"));
            metadata_patch.insert("runtime_ready_at".to_string(), json!(now.to_rfc3339()));
            match runtime
                .complete(WorkspaceAgentMentionRuntimeInput {
                    workspace_id: workspace_id.clone(),
                    conversation_id: conversation_id.clone(),
                    target_agent_id: target_agent_id.clone(),
                    agent_name: agent_name.clone(),
                    sender_name: string_from_map(&payload, "sender_name"),
                    user_prompt,
                })
                .await
            {
                Ok(final_content) => {
                    status = WORKSPACE_AGENT_MENTION_RESPONSE_READY_STATUS.to_string();
                    payload_patch = json!({
                        "final_content": final_content,
                        "runtime_final_content": final_content,
                    });
                    metadata_patch.insert("runtime_writer_status".to_string(), json!("ok"));
                }
                Err(err) => {
                    status = WORKSPACE_AGENT_MENTION_ERROR_READY_STATUS.to_string();
                    let error_detail = compact_text(&err.to_string(), 4_000);
                    payload_patch = json!({
                        "runtime_error_detail": error_detail,
                    });
                    metadata_patch.insert("runtime_writer_status".to_string(), json!("error"));
                }
            }
            return Ok(WorkspacePlanOutboxHandlerOutcome::ParkWithPayload {
                status,
                metadata_patch: Value::Object(metadata_patch),
                payload_patch,
            });
        }

        Ok(WorkspacePlanOutboxHandlerOutcome::Park {
            status: WORKSPACE_AGENT_MENTION_RUNTIME_BOUND_STATUS.to_string(),
            metadata_patch: base_metadata_patch,
        })
    }
}

fn workspace_agent_mention_final_content(payload: &Map<String, Value>) -> Option<String> {
    string_from_map(payload, "final_content")
        .or_else(|| string_from_map(payload, "runtime_final_content"))
        .or_else(|| string_from_map(payload, "response_content"))
}

fn workspace_agent_mention_error_detail(payload: &Map<String, Value>) -> Option<String> {
    string_from_map(payload, "error_detail")
        .or_else(|| string_from_map(payload, "runtime_error_detail"))
        .or_else(|| string_from_map(payload, "error_message"))
}

fn workspace_agent_mention_user_prompt(payload: &Map<String, Value>) -> String {
    string_from_map(payload, "user_prompt")
        .or_else(|| {
            payload
                .get("source_message")
                .and_then(|value| value.as_object())
                .and_then(|source| string_from_map(source, "content"))
        })
        .or_else(|| string_from_map(payload, "message"))
        .unwrap_or_default()
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
