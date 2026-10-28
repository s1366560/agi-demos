//! Audio model input requires a current native identity and a persisted owned artifact.
use std::sync::{Arc, Weak};

use agistack_core::{
    agent::types::MediaAttachment,
    ports::{CoreError, CoreResult},
};
use rusqlite::{params, OptionalExtension};

use crate::local_runtime::{
    agent_boundary_v2::AgentBoundaryV2,
    knowledge_authority_v2::agent_access::PluginNativeIdentityV2, DesktopRun, LocalConversation,
    LocalRuntimeState,
};

pub(super) struct AudioInputAuthority {
    state: Weak<LocalRuntimeState>,
    identity: PluginNativeIdentityV2,
    conversation_id: String,
    run: Option<DesktopRun>,
    boundary: Option<Arc<AgentBoundaryV2>>,
}

impl AudioInputAuthority {
    pub(super) fn capture(
        state: &Arc<LocalRuntimeState>,
        conversation: &LocalConversation,
        run: Option<&DesktopRun>,
        boundary: Option<Arc<AgentBoundaryV2>>,
    ) -> Option<Self> {
        Some(Self {
            state: Arc::downgrade(state),
            identity: PluginNativeIdentityV2::capture(state, conversation, run)?,
            conversation_id: conversation.id.clone(),
            run: run.cloned(),
            boundary,
        })
    }

    pub(super) fn validate(&self, attachment: &MediaAttachment) -> CoreResult<()> {
        let denied = || CoreError::Llm("audio_input_authority_revoked".into());
        let state = self.state.upgrade().ok_or_else(denied)?;
        let auth = self.identity.auth();
        if !self.identity.current(&state)
            || !state
                .session_store
                .session_context_is_current(auth, chrono::Utc::now().timestamp_millis())
                .map_err(|_| denied())?
            || self
                .boundary
                .as_ref()
                .is_some_and(|boundary| !boundary.current(&state))
        {
            return Err(denied());
        }
        if let Some(run) = &self.run {
            let current = state
                .session_store
                .run(&run.id)
                .map_err(|_| denied())?
                .ok_or_else(denied)?;
            if current.revision != run.revision
                || current.permission_profile != run.permission_profile
                || current.environment != run.environment
                || current.plan_version_id != run.plan_version_id
                || current.message_id != run.message_id
                || state.control_for_run(&current).is_none()
            {
                return Err(denied());
            }
        }
        let invalid = || CoreError::Llm("audio_input_artifact_not_owned".into());
        let db = state.session_store.connection().map_err(|_| invalid())?;
        let owned = db.query_row(
            "SELECT 1 FROM desktop_cua_artifacts_v2 WHERE path=?1 AND mime_type=?2 AND user_id=?3 AND tenant_id=?4 AND project_id=?5 AND device_id=?6 AND conversation_id=?7",
            params![attachment.artifact_path,attachment.mime_type,auth.user.user_id,auth.workspace.tenant_id,auth.workspace.project_id,state.session_store.installation_id(),self.conversation_id],
            |_| Ok(()),
        ).optional().map_err(|_| invalid())?.is_some();
        if !owned {
            return Err(invalid());
        }
        let root = state
            .app_data_dir
            .as_ref()
            .ok_or_else(invalid)?
            .join("computer-use-artifacts")
            .canonicalize()
            .map_err(|_| invalid())?;
        let path = std::path::Path::new(&attachment.artifact_path);
        let metadata = std::fs::symlink_metadata(path).map_err(|_| invalid())?;
        let canonical = path.canonicalize().map_err(|_| invalid())?;
        if !path.is_absolute()
            || metadata.file_type().is_symlink()
            || !metadata.is_file()
            || metadata.len() == 0
            || metadata.len() > 64 * 1024 * 1024
            || !canonical.starts_with(root)
        {
            return Err(invalid());
        }
        Ok(())
    }
}
