//! Structured external Agent judgment contract for ambiguous Workspace Context selection.

use std::collections::HashSet;

use async_trait::async_trait;
use serde_json::Value;
use thiserror::Error;

use crate::{MembershipRole, ProjectId, TenantId, UserId, WorkspaceCommandError};

/// One active Project membership eligible for Context selection.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceContextCandidate {
    tenant_id: TenantId,
    project_id: ProjectId,
    membership_role: MembershipRole,
}

impl WorkspaceContextCandidate {
    /// Parse bounded membership fields supplied by the Workspace store.
    ///
    /// # Errors
    ///
    /// Returns [`WorkspaceCommandError`] when an identifier or role is blank
    /// or exceeds its persisted width.
    pub fn parse(
        tenant_id: impl Into<String>,
        project_id: impl Into<String>,
        membership_role: impl Into<String>,
    ) -> Result<Self, WorkspaceCommandError> {
        Ok(Self {
            tenant_id: TenantId::parse(tenant_id)?,
            project_id: ProjectId::parse(project_id)?,
            membership_role: MembershipRole::parse(membership_role)?,
        })
    }

    #[must_use]
    pub const fn tenant_id(&self) -> &TenantId {
        &self.tenant_id
    }

    #[must_use]
    pub const fn project_id(&self) -> &ProjectId {
        &self.project_id
    }

    #[must_use]
    pub const fn membership_role(&self) -> &MembershipRole {
        &self.membership_role
    }
}

/// Existing Context supplied only as structured continuity evidence.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceContextCurrent {
    tenant_id: TenantId,
    project_id: ProjectId,
    revision: u64,
}

impl WorkspaceContextCurrent {
    #[must_use]
    pub const fn new(tenant_id: TenantId, project_id: ProjectId, revision: u64) -> Self {
        Self {
            tenant_id,
            project_id,
            revision,
        }
    }

    #[must_use]
    pub const fn tenant_id(&self) -> &TenantId {
        &self.tenant_id
    }

    #[must_use]
    pub const fn project_id(&self) -> &ProjectId {
        &self.project_id
    }

    #[must_use]
    pub const fn revision(&self) -> u64 {
        self.revision
    }
}

/// Invalid structured Context judgment contract.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum WorkspaceContextJudgeContractError {
    #[error(transparent)]
    Command(#[from] WorkspaceCommandError),

    #[error("ambiguous Workspace Context judgment requires at least two candidates")]
    TooFewCandidates,

    #[error("Workspace Context candidates must be unique")]
    DuplicateCandidate,

    #[error("Workspace Context judgment selected a candidate outside the supplied set")]
    InvalidSelection,

    #[error("Workspace Context judgment {field} must not be blank")]
    BlankJudgmentField { field: &'static str },
}

/// Complete normalized evidence for one ambiguous Context decision.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceContextJudgmentRequest {
    user_id: UserId,
    current: Option<WorkspaceContextCurrent>,
    candidates: Vec<WorkspaceContextCandidate>,
}

impl WorkspaceContextJudgmentRequest {
    /// Construct a judgment request with a unique ambiguous candidate set.
    ///
    /// # Errors
    ///
    /// Returns [`WorkspaceContextJudgeContractError`] unless at least two
    /// unique tenant/Project scopes are supplied.
    pub fn new(
        user_id: UserId,
        current: Option<WorkspaceContextCurrent>,
        candidates: Vec<WorkspaceContextCandidate>,
    ) -> Result<Self, WorkspaceContextJudgeContractError> {
        if candidates.len() < 2 {
            return Err(WorkspaceContextJudgeContractError::TooFewCandidates);
        }
        let unique_scopes = candidates
            .iter()
            .map(|candidate| {
                (
                    candidate.tenant_id().as_str(),
                    candidate.project_id().as_str(),
                )
            })
            .collect::<HashSet<_>>();
        if unique_scopes.len() != candidates.len() {
            return Err(WorkspaceContextJudgeContractError::DuplicateCandidate);
        }
        Ok(Self {
            user_id,
            current,
            candidates,
        })
    }

    #[must_use]
    pub const fn user_id(&self) -> &UserId {
        &self.user_id
    }

    #[must_use]
    pub const fn current(&self) -> Option<&WorkspaceContextCurrent> {
        self.current.as_ref()
    }

    #[must_use]
    pub fn candidates(&self) -> &[WorkspaceContextCandidate] {
        &self.candidates
    }
}

/// Auditable structured tool-call verdict returned by the Agent authority.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspaceContextJudgment {
    selected_index: usize,
    selected: WorkspaceContextCandidate,
    rationale: String,
    evidence: Vec<String>,
    agent_id: String,
    tool_name: String,
    input: Value,
    output: Value,
    latency_ms: u64,
}

impl WorkspaceContextJudgment {
    /// Construct and revalidate a structured verdict against the supplied set.
    ///
    /// # Errors
    ///
    /// Returns [`WorkspaceContextJudgeContractError`] when the selected index
    /// or candidate is not an exact member of the request, or required audit
    /// fields are blank.
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        request: &WorkspaceContextJudgmentRequest,
        selected_index: usize,
        selected: WorkspaceContextCandidate,
        rationale: String,
        evidence: Vec<String>,
        agent_id: String,
        tool_name: String,
        input: Value,
        output: Value,
        latency_ms: u64,
    ) -> Result<Self, WorkspaceContextJudgeContractError> {
        if request.candidates().get(selected_index) != Some(&selected) {
            return Err(WorkspaceContextJudgeContractError::InvalidSelection);
        }
        for (field, value) in [
            ("rationale", rationale.as_str()),
            ("agent_id", agent_id.as_str()),
            ("tool_name", tool_name.as_str()),
        ] {
            if value.trim().is_empty() {
                return Err(WorkspaceContextJudgeContractError::BlankJudgmentField { field });
            }
        }
        Ok(Self {
            selected_index,
            selected,
            rationale,
            evidence,
            agent_id,
            tool_name,
            input,
            output,
            latency_ms,
        })
    }

    #[must_use]
    pub const fn selected_index(&self) -> usize {
        self.selected_index
    }

    #[must_use]
    pub const fn selected(&self) -> &WorkspaceContextCandidate {
        &self.selected
    }

    #[must_use]
    pub fn rationale(&self) -> &str {
        &self.rationale
    }

    #[must_use]
    pub fn evidence(&self) -> &[String] {
        &self.evidence
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

/// External Context Judge transport or validation failure.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Error)]
#[non_exhaustive]
pub enum WorkspaceContextJudgePortError {
    #[error("Workspace Context judge is unavailable")]
    Unavailable,
}

/// Agent-first authority used only when more than one membership is eligible.
#[async_trait]
pub trait WorkspaceContextJudgePort: Send + Sync {
    /// Select exactly one candidate through a structured tool call.
    ///
    /// # Errors
    ///
    /// Returns [`WorkspaceContextJudgePortError`] when the authority cannot
    /// provide a validated structured verdict.
    async fn select(
        &self,
        request: &WorkspaceContextJudgmentRequest,
    ) -> Result<WorkspaceContextJudgment, WorkspaceContextJudgePortError>;
}

#[cfg(test)]
mod tests {
    use std::error::Error;

    use super::*;

    fn candidates() -> Result<Vec<WorkspaceContextCandidate>, WorkspaceCommandError> {
        Ok(vec![
            WorkspaceContextCandidate::parse("tenant-1", "project-1", "member")?,
            WorkspaceContextCandidate::parse("tenant-2", "project-2", "owner")?,
        ])
    }

    #[test]
    fn judgment_rejects_a_selected_candidate_outside_the_request() -> Result<(), Box<dyn Error>> {
        let request =
            WorkspaceContextJudgmentRequest::new(UserId::parse("user-1")?, None, candidates()?)?;
        let result = WorkspaceContextJudgment::new(
            &request,
            0,
            WorkspaceContextCandidate::parse("tenant-3", "project-3", "viewer")?,
            "structured rationale".to_string(),
            Vec::new(),
            "judge-agent".to_string(),
            "select_workspace_context".to_string(),
            Value::Object(Default::default()),
            Value::Object(Default::default()),
            1,
        );

        assert!(matches!(
            result,
            Err(WorkspaceContextJudgeContractError::InvalidSelection)
        ));
        Ok(())
    }

    #[test]
    fn judgment_request_rejects_duplicate_scopes() -> Result<(), Box<dyn Error>> {
        let candidate = WorkspaceContextCandidate::parse("tenant-1", "project-1", "member")?;
        let result = WorkspaceContextJudgmentRequest::new(
            UserId::parse("user-1")?,
            None,
            vec![candidate.clone(), candidate],
        );

        assert!(matches!(
            result,
            Err(WorkspaceContextJudgeContractError::DuplicateCandidate)
        ));
        Ok(())
    }
}
