//! An approval resumes one existing execution; arbitrary scope replacements do not.
use super::*;
use crate::local_runtime::authority_store::{
    DesktopHitlRequest, DesktopHitlStatus, DesktopRun, DesktopRunStatus,
};
use agistack_core::agent::types::HitlKind;

impl McpAppAutomationRegistry {
    /// The cloud dispatcher calls this only after consuming a server-issued
    /// continuation for the exact live cell, step, input and target.
    pub(crate) fn resume_cloud_permission(
        &self,
        previous: &ExecutionScope,
        authority: &ExecutionAuthority,
        target_handle: &str,
    ) -> CoreResult<()> {
        if !matches!(authority, ExecutionAuthority::CloudClaim(_)) {
            return Err(denied("mcp_app_cloud_continuation_required"));
        }
        authority.current()?;
        let current = authority.scope();
        let mut expected = previous.clone();
        expected.run_revision = current.run_revision;
        if expected != *current
            || previous.connection_epoch.is_none()
            || current.run_revision < previous.run_revision
        {
            return Err(denied("mcp_app_continuation_scope_mismatch"));
        }
        let mut tabs = self.tabs.lock().expect("MCP app tabs");
        let tab = tabs
            .values_mut()
            .find(|tab| tab.attached && tab.registration.as_deref() == Some(target_handle))
            .ok_or_else(|| denied("mcp_app_frame_expired"))?;
        if tab.scope != *previous {
            return Err(denied("mcp_app_continuation_scope_mismatch"));
        }
        tab.continuation_revisions.insert(previous.run_revision);
        tab.scope = current.clone();
        Ok(())
    }

    /// Called after the authenticated response and its exact grants have committed,
    /// the checkpoint has accepted that response, and the waiting run has resumed.
    pub(in crate::local_runtime) fn resume_local_permission(
        &self,
        waiting: &DesktopRun,
        resumed: &DesktopRun,
        request: &DesktopHitlRequest,
        pending: Option<&(ExecutionScope, String)>,
    ) {
        let Some((captured, engine)) = pending else {
            return;
        };
        if request.kind != HitlKind::Permission
            || request.status != DesktopHitlStatus::Responded
            || request
                .response_data
                .as_ref()
                .and_then(|response| response["granted"].as_bool())
                != Some(true)
            || request.run_id.as_deref() != Some(waiting.id.as_str())
            || request.conversation_id != waiting.conversation_id
            || waiting.status != DesktopRunStatus::NeedsApproval
            || resumed.status != DesktopRunStatus::Running
            || waiting.revision.checked_add(1) != Some(resumed.revision)
            || waiting.id != resumed.id
            || waiting.conversation_id != resumed.conversation_id
            || waiting.project_id != resumed.project_id
            || waiting.plan_version_id != resumed.plan_version_id
            || waiting.permission_profile != resumed.permission_profile
            || waiting.environment != resumed.environment
            || waiting.authorization_snapshot != resumed.authorization_snapshot
            || captured.run_revision.checked_add(1) != Some(waiting.revision)
            || captured.run_id != waiting.id
            || captured.conversation_id != waiting.conversation_id
            || captured.project_id != waiting.project_id
        {
            return;
        }
        for tab in self.tabs.lock().expect("MCP app tabs").values_mut() {
            // Parent approvals cannot renew a child's independent execution.
            if tab.child.is_none()
                && tab.scope.connection_epoch.is_none()
                && tab.scope == *captured
                && tab.identity.engine_session_id() == engine
            {
                tab.continuation_revisions.insert(tab.scope.run_revision);
                tab.scope.run_revision = resumed.revision;
            }
        }
    }

    /// A queued callback may have captured the previous approved revision. It
    /// still needs its exact live attachment and the newly current authority.
    pub(super) fn require_callback_continuation(
        &self,
        state: &LocalRuntimeState,
        id: &str,
        captured: &ExecutionScope,
    ) -> CoreResult<(AppTab, Arc<ExecutionAuthority>)> {
        let (tab, authority) = self.require(state, id, None)?;
        let mut current = captured.clone();
        current.run_revision = tab.scope.run_revision;
        if current != tab.scope
            || (captured.run_revision != tab.scope.run_revision
                && !tab.continuation_revisions.contains(&captured.run_revision))
        {
            return Err(denied("mcp_app_scope_mismatch"));
        }
        Ok((tab, authority))
    }

    pub(in crate::local_runtime) fn reset_execution(&self, scope: &ExecutionScope, engine: &str) {
        self.tabs.lock().expect("MCP app tabs").retain(|_, tab| {
            tab.scope.tenant_id != scope.tenant_id
                || tab.scope.project_id != scope.project_id
                || tab.scope.conversation_id != scope.conversation_id
                || tab.scope.engine_session_id != scope.engine_session_id
                || tab.scope.device_id != scope.device_id
                || tab.scope.connection_epoch != scope.connection_epoch
                || tab.scope.generation != scope.generation
                || tab.identity.engine_session_id() != engine
        });
    }
}
