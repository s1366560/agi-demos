//! Adapter error type. Everything funnels into `CoreError::Tool` at the port
//! boundary; structured kinds survive in the message prefix for the timeline.

use agistack_core::CoreError;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum CuaError {
    #[error("cua_incompatible_client_version: client={client} server={server}")]
    IncompatibleClientVersion { client: String, server: String },
    #[error("cua_helper_spawn_failed: {0}")]
    HelperSpawnFailed(String),
    #[error("cua_helper_unreachable: {0}")]
    Unreachable(String),
    #[error(
        "cua_action_outcome_unknown: {0}; observe current state before deciding what to do next"
    )]
    OutcomeUnknown(String),
    #[error("cua_request_failed({kind}): {message}")]
    Request { kind: String, message: String },
    #[error("cua_invalid_response: {0}")]
    InvalidResponse(String),
}

impl CuaError {
    /// Kinds produced by the helper's JSON-RPC error payloads (kept in sync
    /// with the helper's `kind` values).
    pub fn from_rpc_kind(kind: &str, message: &str) -> Self {
        CuaError::Request {
            kind: kind.to_string(),
            message: message.to_string(),
        }
    }
}

impl From<CuaError> for CoreError {
    fn from(error: CuaError) -> Self {
        if matches!(&error, CuaError::Request { kind, .. } if matches!(kind.as_str(), "user_paused_session" | "user_stopped_session"))
        {
            CoreError::NativeControlInterrupted
        } else {
            CoreError::Tool(error.to_string())
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn converts_into_core_tool_error() {
        let error = CuaError::from_rpc_kind("stale_element", "refresh get_app_state");
        let core: CoreError = error.into();
        match core {
            CoreError::Tool(message) => {
                assert!(message.contains("stale_element"));
                assert!(message.contains("get_app_state"));
            }
            other => panic!("expected Tool error, got {other:?}"),
        }
    }
}

#[cfg(test)]
mod control_tests {
    use super::*;
    #[test]
    fn only_structured_native_interrupt_retains_control_discriminant() {
        assert!(matches!(
            CoreError::from(CuaError::from_rpc_kind("user_paused_session", "opaque")),
            CoreError::NativeControlInterrupted
        ));
        assert!(matches!(
            CoreError::from(CuaError::from_rpc_kind(
                "permission_denied",
                "user_paused_session"
            )),
            CoreError::Tool(_)
        ));
        assert!(matches!(
            CoreError::from(CuaError::OutcomeUnknown("user_stopped_session".into())),
            CoreError::Tool(_)
        ));
    }
}
