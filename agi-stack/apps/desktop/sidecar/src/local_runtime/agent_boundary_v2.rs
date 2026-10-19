//! Pinned generation authority and private, durable provider request snapshots.

use agistack_adapters_http_llm::RequestLoggedLlm;
use agistack_core::{
    agent::tool_policy::ToolExecutionPolicy,
    model_request::{ModelRequestLog, ModelRequestStatus},
};
use agistack_plugin_host::{
    protocol_v2::tool_policy_adapter::GenerationToolExecutionPolicyV2, ScopeKindV2, ScopeV2,
};

use super::*;

pub(super) struct AgentBoundaryV2 {
    policy: Arc<dyn ToolExecutionPolicy>,
    log: Arc<NativeModelRequestLogV2>,
    // The resolved policy service cannot outlive the operation's generation.
    _lease: Arc<ActivePlatformPluginGenerationLeaseV2>,
}

impl AgentBoundaryV2 {
    pub(super) fn new(
        state: &LocalRuntimeState,
        conversation: &LocalConversation,
        message_id: &str,
        operation_id: &str,
        generation: Arc<ActivePlatformPluginGenerationLeaseV2>,
    ) -> Result<Arc<Self>, String> {
        let scope = ScopeV2 {
            kind: ScopeKindV2::Session,
            tenant_id: Some(conversation.tenant_id.clone()),
            project_id: Some(conversation.project_id.clone()),
            session_id: Some(conversation.id.clone()),
        };
        let service = generation
            .tool_policy(&scope)
            .map_err(|error| error.to_string())?;
        let contributors = generation.request_contributors(&scope);
        let policy = GenerationToolExecutionPolicyV2::new(
            service,
            scope,
            operation_id.into(),
            generation.descriptor().digest.clone(),
        );
        Ok(Arc::new(Self {
            policy: Arc::new(policy),
            log: Arc::new(NativeModelRequestLogV2 {
                store: state.session_store.clone(),
                conversation_id: conversation.id.clone(),
                message_id: message_id.into(),
                operation_id: operation_id.into(),
                generation_digest: generation.descriptor().digest.clone(),
                contributors,
            }),
            _lease: generation,
        }))
    }

    pub(super) fn wrap_llm(&self, llm: Arc<dyn LlmPort>) -> Arc<dyn LlmPort> {
        Arc::new(RequestLoggedLlm::new(llm, self.log.clone()))
    }

    pub(super) fn wrap_engine(self: &Arc<Self>, engine: ReActEngine) -> ReActEngine {
        // Keep the lease alive together with the policy, including child engines.
        engine.with_tool_policy(Arc::new(PinnedPolicy {
            boundary: self.clone(),
            pending: Mutex::new(HashMap::new()),
        }))
    }
}

struct PinnedPolicy {
    boundary: Arc<AgentBoundaryV2>,
    pending: Mutex<HashMap<String, Vec<tool_result_events_v2::PendingResultEvent>>>,
}
async fn capture_content(
    context: &agistack_core::agent::tool_policy::ToolPolicyContext<'_>,
    tools: &dyn ToolHost,
    input: &str,
) -> (
    CoreResult<agistack_core::ports::ToolResult>,
    Vec<tool_result_events_v2::PendingResultEvent>,
) {
    tool_result_events_v2::capture(computer_use_v2::call_identity::scope(
        context,
        tools.call_with_content(context.tool, input),
    ))
    .await
}

#[async_trait]
impl ToolExecutionPolicy for PinnedPolicy {
    async fn before_execute(
        &self,
        context: &agistack_core::agent::tool_policy::ToolPolicyContext<'_>,
        input: &str,
        schema: Option<&Value>,
    ) -> CoreResult<agistack_core::agent::tool_policy::ToolPolicyDecision> {
        self.boundary
            .policy
            .before_execute(context, input, schema)
            .await
    }
    async fn execute(
        &self,
        context: &agistack_core::agent::tool_policy::ToolPolicyContext<'_>,
        tools: &dyn ToolHost,
        input: &str,
    ) -> CoreResult<String> {
        let (result, events) = tool_result_events_v2::capture(
            computer_use_v2::call_identity::scope(context, tools.call(context.tool, input)),
        )
        .await;
        self.pending
            .lock()
            .expect("pending policy results")
            .insert(context.call_id(), events);
        result
    }
    async fn execute_with_content(
        &self,
        context: &agistack_core::agent::tool_policy::ToolPolicyContext<'_>,
        tools: &dyn ToolHost,
        input: &str,
    ) -> CoreResult<agistack_core::ports::ToolResult> {
        let (result, events) = capture_content(context, tools, input).await;
        self.pending
            .lock()
            .expect("pending policy results")
            .insert(context.call_id(), events);
        result
    }
    async fn transform_result(
        &self,
        context: &agistack_core::agent::tool_policy::ToolPolicyContext<'_>,
        result: agistack_core::agent::tool_policy::ToolPolicyResult,
    ) -> CoreResult<agistack_core::agent::tool_policy::ToolPolicyResult> {
        let pending = self
            .pending
            .lock()
            .expect("pending policy results")
            .remove(&context.call_id())
            .unwrap_or_default();
        let raw_output = result.output.clone();
        let raw_media = result.media.clone();
        let accepted = self
            .boundary
            .policy
            .transform_result(context, result)
            .await?;
        // App payloads embed the original body. Any replacement uses the normal
        // transformed observation renderer, never the obsolete embedded body.
        if !accepted.is_error && accepted.output == raw_output && accepted.media == raw_media {
            tool_result_events_v2::publish(pending);
        }
        Ok(accepted)
    }
}

struct NativeModelRequestLogV2 {
    store: session_store::DesktopSessionStore,
    conversation_id: String,
    message_id: String,
    operation_id: String,
    generation_digest: String,
    contributors: Value,
}

impl NativeModelRequestLogV2 {
    fn append(&self, event: &str, attempt_id: &str, data: Value) -> CoreResult<()> {
        let child = local_plugin_tool_host_v2::identity::current_child();
        let item = json!({
            "id": Uuid::new_v4().to_string(), "type": event,
            "conversation_id": self.conversation_id, "message_id": self.message_id,
            "timestamp": now_iso(),
            "data": {
                "attempt_id": attempt_id,
                "schema_version": 1,
                "format": "provider.http.json/v1",
                "operation_id": self.operation_id,
                "generation_digest": self.generation_digest,
                "contributors": self.contributors,
                "child_execution_id": child.map(|child| child.execution_id),
                "request": data,
            },
        });
        // Do not broadcast model request bodies as public timeline observations.
        self.store
            .append_timeline(&self.conversation_id, &item)
            .map_err(CoreError::Storage)
    }
}

#[async_trait]
impl ModelRequestLog for NativeModelRequestLogV2 {
    async fn prepare_request(&self, protocol: &str, body: Value) -> CoreResult<String> {
        let id = Uuid::new_v4().to_string();
        self.append(
            "model_request_prepared",
            &id,
            json!({"protocol": protocol, "body": body}),
        )?;
        Ok(id)
    }
    async fn settle_request(&self, attempt_id: &str, status: ModelRequestStatus) -> CoreResult<()> {
        self.append(
            "model_request_settled",
            attempt_id,
            json!({"status": status}),
        )
    }
    fn cancel_request(&self, attempt_id: &str) {
        let _ = self.append(
            "model_request_settled",
            attempt_id,
            json!({"status": ModelRequestStatus::Cancelled}),
        );
    }
}

/// Replay reads an exact stored body; it never runs plugins or resolves a model.
pub(super) fn replay_prepared_model_request(
    store: &session_store::DesktopSessionStore,
    conversation_id: &str,
    message_id: &str,
    attempt_id: &str,
) -> Result<Option<Value>, String> {
    let count = store.timeline_count(conversation_id)?;
    Ok(store
        .timeline(conversation_id, count)?
        .into_iter()
        .find(|item| {
            item["type"] == "model_request_prepared"
                && item["message_id"] == message_id
                && item["data"]["attempt_id"] == attempt_id
                && item["data"]["schema_version"] == 1
                && item["data"]["format"] == "provider.http.json/v1"
        })
        .map(|item| item["data"]["request"].clone()))
}

#[cfg(test)]
#[path = "agent_boundary_v2_tests.rs"]
mod tests;
