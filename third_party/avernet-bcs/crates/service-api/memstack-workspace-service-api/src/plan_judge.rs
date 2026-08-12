//! Structured Agent authority for subjective Workspace Plan decisions.

use async_trait::async_trait;
use serde_json::Value;
use thiserror::Error;

/// Semantic Plan decisions that must not be inferred from text or metadata heuristics.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[non_exhaustive]
pub enum WorkspacePlanJudgmentKind {
    RecoverStaleAttempts,
    TriggerNextIteration,
    SelectPipelineTarget,
    RegenerateDeliveryContract,
    RequestNodeReplan,
    AcceptNodeReview,
}

impl WorkspacePlanJudgmentKind {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::RecoverStaleAttempts => "recover_stale_attempts",
            Self::TriggerNextIteration => "trigger_next_iteration",
            Self::SelectPipelineTarget => "select_pipeline_target",
            Self::RegenerateDeliveryContract => "regenerate_delivery_contract",
            Self::RequestNodeReplan => "request_node_replan",
            Self::AcceptNodeReview => "accept_node_review",
        }
    }

    #[must_use]
    pub const fn requires_selected_node(self) -> bool {
        matches!(self, Self::SelectPipelineTarget)
    }
}

/// Validated evidence passed to the external Agent as a structured tool-call payload.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspacePlanJudgmentRequest {
    tenant_id: String,
    project_id: String,
    workspace_id: String,
    actor_id: String,
    plan_id: String,
    plan_revision: u64,
    kind: WorkspacePlanJudgmentKind,
    candidate_node_ids: Vec<String>,
    evidence: Value,
}

impl WorkspacePlanJudgmentRequest {
    /// Construct one bounded judgment request without assigning semantic meaning locally.
    ///
    /// # Errors
    ///
    /// Returns [`WorkspacePlanJudgeContractError`] when required identifiers are blank,
    /// candidates are duplicated, selection has no candidates, or evidence is not an object.
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        tenant_id: String,
        project_id: String,
        workspace_id: String,
        actor_id: String,
        plan_id: String,
        plan_revision: u64,
        kind: WorkspacePlanJudgmentKind,
        candidate_node_ids: Vec<String>,
        evidence: Value,
    ) -> Result<Self, WorkspacePlanJudgeContractError> {
        for (field, value) in [
            ("tenant_id", tenant_id.as_str()),
            ("project_id", project_id.as_str()),
            ("workspace_id", workspace_id.as_str()),
            ("actor_id", actor_id.as_str()),
            ("plan_id", plan_id.as_str()),
        ] {
            if value.trim().is_empty() {
                return Err(WorkspacePlanJudgeContractError::BlankField { field });
            }
        }
        if !evidence.is_object() {
            return Err(WorkspacePlanJudgeContractError::EvidenceNotObject);
        }
        if candidate_node_ids
            .iter()
            .any(|node_id| node_id.trim().is_empty())
        {
            return Err(WorkspacePlanJudgeContractError::BlankField {
                field: "candidate_node_id",
            });
        }
        let mut unique = candidate_node_ids.clone();
        unique.sort();
        unique.dedup();
        if unique.len() != candidate_node_ids.len() {
            return Err(WorkspacePlanJudgeContractError::DuplicateCandidate);
        }
        if kind.requires_selected_node() && candidate_node_ids.is_empty() {
            return Err(WorkspacePlanJudgeContractError::MissingCandidate);
        }
        Ok(Self {
            tenant_id,
            project_id,
            workspace_id,
            actor_id,
            plan_id,
            plan_revision,
            kind,
            candidate_node_ids,
            evidence,
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
    pub fn actor_id(&self) -> &str {
        &self.actor_id
    }

    #[must_use]
    pub fn plan_id(&self) -> &str {
        &self.plan_id
    }

    #[must_use]
    pub const fn plan_revision(&self) -> u64 {
        self.plan_revision
    }

    #[must_use]
    pub const fn kind(&self) -> WorkspacePlanJudgmentKind {
        self.kind
    }

    #[must_use]
    pub fn candidate_node_ids(&self) -> &[String] {
        &self.candidate_node_ids
    }

    #[must_use]
    pub const fn evidence(&self) -> &Value {
        &self.evidence
    }
}

/// Auditable structured verdict returned by the configured Agent authority.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspacePlanJudgment {
    proceed: bool,
    selected_node_id: Option<String>,
    rationale: String,
    agent_id: String,
    tool_name: String,
    input: Value,
    output: Value,
    latency_ms: u64,
}

impl WorkspacePlanJudgment {
    /// Validate the Agent verdict against the exact request candidate set.
    ///
    /// # Errors
    ///
    /// Returns [`WorkspacePlanJudgeContractError`] for blank audit fields, a selected
    /// node outside the request, or a proceeding selection verdict without a node.
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        request: &WorkspacePlanJudgmentRequest,
        proceed: bool,
        selected_node_id: Option<String>,
        rationale: String,
        agent_id: String,
        tool_name: String,
        input: Value,
        output: Value,
        latency_ms: u64,
    ) -> Result<Self, WorkspacePlanJudgeContractError> {
        for (field, value) in [
            ("rationale", rationale.as_str()),
            ("agent_id", agent_id.as_str()),
            ("tool_name", tool_name.as_str()),
        ] {
            if value.trim().is_empty() {
                return Err(WorkspacePlanJudgeContractError::BlankField { field });
            }
        }
        if let Some(node_id) = selected_node_id.as_deref()
            && !request
                .candidate_node_ids()
                .iter()
                .any(|candidate| candidate == node_id)
        {
            return Err(WorkspacePlanJudgeContractError::InvalidSelection);
        }
        if proceed && request.kind().requires_selected_node() && selected_node_id.is_none() {
            return Err(WorkspacePlanJudgeContractError::MissingSelection);
        }
        Ok(Self {
            proceed,
            selected_node_id,
            rationale,
            agent_id,
            tool_name,
            input,
            output,
            latency_ms,
        })
    }

    #[must_use]
    pub const fn proceed(&self) -> bool {
        self.proceed
    }

    #[must_use]
    pub fn selected_node_id(&self) -> Option<&str> {
        self.selected_node_id.as_deref()
    }

    #[must_use]
    pub fn rationale(&self) -> &str {
        &self.rationale
    }

    #[must_use]
    pub fn agent_id(&self) -> &str {
        &self.agent_id
    }

    #[must_use]
    pub fn tool_name(&self) -> &str {
        &self.tool_name
    }

    #[must_use]
    pub const fn input(&self) -> &Value {
        &self.input
    }

    #[must_use]
    pub const fn output(&self) -> &Value {
        &self.output
    }

    #[must_use]
    pub const fn latency_ms(&self) -> u64 {
        self.latency_ms
    }
}

/// Invalid or unavailable structured Plan judgment.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
#[non_exhaustive]
pub enum WorkspacePlanJudgeContractError {
    #[error("Workspace Plan judgment {field} must not be blank")]
    BlankField { field: &'static str },

    #[error("Workspace Plan judgment evidence must be an object")]
    EvidenceNotObject,

    #[error("Workspace Plan judgment candidates must be unique")]
    DuplicateCandidate,

    #[error("Workspace Plan judgment requires at least one candidate")]
    MissingCandidate,

    #[error("Workspace Plan judgment selected a node outside the supplied candidates")]
    InvalidSelection,

    #[error("Workspace Plan judgment omitted its required selected node")]
    MissingSelection,
}

/// External Plan Judge transport failure.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Error)]
#[non_exhaustive]
pub enum WorkspacePlanJudgePortError {
    #[error("Workspace Plan judge is unavailable")]
    Unavailable,
}

/// Agent-first boundary for semantic Plan verdicts and ambiguous node selection.
#[async_trait]
pub trait WorkspacePlanJudgePort: Send + Sync {
    /// Return one validated structured verdict.
    ///
    /// # Errors
    ///
    /// Returns [`WorkspacePlanJudgePortError`] when no authenticated verdict is available.
    async fn judge(
        &self,
        request: &WorkspacePlanJudgmentRequest,
    ) -> Result<WorkspacePlanJudgment, WorkspacePlanJudgePortError>;
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;

    fn request() -> Result<WorkspacePlanJudgmentRequest, WorkspacePlanJudgeContractError> {
        WorkspacePlanJudgmentRequest::new(
            "tenant-1".to_string(),
            "project-1".to_string(),
            "workspace-1".to_string(),
            "user-1".to_string(),
            "plan-1".to_string(),
            3,
            WorkspacePlanJudgmentKind::SelectPipelineTarget,
            vec!["node-1".to_string(), "node-2".to_string()],
            json!({"nodes": []}),
        )
    }

    #[test]
    fn selection_must_be_an_exact_request_candidate() -> Result<(), Box<dyn std::error::Error>> {
        let request = request()?;
        let result = WorkspacePlanJudgment::new(
            &request,
            true,
            Some("outside".to_string()),
            "structured rationale".to_string(),
            "judge-agent".to_string(),
            "judge_workspace_plan".to_string(),
            json!({}),
            json!({}),
            5,
        );
        assert_eq!(
            result,
            Err(WorkspacePlanJudgeContractError::InvalidSelection)
        );
        Ok(())
    }

    #[test]
    fn proceeding_pipeline_selection_requires_selected_node()
    -> Result<(), Box<dyn std::error::Error>> {
        let request = request()?;
        let result = WorkspacePlanJudgment::new(
            &request,
            true,
            None,
            "structured rationale".to_string(),
            "judge-agent".to_string(),
            "judge_workspace_plan".to_string(),
            json!({}),
            json!({}),
            5,
        );
        assert_eq!(
            result,
            Err(WorkspacePlanJudgeContractError::MissingSelection)
        );
        Ok(())
    }
}
