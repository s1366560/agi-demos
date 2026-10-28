//! Host-owned callback provenance. An App cannot provide this through its arguments.
use std::future::Future;

use super::*;

#[derive(Clone)]
pub(super) struct CallbackOrigin {
    pub(super) renderer_id: String,
    pub(super) registration: String,
    pub(super) scope: ExecutionScope,
    pub(super) engine_session_id: String,
    pub(super) server_id: String,
    pub(super) tool_name: String,
}

tokio::task_local! {
    static CURRENT: CallbackOrigin;
}

impl CallbackOrigin {
    pub(super) fn current() -> Option<Self> {
        CURRENT.try_with(Clone::clone).ok()
    }
    pub(super) fn capture(id: &str, tab: &AppTab, binding: &McpToolBinding) -> CoreResult<Self> {
        if !tab.attached || binding.server_id != tab.app.server_id {
            return Err(denied("mcp_app_callback_source_invalid"));
        }
        Ok(Self {
            renderer_id: id.into(),
            registration: tab
                .registration
                .clone()
                .ok_or_else(|| denied("mcp_app_frame_expired"))?,
            scope: tab.scope.clone(),
            engine_session_id: tab.identity.engine_session_id().into(),
            server_id: binding.server_id.clone(),
            tool_name: binding.tool_name.clone(),
        })
    }

    pub(super) async fn scope<F: Future>(self, future: F) -> F::Output {
        CURRENT.scope(self, future).await
    }
}

/// A successful callback returns to its live source frame, rather than opening
/// a replacement App and revoking the callback that is still awaiting its result.
pub(in crate::local_runtime) fn is_callback_result(
    state: &LocalRuntimeState,
    run_id: &str,
    server_id: &str,
    tool_name: &str,
) -> CoreResult<bool> {
    CURRENT
        .try_with(|origin| {
            if origin.scope.run_id != run_id
                || origin.server_id != server_id
                || origin.tool_name != tool_name
                || call_identity::active()?.engine_session_id() != origin.engine_session_id
            {
                return Err(denied("mcp_app_callback_binding_changed"));
            }
            let (tab, _) = state.mcp_app_automation.require_callback_continuation(
                state,
                &origin.renderer_id,
                &origin.scope,
            )?;
            if !tab.attached || tab.registration.as_deref() != Some(origin.registration.as_str()) {
                return Err(denied("mcp_app_frame_or_scope_changed"));
            }
            Ok(true)
        })
        .unwrap_or(Ok(false))
}
