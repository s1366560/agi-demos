//! Request identity belongs to the authenticated message execution.
use std::sync::Arc;

use agistack_core::{
    agent::hitl_validation::{HitlValidationContext, HitlValidationPort},
    ports::{CoreError, CoreResult},
    HitlRequest, ReActEngine,
};
use async_trait::async_trait;

#[derive(Clone, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum MessageExecution {
    Run(String),
    Message(String),
}

#[derive(Clone)]
pub(super) struct MessageScope {
    pub user_id: String,
    pub tenant_id: String,
    pub project_id: String,
    pub conversation_id: String,
    pub execution: MessageExecution,
    pub native: Option<crate::computer_use_device_v2::NativeHumanRequestValidation>,
}

pub(super) fn bind_engine(engine: ReActEngine, scope: MessageScope) -> ReActEngine {
    engine.with_hitl_validation(Arc::new(scope))
}

#[async_trait]
impl HitlValidationPort for MessageScope {
    fn bind_request_id(
        &self,
        context: &HitlValidationContext<'_>,
        model_request_id: &str,
    ) -> CoreResult<String> {
        // The model's ID is always an untrusted label, including a copied host
        // prefix. Typed execution identity also separates run and message IDs.
        let binding = serde_json::to_vec(&(
            "rust-cloud-hitl-request-v1",
            &self.tenant_id,
            &self.project_id,
            &self.user_id,
            &self.conversation_id,
            &self.execution,
            context.session_id,
            context.round,
            model_request_id,
        ))
        .map_err(|error| CoreError::Storage(error.to_string()))?;
        Ok(format!(
            "cloud-hitl-{}",
            uuid::Uuid::new_v5(&uuid::Uuid::NAMESPACE_OID, &binding)
        ))
    }

    async fn validate(
        &self,
        context: &HitlValidationContext<'_>,
        request: &HitlRequest,
    ) -> CoreResult<()> {
        if let Some(native) = self.native.as_ref() {
            native.validate(context, request).await?;
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests;
