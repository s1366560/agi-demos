//! Legacy Workspace event compatibility mapping.

use memstack_workspace_service_api::WorkspaceMutationAction;
use serde_json::Value;
use thiserror::Error;

/// Invalid legacy event data supplied to the transaction planner.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
#[non_exhaustive]
pub enum LegacyWorkspaceEventError {
    #[error("legacy Workspace event payload must be a JSON object")]
    PayloadNotObject,

    #[error("legacy Workspace event payload workspace_id does not match the command scope")]
    WorkspaceMismatch,

    #[error("legacy Workspace agent-bound event payload requires is_update={expected}")]
    AgentUpdateFlag { expected: bool },

    #[error("legacy Workspace agent-bound event payload requires a boolean is_update field")]
    AgentUpdateFlagMissing,
}

/// One durable event in the existing Workspace event vocabulary.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LegacyWorkspaceEvent {
    event_type: &'static str,
    payload: Value,
}

impl LegacyWorkspaceEvent {
    /// Validate and map a Wave A action to its legacy event contract.
    ///
    /// Create Workspace intentionally maps to the single owner
    /// `workspace_member_joined` event emitted by the legacy service.
    ///
    /// # Errors
    ///
    /// Returns [`LegacyWorkspaceEventError`] when the payload is not an object,
    /// targets another Workspace, or carries an invalid agent update flag.
    pub fn for_action(
        action: WorkspaceMutationAction,
        workspace_id: &str,
        payload: Value,
    ) -> Result<Self, LegacyWorkspaceEventError> {
        let Some(object) = payload.as_object() else {
            return Err(LegacyWorkspaceEventError::PayloadNotObject);
        };
        if object.get("workspace_id").and_then(Value::as_str) != Some(workspace_id) {
            return Err(LegacyWorkspaceEventError::WorkspaceMismatch);
        }

        let event_type = match action {
            WorkspaceMutationAction::CreateWorkspace | WorkspaceMutationAction::AddMember => {
                "workspace_member_joined"
            }
            WorkspaceMutationAction::UpdateWorkspace => "workspace_updated",
            WorkspaceMutationAction::DeleteWorkspace => "workspace_deleted",
            WorkspaceMutationAction::UpdateMemberRole => "workspace_member_updated",
            WorkspaceMutationAction::RemoveMember => "workspace_member_left",
            WorkspaceMutationAction::BindAgent => {
                require_agent_update_flag_present(object.get("is_update"))?;
                "workspace_agent_bound"
            }
            WorkspaceMutationAction::UpdateAgentBinding => {
                require_agent_update_flag(object.get("is_update"), true)?;
                "workspace_agent_bound"
            }
            WorkspaceMutationAction::UnbindAgent => "workspace_agent_unbound",
            WorkspaceMutationAction::UpdateAgentPolicy => "workspace_agent_policy_updated",
        };

        Ok(Self {
            event_type,
            payload,
        })
    }

    /// Legacy event type persisted in the durable outbox.
    #[must_use]
    pub const fn event_type(&self) -> &'static str {
        self.event_type
    }

    /// Validated legacy payload persisted in the durable outbox.
    #[must_use]
    pub const fn payload(&self) -> &Value {
        &self.payload
    }
}

fn require_agent_update_flag(
    value: Option<&Value>,
    expected: bool,
) -> Result<(), LegacyWorkspaceEventError> {
    if value.and_then(Value::as_bool) == Some(expected) {
        Ok(())
    } else {
        Err(LegacyWorkspaceEventError::AgentUpdateFlag { expected })
    }
}

fn require_agent_update_flag_present(
    value: Option<&Value>,
) -> Result<(), LegacyWorkspaceEventError> {
    if value.is_some_and(Value::is_boolean) {
        Ok(())
    } else {
        Err(LegacyWorkspaceEventError::AgentUpdateFlagMissing)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn wave_a_actions_preserve_legacy_event_names() -> Result<(), LegacyWorkspaceEventError> {
        let cases = [
            (
                WorkspaceMutationAction::CreateWorkspace,
                "workspace_member_joined",
                None,
            ),
            (
                WorkspaceMutationAction::UpdateWorkspace,
                "workspace_updated",
                None,
            ),
            (
                WorkspaceMutationAction::DeleteWorkspace,
                "workspace_deleted",
                None,
            ),
            (
                WorkspaceMutationAction::AddMember,
                "workspace_member_joined",
                None,
            ),
            (
                WorkspaceMutationAction::UpdateMemberRole,
                "workspace_member_updated",
                None,
            ),
            (
                WorkspaceMutationAction::RemoveMember,
                "workspace_member_left",
                None,
            ),
            (
                WorkspaceMutationAction::BindAgent,
                "workspace_agent_bound",
                Some(false),
            ),
            (
                WorkspaceMutationAction::UpdateAgentBinding,
                "workspace_agent_bound",
                Some(true),
            ),
            (
                WorkspaceMutationAction::UnbindAgent,
                "workspace_agent_unbound",
                None,
            ),
            (
                WorkspaceMutationAction::UpdateAgentPolicy,
                "workspace_agent_policy_updated",
                None,
            ),
        ];

        for (action, expected_type, update_flag) in cases {
            let mut payload = json!({"workspace_id": "workspace-1"});
            if let Some(flag) = update_flag {
                payload["is_update"] = Value::Bool(flag);
            }
            let event = LegacyWorkspaceEvent::for_action(action, "workspace-1", payload)?;
            assert_eq!(event.event_type(), expected_type);
        }
        Ok(())
    }

    #[test]
    fn agent_bound_events_require_the_structured_update_flag() {
        let error = LegacyWorkspaceEvent::for_action(
            WorkspaceMutationAction::UpdateAgentBinding,
            "workspace-1",
            json!({"workspace_id": "workspace-1", "is_update": false}),
        );

        assert_eq!(
            error,
            Err(LegacyWorkspaceEventError::AgentUpdateFlag { expected: true })
        );
    }

    #[test]
    fn bind_agent_accepts_structured_create_and_update_flags()
    -> Result<(), LegacyWorkspaceEventError> {
        for is_update in [false, true] {
            let event = LegacyWorkspaceEvent::for_action(
                WorkspaceMutationAction::BindAgent,
                "workspace-1",
                json!({"workspace_id": "workspace-1", "is_update": is_update}),
            )?;
            assert_eq!(event.event_type(), "workspace_agent_bound");
        }
        Ok(())
    }
}
