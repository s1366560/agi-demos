use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct AgentRegistryLookup {
    pub(super) tenant_id: String,
    pub(super) project_id: String,
    pub(super) agent_id: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ProviderRegistryLookup {
    pub(super) tenant_id: String,
    pub(super) provider_id: String,
    pub(super) model_id: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ProviderRegistryDefaultLookup {
    pub(super) tenant_id: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ProviderBotRef {
    pub(super) provider_id: String,
    #[serde(default)]
    pub(super) provider_bot_ref: String,
    #[serde(default)]
    pub(super) tags: Vec<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ProviderSender {
    pub(super) kind: String,
    pub(super) name: String,
    #[serde(default)]
    pub(super) actor_id: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ProviderExtensions {
    pub(super) tenant_id: String,
    pub(super) project_id: String,
    pub(super) workspace_id: String,
    pub(super) user_id: String,
    pub(super) conversation_id: String,
    #[serde(default)]
    pub(super) task_id: Option<String>,
    #[serde(default)]
    pub(super) attempt_id: Option<String>,
    #[serde(default)]
    pub(super) plan_id: Option<String>,
    #[serde(default)]
    pub(super) plan_node_id: Option<String>,
    #[serde(default)]
    pub(super) workspace_agent_binding_id: Option<String>,
    #[serde(default)]
    pub(super) delivery_request_id: Option<String>,
    #[serde(default)]
    pub(super) bcs_message_id: Option<String>,
    #[serde(default)]
    pub(super) workspace_message_correlation_id: Option<String>,
    #[serde(default)]
    pub(super) correlation_id: Option<String>,
}

impl ProviderExtensions {
    pub(super) fn callback_value(&self) -> Value {
        serde_json::to_value(self).unwrap_or_else(|_| Value::Object(Default::default()))
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
pub(super) enum ProviderMethod {
    #[serde(rename = "chat.send")]
    Send,
    #[serde(rename = "chat.inject")]
    Inject,
    #[serde(rename = "chat.abort")]
    Abort,
    #[serde(rename = "chat.history")]
    History,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ProviderWebhookRequest {
    #[serde(rename = "type")]
    pub(super) frame_type: String,
    pub(super) id: String,
    pub(super) method: ProviderMethod,
    pub(super) session_id: String,
    pub(super) bcn_group_id: String,
    pub(super) to_bot: ProviderBotRef,
    #[serde(default)]
    pub(super) from: Option<ProviderSender>,
    #[serde(default)]
    pub(super) message: Option<Value>,
    #[serde(default)]
    pub(super) attachments: Vec<Value>,
    #[serde(default)]
    pub(super) before: Option<u64>,
    #[serde(default)]
    pub(super) after: Option<u64>,
    #[serde(default)]
    pub(super) limit: Option<u64>,
    pub(super) timeout_ms: u64,
    pub(super) extensions: ProviderExtensions,
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum PlanDispatchAction {
    RecoverStaleAttempts,
    TriggerNextIteration,
    RunPipeline,
    RegenerateDeliveryContract,
}

impl PlanDispatchAction {
    pub(super) const fn as_str(self) -> &'static str {
        match self {
            Self::RecoverStaleAttempts => "recover_stale_attempts",
            Self::TriggerNextIteration => "trigger_next_iteration",
            Self::RunPipeline => "run_pipeline",
            Self::RegenerateDeliveryContract => "regenerate_delivery_contract",
        }
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct PlanDispatchRequest {
    pub(super) tenant_id: String,
    pub(super) project_id: String,
    pub(super) workspace_id: String,
    pub(super) plan_id: String,
    #[serde(default)]
    pub(super) plan_node_id: Option<String>,
    #[serde(default)]
    pub(super) task_id: Option<String>,
    #[serde(default)]
    pub(super) attempt_id: Option<String>,
    #[serde(default)]
    pub(super) agent_id: Option<String>,
    pub(super) action: PlanDispatchAction,
    pub(super) outbox_id: String,
    pub(super) correlation_id: String,
    pub(super) conversation_id: String,
    pub(super) payload: Value,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ContextJudgeRequest {
    pub(super) user_id: String,
    #[serde(default)]
    pub(super) current: Option<ContextCurrent>,
    pub(super) candidates: Vec<ContextCandidate>,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ContextCurrent {
    pub(super) tenant_id: String,
    pub(super) project_id: String,
    pub(super) revision: u64,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Eq, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ContextCandidate {
    pub(super) tenant_id: String,
    pub(super) project_id: String,
    pub(super) membership_role: String,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct PlanJudgeRequest {
    pub(super) tenant_id: String,
    pub(super) project_id: String,
    pub(super) workspace_id: String,
    pub(super) actor_id: String,
    pub(super) plan_id: String,
    pub(super) plan_revision: u64,
    pub(super) kind: String,
    pub(super) candidate_node_ids: Vec<String>,
    pub(super) evidence: Value,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct AutonomyJudgeRequest {
    pub(super) tenant_id: String,
    pub(super) project_id: String,
    pub(super) workspace_id: String,
    pub(super) actor_id: String,
    pub(super) workspace_revision: u64,
    pub(super) force: bool,
    pub(super) candidates: Vec<AutonomyCandidate>,
    pub(super) agent_candidates: Vec<AutonomyAgentCandidate>,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct AutonomyCandidate {
    pub(super) root_task_id: String,
    pub(super) title: String,
    #[serde(default)]
    pub(super) description: Option<String>,
    pub(super) status: String,
    pub(super) metadata: Value,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct AutonomyAgentCandidate {
    pub(super) workspace_agent_binding_id: String,
    pub(super) agent_id: String,
    #[serde(default)]
    pub(super) display_name: Option<String>,
    #[serde(default)]
    pub(super) description: Option<String>,
    pub(super) status: String,
    pub(super) config: Value,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct AutonomyNextAction {
    pub(super) title: String,
    pub(super) description: String,
    pub(super) workspace_agent_binding_id: String,
}
