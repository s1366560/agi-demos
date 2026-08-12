//! Structured external Agent Registry validation contract.

use async_trait::async_trait;
use thiserror::Error;

use crate::{AgentId, ProjectId, TenantId, WorkspaceCommandError};

const AGENT_NAME_MAX_CHARS: usize = 1024;

/// Scoped lookup sent to the external Agent Registry authority.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AgentRegistryLookup {
    tenant_id: TenantId,
    project_id: ProjectId,
    agent_id: AgentId,
}

impl AgentRegistryLookup {
    #[must_use]
    pub const fn new(tenant_id: TenantId, project_id: ProjectId, agent_id: AgentId) -> Self {
        Self {
            tenant_id,
            project_id,
            agent_id,
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
    pub const fn agent_id(&self) -> &AgentId {
        &self.agent_id
    }
}

/// Agent metadata required to create or update the corresponding BCS Bot.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AgentRegistryAgent {
    agent_id: AgentId,
    name: String,
    display_name: Option<String>,
    enabled: bool,
}

impl AgentRegistryAgent {
    /// Parse one registry response into a bounded, scope-independent record.
    ///
    /// # Errors
    ///
    /// Returns [`WorkspaceCommandError`] when the identifier or names cannot
    /// be represented by the BCS Bot schema.
    pub fn parse(
        agent_id: impl Into<String>,
        name: impl Into<String>,
        display_name: Option<String>,
        enabled: bool,
    ) -> Result<Self, WorkspaceCommandError> {
        let name = bounded_name(name.into(), "agent_name")?;
        let display_name = display_name
            .map(|value| bounded_name(value, "agent_display_name"))
            .transpose()?;
        Ok(Self {
            agent_id: AgentId::parse(agent_id)?,
            name,
            display_name,
            enabled,
        })
    }

    #[must_use]
    pub const fn agent_id(&self) -> &AgentId {
        &self.agent_id
    }

    #[must_use]
    pub fn name(&self) -> &str {
        &self.name
    }

    #[must_use]
    pub fn display_name(&self) -> Option<&str> {
        self.display_name.as_deref()
    }

    #[must_use]
    pub const fn enabled(&self) -> bool {
        self.enabled
    }
}

/// External Agent Registry transport failure.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Error)]
#[non_exhaustive]
pub enum AgentRegistryPortError {
    #[error("Agent Registry is unavailable")]
    Unavailable,
}

/// Authority port used before any Workspace Agent roster mutation is planned.
#[async_trait]
pub trait AgentRegistryPort: Send + Sync {
    /// Resolve an Agent that is visible in the requested tenant/project scope.
    ///
    /// # Errors
    ///
    /// Returns [`AgentRegistryPortError`] when the external authority cannot
    /// produce a trusted structured answer. `Ok(None)` means the Agent is not
    /// available in the requested scope.
    async fn resolve(
        &self,
        lookup: &AgentRegistryLookup,
    ) -> Result<Option<AgentRegistryAgent>, AgentRegistryPortError>;
}

fn bounded_name(value: String, field: &'static str) -> Result<String, WorkspaceCommandError> {
    if value.trim().is_empty() {
        return Err(WorkspaceCommandError::Blank { field });
    }
    let actual_chars = value.chars().count();
    if actual_chars > AGENT_NAME_MAX_CHARS {
        return Err(WorkspaceCommandError::TooLong {
            field,
            max_chars: AGENT_NAME_MAX_CHARS,
            actual_chars,
        });
    }
    Ok(value)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn registry_agent_rejects_blank_and_oversized_names() {
        assert!(matches!(
            AgentRegistryAgent::parse("agent-1", " ", None, true),
            Err(WorkspaceCommandError::Blank {
                field: "agent_name"
            })
        ));
        assert!(matches!(
            AgentRegistryAgent::parse("agent-1", "n".repeat(AGENT_NAME_MAX_CHARS + 1), None, true,),
            Err(WorkspaceCommandError::TooLong {
                field: "agent_name",
                ..
            })
        ));
    }
}
