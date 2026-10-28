//! Core policy adapter bound to a previously resolved, trusted generation service.

use std::sync::Arc;

use agistack_core::{
    agent::{
        tool_policy::{
            ToolExecutionPolicy, ToolPolicyContext, ToolPolicyDecision, ToolPolicyResult,
        },
        types::{HitlKind, HitlRequest},
    },
    ports::{CoreError, CoreResult},
};
use async_trait::async_trait;
use serde_json::{json, Value};

use super::{
    tool_argument_validation::ToolArgumentValidator,
    tool_policy::{
        TrustedToolPolicyV2, TOOLS_BEFORE_EXECUTE_EVENT_V2, TOOLS_RESULT_TRANSFORM_EVENT_V2,
    },
    ScopeKindV2, ScopeV2,
};

/// Callers retain their generation lease for this adapter's entire lifetime.
pub struct GenerationToolExecutionPolicyV2 {
    service: Arc<TrustedToolPolicyV2>,
    scope: ScopeV2,
    operation_id: String,
    generation_digest: String,
    arguments: ToolArgumentValidator,
}

impl GenerationToolExecutionPolicyV2 {
    pub fn new(
        service: Arc<TrustedToolPolicyV2>,
        scope: ScopeV2,
        operation_id: String,
        generation_digest: String,
    ) -> Self {
        Self {
            service,
            scope,
            operation_id,
            generation_digest,
            arguments: ToolArgumentValidator::default(),
        }
    }

    fn identity(&self, context: &ToolPolicyContext<'_>) -> Value {
        json!({
            "tenant_id": self.scope.tenant_id,
            "project_id": self.scope.project_id,
            "session_id": self.scope.session_id.as_deref().unwrap_or(context.session_id),
            "operation_id": self.operation_id,
            "generation_digest": self.generation_digest,
            "tool_name": context.tool,
            "call_id": context.call_id(),
        })
    }

    async fn dispatch(
        &self,
        context: &ToolPolicyContext<'_>,
        event: &str,
        payload: Value,
    ) -> CoreResult<Value> {
        let mut scope = self.scope.clone();
        scope.kind = ScopeKindV2::Session;
        scope
            .session_id
            .get_or_insert_with(|| context.session_id.to_owned());
        self.service
            .dispatch(scope, event, payload)
            .await
            .map_err(|_| CoreError::Tool("trusted tool policy dispatch failed".into()))
    }
}

#[async_trait]
impl ToolExecutionPolicy for GenerationToolExecutionPolicyV2 {
    async fn execute_with_content(
        &self,
        context: &ToolPolicyContext<'_>,
        tools: &dyn agistack_core::ports::ToolHost,
        input_json: &str,
    ) -> CoreResult<agistack_core::ports::ToolResult> {
        tools.call_with_content(context.tool, input_json).await
    }

    async fn before_execute(
        &self,
        context: &ToolPolicyContext<'_>,
        input_json: &str,
        schema: Option<&Value>,
    ) -> CoreResult<ToolPolicyDecision> {
        let arguments: Value = serde_json::from_str(input_json)
            .map_err(|_| CoreError::Tool("tool arguments are invalid JSON".into()))?;
        let mut payload = self.identity(context);
        payload["arguments"] = arguments;
        payload["decision"] = json!({"kind": "allow"});
        let result = self
            .dispatch(context, TOOLS_BEFORE_EXECUTE_EVENT_V2, payload)
            .await?;
        let reason = result["decision"]["reason"]
            .as_str()
            .unwrap_or("Tool execution restricted by policy")
            .to_owned();
        match result["decision"]["kind"].as_str() {
            Some("allow") => {
                self.arguments
                    .validate(schema, &result["arguments"])
                    .await
                    .map_err(|_| {
                        CoreError::Tool("rewritten tool arguments violate input schema".into())
                    })?;
                Ok(ToolPolicyDecision::Allow {
                    input_json: result["arguments"].to_string(),
                })
            }
            Some("deny") => Ok(ToolPolicyDecision::Deny { reason }),
            Some("cancel") => Ok(ToolPolicyDecision::Cancel { reason }),
            Some("ask") => {
                let request: HitlRequest = serde_json::from_value(
                    result["decision"]["request"].clone(),
                )
                .map_err(|_| {
                    CoreError::Tool(
                        "tool policy ask requires a structured permission request".into(),
                    )
                })?;
                if request.kind != HitlKind::Permission
                    || request.id.trim().is_empty()
                    || request.prompt.trim().is_empty()
                    || !request.decision.as_ref().is_some_and(|decision| {
                        decision.is_complete() && decision.action.name == context.tool
                    })
                {
                    return Err(CoreError::Tool(
                        "tool policy permission request is incomplete or targets another tool"
                            .into(),
                    ));
                }
                Ok(ToolPolicyDecision::Ask { request })
            }
            _ => Err(CoreError::Tool("invalid tool policy decision".into())),
        }
    }

    async fn transform_result(
        &self,
        context: &ToolPolicyContext<'_>,
        result: ToolPolicyResult,
    ) -> CoreResult<ToolPolicyResult> {
        let original_output = result.output.clone();
        let media = result.media;
        let mut payload = self.identity(context);
        payload["result"] = json!({"output": result.output, "is_error": result.is_error, "metadata": result.metadata});
        payload["decision"] = json!({"kind": "accept"});
        let result = self
            .dispatch(context, TOOLS_RESULT_TRANSFORM_EVENT_V2, payload)
            .await?;
        if result["decision"]["kind"].as_str() == Some("block") {
            return Ok(ToolPolicyResult {
                output: "Tool result withheld by policy".into(),
                is_error: true,
                metadata: json!({"blocked": true}),
                media: Vec::new(),
            });
        }
        Ok(ToolPolicyResult {
            output: result["result"]["output"]
                .as_str()
                .ok_or_else(|| CoreError::Tool("invalid transformed tool output".into()))?
                .to_owned(),
            is_error: result["result"]["is_error"]
                .as_bool()
                .ok_or_else(|| CoreError::Tool("invalid transformed tool error flag".into()))?,
            metadata: result["result"]["metadata"].clone(),
            // This transform contract can rewrite text, but cannot transform images.
            // Only the unchanged accepted result retains its owned attachments.
            media: if result["result"]["output"].as_str() == Some(&original_output)
                && result["result"]["is_error"].as_bool() == Some(false)
            {
                media
            } else {
                Vec::new()
            },
        })
    }
}
