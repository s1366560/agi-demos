//! Accepted human responses retain existing surfaces without renewing old callbacks.
use super::*;
use crate::local_runtime::{
    authority_store::{DesktopHitlRequest, DesktopHitlStatus, DesktopRun, DesktopRunStatus},
    platform_plugin_authority_v2::ActivePlatformPluginGenerationLeaseV2,
};
use agistack_core::agent::types::HitlKind;

pub(in crate::local_runtime) struct LocalHumanResponseSurfaces {
    engine_session_id: String,
    tabs: Vec<(String, AppTab)>,
}

fn surface_waiting_status(request: &DesktopHitlRequest) -> Option<DesktopRunStatus> {
    match request.kind {
        HitlKind::Permission
            if request
                .decision
                .as_ref()
                .is_some_and(|decision| decision.target.kind == "tool") =>
        {
            Some(DesktopRunStatus::NeedsApproval)
        }
        HitlKind::Clarification => Some(DesktopRunStatus::NeedsInput),
        _ => None,
    }
}

fn accepted_surface_response(request: &DesktopHitlRequest) -> bool {
    let Some(response) = request.response_data.as_ref() else {
        return false;
    };
    match request.kind {
        HitlKind::Permission => response["granted"].as_bool() == Some(true),
        HitlKind::Clarification => {
            super::super::hitl_response_answer(request.kind, response).is_some()
        }
        _ => false,
    }
}

impl McpAppAutomationRegistry {
    /// Capture before committing the response. The waiting engine has already
    /// replaced the run authority, so this deliberately does not admit operations.
    pub(in crate::local_runtime) fn capture_local_human_response(
        &self,
        waiting: &DesktopRun,
        request: &DesktopHitlRequest,
        tenant: &str,
        engine: &str,
    ) -> Option<LocalHumanResponseSurfaces> {
        if surface_waiting_status(request) != Some(waiting.status)
            || request.run_id.as_deref() != Some(waiting.id.as_str())
            || request.conversation_id != waiting.conversation_id
            || engine != waiting.conversation_id
        {
            return None;
        }
        let tabs = self
            .tabs
            .lock()
            .expect("MCP app tabs")
            .iter()
            .filter(|(_, tab)| {
                tab.local_origin
                    && !tab.mount_cancelled
                    && tab.child.is_none()
                    && tab.scope.device_id.is_none()
                    && tab.scope.connection_epoch.is_none()
                    && tab.scope.tenant_id == tenant
                    && tab.scope.project_id == waiting.project_id
                    && tab.scope.conversation_id == waiting.conversation_id
                    && tab.scope.run_id == waiting.id
                    && tab.scope.run_revision.checked_add(1) == Some(waiting.revision)
                    && (tab.scope.engine_session_id.is_empty()
                        || tab.scope.engine_session_id == engine)
                    && tab.identity.engine_session_id() == engine
            })
            .map(|(id, tab)| (id.clone(), tab.clone()))
            .collect();
        Some(LocalHumanResponseSurfaces {
            engine_session_id: engine.into(),
            tabs,
        })
    }

    /// Only the authenticated handler calls this, after checkpoint acceptance
    /// and the waiting-to-running CAS. No tool permission is issued here.
    pub(in crate::local_runtime) fn resume_local_human_response(
        &self,
        state: &LocalRuntimeState,
        waiting: &DesktopRun,
        resumed: &DesktopRun,
        request: &DesktopHitlRequest,
        captured: &LocalHumanResponseSurfaces,
        accepted_engine: &str,
        generation: &ActivePlatformPluginGenerationLeaseV2,
    ) {
        if surface_waiting_status(request) != Some(waiting.status)
            || request.status != DesktopHitlStatus::Responded
            || !accepted_surface_response(request)
            || request.run_id.as_deref() != Some(waiting.id.as_str())
            || request.conversation_id != waiting.conversation_id
            || resumed.status != DesktopRunStatus::Running
            || waiting.revision.checked_add(1) != Some(resumed.revision)
            || waiting.id != resumed.id
            || waiting.conversation_id != resumed.conversation_id
            || waiting.project_id != resumed.project_id
            || waiting.plan_version_id != resumed.plan_version_id
            || waiting.permission_profile != resumed.permission_profile
            || waiting.environment != resumed.environment
            || waiting.authorization_snapshot != resumed.authorization_snapshot
            || captured.engine_session_id != accepted_engine
            || accepted_engine != resumed.conversation_id
            || !state
                .session_store
                .run(&resumed.id)
                .ok()
                .flatten()
                .is_some_and(|run| {
                    run.status == DesktopRunStatus::Running && run.revision == resumed.revision
                })
        {
            return;
        }
        state
            .platform_plugin_authority_v2
            .with_current_generation(generation.descriptor(), || {
                let mut tabs = self.tabs.lock().expect("MCP app tabs");
                for (id, previous) in &captured.tabs {
                    let Some(tab) = tabs.get_mut(id) else {
                        continue;
                    };
                    // A first verified mount can arrive after capture. It has no
                    // prior handle or callback lineage; any cancellation/remount
                    // changes its tombstones and must still fail closed.
                    let first_pending_mount = previous.mount_nonce.is_none()
                        && !previous.attached
                        && previous.registration.is_none()
                        && !tab.attached
                        && tab.registration.is_none()
                        && tab.cancelled_mounts == previous.cancelled_mounts;
                    if !tab.local_origin
                        || !previous.local_origin
                        || tab.scope != previous.scope
                        || tab.scope.generation != generation.descriptor().generation
                        || tab.mount_cancelled
                        || (tab.mount_nonce != previous.mount_nonce && !first_pending_mount)
                        || tab.attached != previous.attached
                        || tab.registration != previous.registration
                        || tab.child.is_some()
                        || tab.app != previous.app
                        || tab.identity.engine_session_id() != accepted_engine
                        || tab.identity.round() != previous.identity.round()
                    {
                        continue;
                    }
                    let scope = super::super::mcp_supervisor::McpScope {
                        tenant_id: tab.scope.tenant_id.clone(),
                        project_id: tab.scope.project_id.clone(),
                    };
                    let Ok(binding) = state.mcp_supervisor.resolve_tool(
                        &scope,
                        &tab.app.server_id,
                        &tab.app.tool_name,
                    ) else {
                        continue;
                    };
                    if binding.server_revision != previous.binding.server_revision
                        || binding.catalog_digest != previous.binding.catalog_digest
                        || tab.binding.server_revision != previous.binding.server_revision
                        || tab.binding.catalog_digest != previous.binding.catalog_digest
                    {
                        continue;
                    }
                    tab.scope.run_revision = resumed.revision;
                    // A human response starts fresh operations. Earlier exact-step
                    // approvals cannot carry their captured callbacks across it.
                    tab.continuation_revisions.clear();
                }
            });
    }
}
