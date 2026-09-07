//! Exact-invocation permission records. These records never authorize dispatch.
//!
//! Host bindings deliberately do not implement `Deserialize`: an agent or HTTP
//! payload cannot supply an attestation. Trusted host code must resolve the tool
//! and hash the input. Durable plugin generation fencing is a separate boundary.

use serde::{Deserialize, Serialize};

/// Ephemeral guidance advertised only by a host with the suspension port installed.
pub(crate) const PERMISSION_SUSPENSION_GUIDANCE: &str = "[Host decision capability] \
This host supports atomic tool-invocation permission suspension. For an exact tool-invocation \
permission, include request.permission_invocation as {\"tool\":string,\"input\":object}; tool must \
equal decision.action.name and input must contain the exact proposed arguments. This field is \
valid only for permission. Do not supply host identity, invocation IDs, versions, or grants.";

pub(crate) fn decision_goal<'a>(
    goal: &'a str,
    port: &Option<std::sync::Arc<dyn PermissionSuspensionPort>>,
) -> std::borrow::Cow<'a, str> {
    // The live host port is the authority; no saved flag or user-text inference.
    if port.is_some() {
        std::borrow::Cow::Owned(format!("{goal}\n\n{PERMISSION_SUSPENSION_GUIDANCE}"))
    } else {
        std::borrow::Cow::Borrowed(goal)
    }
}

pub(crate) fn reject_ordinary_resume(state: &crate::SessionState) -> crate::CoreResult<()> {
    if state
        .pending_hitl
        .as_ref()
        .is_some_and(|r| r.permission_invocation.is_some())
    {
        return Err(crate::CoreError::Tool(
            "bound permission requires its dedicated answer boundary".into(),
        ));
    }
    Ok(())
}

pub(crate) fn validate_proposal(
    state: &crate::SessionState,
    request: &crate::HitlRequest,
) -> crate::CoreResult<()> {
    let valid = request
        .permission_invocation
        .as_ref()
        .is_some_and(|proposal| {
            request.kind == crate::HitlKind::Permission
                && !proposal.tool.trim().is_empty()
                && !request.id.trim().is_empty()
                && !request.prompt.trim().is_empty()
                && request
                    .decision
                    .as_ref()
                    .is_some_and(|d| d.is_complete() && d.action.name == proposal.tool)
                && state.hitl_answer(&request.id).is_none()
        });
    if !valid {
        return Err(crate::CoreError::Tool(
            "invalid bound permission proposal".into(),
        ));
    }
    Ok(())
}

/// Agent-proposed execution payload. This carries no host attestation or grant.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PermissionInvocationProposal {
    pub tool: String,
    pub input: serde_json::Value,
}

/// Atomically persists the exact post-decision checkpoint, request and intent,
/// and parks the run under its current host-owned execution authority.
/// Successful suspension never authorizes or dispatches the proposed tool.
#[async_trait::async_trait]
pub trait PermissionSuspensionPort: Send + Sync {
    async fn suspend(&self, state: &crate::SessionState) -> crate::CoreResult<()>;
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PermissionAnswer {
    AllowOnce,
    Deny,
}

impl PermissionAnswer {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::AllowOnce => "allow_once",
            Self::Deny => "deny",
        }
    }
}

/// A host-observed invocation identity, not a grant or a durable generation proof.
///
/// ```compile_fail
/// use agistack_core::automation_permission::HostPermissionBinding;
/// let _: HostPermissionBinding = serde_json::from_str("{}").unwrap();
/// ```
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct HostPermissionBinding {
    invocation_id: String,
    tool_name: String,
    tool_version: String,
    input_sha256: String,
}

impl HostPermissionBinding {
    /// For trusted host adapters only. Never populate these arguments from an
    /// agent's decision context or deserialize an equivalent wire structure.
    pub fn from_host_observation(
        invocation_id: String,
        tool_name: String,
        tool_version: String,
        input_sha256: String,
    ) -> Option<Self> {
        if [&invocation_id, &tool_name, &tool_version]
            .iter()
            .any(|value| value.trim().is_empty())
            || input_sha256.len() != 64
            || !input_sha256.bytes().all(|value| value.is_ascii_hexdigit())
        {
            return None;
        }
        Some(Self {
            invocation_id,
            tool_name,
            tool_version,
            input_sha256,
        })
    }

    pub fn invocation_id(&self) -> &str {
        &self.invocation_id
    }
    pub fn tool_name(&self) -> &str {
        &self.tool_name
    }
    pub fn tool_version(&self) -> &str {
        &self.tool_version
    }
    pub fn input_sha256(&self) -> &str {
        &self.input_sha256
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_once_or_deny_are_protocol_answers() {
        assert_eq!(
            serde_json::from_str::<PermissionAnswer>("\"allow_once\"").unwrap(),
            PermissionAnswer::AllowOnce
        );
        for value in ["allow", "always", "true"] {
            assert!(serde_json::from_value::<PermissionAnswer>(serde_json::json!(value)).is_err());
        }
    }

    #[test]
    fn missing_host_identity_or_input_digest_is_rejected() {
        assert!(HostPermissionBinding::from_host_observation(
            "id".into(),
            "tool".into(),
            "".into(),
            "a".repeat(64)
        )
        .is_none());
        assert!(HostPermissionBinding::from_host_observation(
            "id".into(),
            "tool".into(),
            "1".into(),
            "agent claim".into()
        )
        .is_none());
    }
}
