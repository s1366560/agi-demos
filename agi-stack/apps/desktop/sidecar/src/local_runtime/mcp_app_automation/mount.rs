//! An iframe mount is an independent host-owned lifetime, including while waiting.
use super::*;
use crate::local_runtime::authority_store::DesktopRunStatus;

impl McpAppAutomationRegistry {
    pub(super) fn cancel_mount(&self, id: &str, nonce: &str) -> CoreResult<Value> {
        if let Some(tab) = self.tabs.lock().expect("MCP app tabs").get_mut(id) {
            // Remember cancellation even before asynchronous registration completes.
            // An old effect cannot revoke the replacement mount.
            tab.cancelled_mounts.insert(nonce.into());
            if tab.mount_nonce.is_none() || tab.mount_nonce.as_deref() == Some(nonce) {
                tab.mount_cancelled = true;
                tab.attached = false;
                tab.registration = None;
                tab.continuation_revisions.clear();
            }
        }
        Ok(json!({}))
    }

    pub(super) fn attach_mount(
        &self,
        state: &LocalRuntimeState,
        id: &str,
        nonce: &str,
    ) -> CoreResult<Value> {
        let (captured, pending) = match self.require(state, id, None) {
            Ok((tab, _)) => (tab, false),
            Err(error) => {
                let Some(tab) = self.waiting_mount(state, id) else {
                    return Err(error);
                };
                (tab, true)
            }
        };
        let mut tabs = self.tabs.lock().expect("MCP app tabs");
        let tab = tabs
            .get_mut(id)
            .ok_or_else(|| denied("mcp_app_frame_expired"))?;
        if tab.scope != captured.scope
            || tab.mount_nonce != captured.mount_nonce
            || tab.mount_cancelled != captured.mount_cancelled
            || tab.cancelled_mounts.contains(nonce)
        {
            return Err(denied("mcp_app_mount_expired"));
        }
        if tab
            .mount_nonce
            .as_deref()
            .is_some_and(|current| current != nonce)
            && !tab.mount_cancelled
        {
            return Err(denied("mcp_app_mount_already_bound"));
        }
        if tab.mount_nonce.as_deref() != Some(nonce) {
            tab.attached = false;
            tab.registration = None;
            tab.continuation_revisions.clear();
        }
        tab.mount_nonce = Some(nonce.into());
        tab.mount_cancelled = false;
        if !pending && !tab.attached {
            tab.registration = Some(format!("mcpapp-{}", uuid::Uuid::new_v4()));
            tab.attached = true;
        }
        Ok(json!({"tabId":id,"pending":pending}))
    }

    /// Waiting admits only the verified mount identity, never App calls or a
    /// public browser handle. A human response must renew this exact mount before the
    /// normal current-authority attach can succeed.
    fn waiting_mount(&self, state: &LocalRuntimeState, id: &str) -> Option<AppTab> {
        let tab = self.tabs.lock().ok()?.get(id)?.clone();
        let generation = state
            .platform_plugin_authority_v2
            .acquire_generation()
            .ok()?;
        if !tab.local_origin
            || tab.child.is_some()
            || tab.scope.device_id.is_some()
            || tab.scope.connection_epoch.is_some()
            || tab.scope.generation != generation.descriptor().generation
            || tab.identity.engine_session_id() != tab.scope.conversation_id
            || (!tab.scope.engine_session_id.is_empty()
                && tab.scope.engine_session_id != tab.scope.conversation_id)
        {
            return None;
        }
        // The waiting engine releases its old tool host. Only persisted local
        // ownership admits an iframe identity here; operations still require a
        // fresh, current authority through `require` after approval.
        let conversation = state
            .session_store
            .conversation(&tab.scope.conversation_id)
            .ok()??;
        if conversation.tenant_id != tab.scope.tenant_id
            || conversation.project_id != tab.scope.project_id
        {
            return None;
        }
        let run = state.session_store.run(&tab.scope.run_id).ok()??;
        if !matches!(
            run.status,
            DesktopRunStatus::NeedsApproval | DesktopRunStatus::NeedsInput
        ) || run.conversation_id != tab.scope.conversation_id
            || run.project_id != tab.scope.project_id
            || tab.scope.run_revision.checked_add(1) != Some(run.revision)
        {
            return None;
        }
        let scope = super::super::mcp_supervisor::McpScope {
            tenant_id: tab.scope.tenant_id.clone(),
            project_id: tab.scope.project_id.clone(),
        };
        let binding = state
            .mcp_supervisor
            .resolve_tool(&scope, &tab.app.server_id, &tab.app.tool_name)
            .ok()?;
        if binding.server_revision != tab.binding.server_revision
            || binding.catalog_digest != tab.binding.catalog_digest
        {
            return None;
        }
        Some(tab)
    }
}
