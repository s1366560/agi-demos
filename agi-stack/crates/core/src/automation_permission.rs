//! Exact-invocation permission records. These records never authorize dispatch.
//!
//! Host bindings deliberately do not implement `Deserialize`: an agent or HTTP
//! payload cannot supply an attestation. Trusted host code must resolve the tool
//! and hash the input. Durable plugin generation fencing is a separate boundary.

use serde::{Deserialize, Serialize};

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
