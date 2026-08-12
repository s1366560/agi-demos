//! Structured Provider dispatch contract for durable Workspace Plan actions.

use async_trait::async_trait;
use serde_json::Value;
use thiserror::Error;

/// Event types exclusively owned by Plan runtime delivery before publication.
pub const WORKSPACE_PLAN_RUNTIME_EVENT_TYPES: [&str; 4] = [
    "operator_stale_attempt_recovery_requested",
    "operator_iteration_next_requested",
    "workspace_pipeline_run_requested",
    "delivery_contract_regeneration_requested",
];

/// Runtime actions emitted by the Plan authority outbox.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[non_exhaustive]
pub enum WorkspacePlanDispatchAction {
    RecoverStaleAttempts,
    TriggerNextIteration,
    RunPipeline,
    RegenerateDeliveryContract,
}

impl WorkspacePlanDispatchAction {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::RecoverStaleAttempts => "recover_stale_attempts",
            Self::TriggerNextIteration => "trigger_next_iteration",
            Self::RunPipeline => "run_pipeline",
            Self::RegenerateDeliveryContract => "regenerate_delivery_contract",
        }
    }
}

/// Immutable, correlated request delivered to the existing Agent Runtime Provider.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspacePlanDispatchRequest {
    tenant_id: String,
    project_id: String,
    workspace_id: String,
    plan_id: String,
    plan_node_id: Option<String>,
    task_id: Option<String>,
    attempt_id: Option<String>,
    agent_id: Option<String>,
    action: WorkspacePlanDispatchAction,
    outbox_id: String,
    correlation_id: String,
    conversation_id: String,
    payload: Value,
}

impl WorkspacePlanDispatchRequest {
    /// Construct one validated structured dispatch request.
    ///
    /// # Errors
    ///
    /// Returns [`WorkspacePlanDispatchContractError`] for blank identifiers,
    /// blank optional associations, or a non-object payload.
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        tenant_id: String,
        project_id: String,
        workspace_id: String,
        plan_id: String,
        plan_node_id: Option<String>,
        task_id: Option<String>,
        attempt_id: Option<String>,
        agent_id: Option<String>,
        action: WorkspacePlanDispatchAction,
        outbox_id: String,
        correlation_id: String,
        conversation_id: String,
        payload: Value,
    ) -> Result<Self, WorkspacePlanDispatchContractError> {
        for (field, value) in [
            ("tenant_id", tenant_id.as_str()),
            ("project_id", project_id.as_str()),
            ("workspace_id", workspace_id.as_str()),
            ("plan_id", plan_id.as_str()),
            ("outbox_id", outbox_id.as_str()),
            ("correlation_id", correlation_id.as_str()),
            ("conversation_id", conversation_id.as_str()),
        ] {
            if value.trim().is_empty() {
                return Err(WorkspacePlanDispatchContractError::BlankField { field });
            }
        }
        for (field, value) in [
            ("plan_node_id", plan_node_id.as_deref()),
            ("task_id", task_id.as_deref()),
            ("attempt_id", attempt_id.as_deref()),
            ("agent_id", agent_id.as_deref()),
        ] {
            if value.is_some_and(|value| value.trim().is_empty()) {
                return Err(WorkspacePlanDispatchContractError::BlankField { field });
            }
        }
        if !payload.is_object() {
            return Err(WorkspacePlanDispatchContractError::PayloadNotObject);
        }
        Ok(Self {
            tenant_id,
            project_id,
            workspace_id,
            plan_id,
            plan_node_id,
            task_id,
            attempt_id,
            agent_id,
            action,
            outbox_id,
            correlation_id,
            conversation_id,
            payload,
        })
    }

    #[must_use]
    pub fn tenant_id(&self) -> &str {
        &self.tenant_id
    }

    #[must_use]
    pub fn project_id(&self) -> &str {
        &self.project_id
    }

    #[must_use]
    pub fn workspace_id(&self) -> &str {
        &self.workspace_id
    }

    #[must_use]
    pub fn plan_id(&self) -> &str {
        &self.plan_id
    }

    #[must_use]
    pub fn plan_node_id(&self) -> Option<&str> {
        self.plan_node_id.as_deref()
    }

    #[must_use]
    pub fn task_id(&self) -> Option<&str> {
        self.task_id.as_deref()
    }

    #[must_use]
    pub fn attempt_id(&self) -> Option<&str> {
        self.attempt_id.as_deref()
    }

    #[must_use]
    pub fn agent_id(&self) -> Option<&str> {
        self.agent_id.as_deref()
    }

    #[must_use]
    pub const fn action(&self) -> WorkspacePlanDispatchAction {
        self.action
    }

    #[must_use]
    pub fn outbox_id(&self) -> &str {
        &self.outbox_id
    }

    #[must_use]
    pub fn correlation_id(&self) -> &str {
        &self.correlation_id
    }

    #[must_use]
    pub fn conversation_id(&self) -> &str {
        &self.conversation_id
    }

    #[must_use]
    pub const fn payload(&self) -> &Value {
        &self.payload
    }
}

/// Provider acceptance persisted before the outbox lease is completed.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspacePlanDispatchReceipt {
    provider_id: String,
    provider_bot_ref: String,
    provider_run_id: String,
}

impl WorkspacePlanDispatchReceipt {
    /// Construct a validated Provider acceptance receipt.
    ///
    /// # Errors
    ///
    /// Returns [`WorkspacePlanDispatchContractError`] when any Provider
    /// correlation field is blank.
    pub fn new(
        provider_id: String,
        provider_bot_ref: String,
        provider_run_id: String,
    ) -> Result<Self, WorkspacePlanDispatchContractError> {
        for (field, value) in [
            ("provider_id", provider_id.as_str()),
            ("provider_bot_ref", provider_bot_ref.as_str()),
            ("provider_run_id", provider_run_id.as_str()),
        ] {
            if value.trim().is_empty() {
                return Err(WorkspacePlanDispatchContractError::BlankField { field });
            }
        }
        Ok(Self {
            provider_id,
            provider_bot_ref,
            provider_run_id,
        })
    }

    #[must_use]
    pub fn provider_id(&self) -> &str {
        &self.provider_id
    }

    #[must_use]
    pub fn provider_bot_ref(&self) -> &str {
        &self.provider_bot_ref
    }

    #[must_use]
    pub fn provider_run_id(&self) -> &str {
        &self.provider_run_id
    }
}

/// Invalid structured dispatch request or acceptance receipt.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
#[non_exhaustive]
pub enum WorkspacePlanDispatchContractError {
    #[error("{field} must not be blank")]
    BlankField { field: &'static str },
    #[error("payload must be a JSON object")]
    PayloadNotObject,
}

/// Stable fail-closed Provider failure categories.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Error)]
#[non_exhaustive]
pub enum WorkspacePlanDispatchPortError {
    #[error("Workspace Plan Provider is unavailable")]
    Unavailable,
    #[error("Workspace Plan Provider rejected the dispatch")]
    Rejected,
}

impl WorkspacePlanDispatchPortError {
    #[must_use]
    pub const fn code(self) -> &'static str {
        match self {
            Self::Unavailable => "workspace_plan_provider_unavailable",
            Self::Rejected => "workspace_plan_provider_rejected",
        }
    }
}

/// External Agent Runtime boundary for structured Plan actions.
#[async_trait]
pub trait WorkspacePlanDispatchPort: Send + Sync + 'static {
    async fn dispatch(
        &self,
        request: &WorkspacePlanDispatchRequest,
    ) -> Result<WorkspacePlanDispatchReceipt, WorkspacePlanDispatchPortError>;
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;

    fn request() -> Result<WorkspacePlanDispatchRequest, WorkspacePlanDispatchContractError> {
        WorkspacePlanDispatchRequest::new(
            "tenant-1".to_string(),
            "project-1".to_string(),
            "workspace-1".to_string(),
            "plan-1".to_string(),
            Some("node-1".to_string()),
            Some("task-1".to_string()),
            Some("attempt-1".to_string()),
            Some("agent-1".to_string()),
            WorkspacePlanDispatchAction::RunPipeline,
            "outbox-1".to_string(),
            "correlation-1".to_string(),
            "conversation-1".to_string(),
            json!({"reason": "verify"}),
        )
    }

    #[test]
    fn structured_request_preserves_all_runtime_associations()
    -> Result<(), Box<dyn std::error::Error>> {
        let request = request()?;

        assert_eq!(request.tenant_id(), "tenant-1");
        assert_eq!(request.project_id(), "project-1");
        assert_eq!(request.workspace_id(), "workspace-1");
        assert_eq!(request.plan_id(), "plan-1");
        assert_eq!(request.plan_node_id(), Some("node-1"));
        assert_eq!(request.task_id(), Some("task-1"));
        assert_eq!(request.attempt_id(), Some("attempt-1"));
        assert_eq!(request.agent_id(), Some("agent-1"));
        assert_eq!(request.action().as_str(), "run_pipeline");
        assert_eq!(request.outbox_id(), "outbox-1");
        assert_eq!(request.correlation_id(), "correlation-1");
        assert_eq!(request.conversation_id(), "conversation-1");
        assert_eq!(request.payload()["reason"], "verify");
        Ok(())
    }

    #[test]
    fn request_and_receipt_reject_blank_or_unstructured_fields()
    -> Result<(), Box<dyn std::error::Error>> {
        let mut invalid = request()?;
        invalid.payload = json!([]);
        assert!(matches!(
            WorkspacePlanDispatchRequest::new(
                invalid.tenant_id,
                invalid.project_id,
                invalid.workspace_id,
                invalid.plan_id,
                invalid.plan_node_id,
                invalid.task_id,
                invalid.attempt_id,
                invalid.agent_id,
                invalid.action,
                invalid.outbox_id,
                invalid.correlation_id,
                invalid.conversation_id,
                invalid.payload,
            ),
            Err(WorkspacePlanDispatchContractError::PayloadNotObject)
        ));
        assert!(
            WorkspacePlanDispatchReceipt::new(
                "provider".to_string(),
                " ".to_string(),
                "run".to_string()
            )
            .is_err()
        );
        Ok(())
    }

    #[test]
    fn port_errors_expose_only_stable_codes() {
        assert_eq!(
            WorkspacePlanDispatchPortError::Unavailable.code(),
            "workspace_plan_provider_unavailable"
        );
        assert_eq!(
            WorkspacePlanDispatchPortError::Rejected.code(),
            "workspace_plan_provider_rejected"
        );
    }
}
