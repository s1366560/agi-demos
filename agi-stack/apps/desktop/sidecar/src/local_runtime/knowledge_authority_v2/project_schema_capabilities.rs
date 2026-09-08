//! Dedicated schema release and action roster. Memory qualification grants nothing here.
use super::super::*;
use super::actions::{SchemaAction, SCHEMA_ACTIONS};
use crate::local_runtime::LocalRuntimeState;

pub(super) fn authority(
    lease: &ActivePlatformPluginGenerationLeaseV2,
    auth: &AuthenticatedContext,
) -> std::result::Result<Arc<KnowledgeAuthorityV2>, KnowledgeAuthorityErrorV2> {
    let descriptor = lease.descriptor();
    let authority = lease.knowledge_authority(&ScopeV2 {
        kind: ScopeKindV2::Project,
        tenant_id: Some(auth.workspace.tenant_id.clone()),
        project_id: Some(auth.workspace.project_id.clone()),
        session_id: None,
    })?;
    authority.require_profile(
        &descriptor.profile_id,
        &descriptor.digest,
        descriptor.publication_version,
    )?;
    Ok(authority)
}

impl KnowledgeAuthorityV2 {
    fn schema_actions(
        &self,
        role: &str,
    ) -> std::result::Result<Vec<&'static str>, KnowledgeAuthorityErrorV2> {
        let state = self
            .inner
            .lock()
            .map_err(|_| KnowledgeAuthorityErrorV2::Disposed)?;
        if state.disposed {
            return Err(KnowledgeAuthorityErrorV2::Disposed);
        }
        let writer = matches!(role, "owner" | "admin" | "member" | "contributor");
        if !writer && role != "viewer" {
            return Err(KnowledgeAuthorityErrorV2::Forbidden);
        }
        #[cfg(test)]
        if matches!(state.admission, KnowledgeAdmission::InternalValidation) {
            return Ok(SCHEMA_ACTIONS
                .iter()
                .filter(|action| !action.is_write() || writer)
                .map(|action| action.as_str())
                .collect());
        }
        // LocalAcceptance and SyncAcceptance intentionally remain closed too.
        let _ = SCHEMA_ACTIONS;
        Ok(Vec::new())
    }

    pub(in crate::local_runtime::knowledge_authority_v2) fn require_schema_action(
        &self,
        role: &str,
        action: SchemaAction,
    ) -> std::result::Result<(), KnowledgeAuthorityErrorV2> {
        let actions = self.schema_actions(role)?;
        if actions.is_empty() {
            return Err(KnowledgeAuthorityErrorV2::ReleaseClosed);
        }
        if !actions.contains(&action.as_str()) {
            return Err(KnowledgeAuthorityErrorV2::Forbidden);
        }
        Ok(())
    }
}

pub(in crate::local_runtime::knowledge_authority_v2) fn observe(
    state: &LocalRuntimeState,
    lease: &ActivePlatformPluginGenerationLeaseV2,
    auth: &AuthenticatedContext,
) -> std::result::Result<Value, KnowledgeAuthorityErrorV2> {
    let descriptor = lease.descriptor();
    if !auth.user.is_active
        || descriptor.generation == 0
        || descriptor.generation > 9_007_199_254_740_991
        || auth.workspace.revision > 9_007_199_254_740_991
    {
        return Err(KnowledgeAuthorityErrorV2::ScopeMismatch);
    }
    let connection = state
        .session_store
        .connection()
        .map_err(|_| KnowledgeAuthorityErrorV2::Forbidden)?;
    let membership = processing_context::live_membership(&connection, auth, false)?;
    state.platform_plugin_authority_v2.with_current_generation(descriptor, || {
        let actions = authority(lease, auth)?.schema_actions(&membership.role)?;
        if chrono::Utc::now().timestamp_millis() >= membership.expires_at_ms { return Err(KnowledgeAuthorityErrorV2::Forbidden); }
        Ok(json!({"contract_version":"1.0.0", "authority":"native-project-schema", "operation":"schema_capabilities", "actor_id":auth.user.user_id,
            "scope":{"tenant_id":auth.workspace.tenant_id,"project_id":auth.workspace.project_id,"context_revision":auth.workspace.revision,
                "profile_id":descriptor.profile_id,"generation":descriptor.generation,"digest":descriptor.digest},
            "result":{"route_id":"project-project-schema", "availability":if actions.is_empty(){"unavailable"}else{"degraded"},
                "reason_code":if actions.is_empty(){"project_schema_release_closed"}else{"project_schema_internal_validation"},
                "allowed_actions":actions,"authority_source":"sidecar","provenance":"observed"}}))
    }).ok_or(KnowledgeAuthorityErrorV2::GenerationMismatch)?
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;
    use crate::local_knowledge_acceptance::tests::AcceptanceDirectories;

    #[test]
    fn memory_local_and_sync_qualifications_do_not_admit_schema_or_open_storage() {
        let dirs = AcceptanceDirectories::new();
        for admission in [
            KnowledgeAdmission::LocalAcceptance(dirs.qualification()),
            KnowledgeAdmission::SyncAcceptance(dirs.sync_qualification()),
        ] {
            let authority = KnowledgeAuthorityV2 {
                sync_connection_nonce: uuid::Uuid::new_v4(),
                inner: Arc::new(Mutex::new(KnowledgeState {
                    app_data_dir: Some(dirs.data.clone()),
                    repository: None,
                    disposed: false,
                    admission,
                    validation_actions: None,
                })),
            };
            assert!(authority.schema_actions("owner").unwrap().is_empty());
            for action in SCHEMA_ACTIONS {
                assert!(matches!(
                    authority.require_schema_action("owner", *action),
                    Err(KnowledgeAuthorityErrorV2::ReleaseClosed)
                ));
            }
            assert!(!dirs.data.join("knowledge").exists());
        }
    }
}
