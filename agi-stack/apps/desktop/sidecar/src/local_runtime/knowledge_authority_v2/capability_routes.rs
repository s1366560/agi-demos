//! An observed entry for the existing project-project-memories capability.
//! Discovery never opens knowledge storage, including in the closed release.
use super::*;
use axum::extract::OriginalUri;

pub(super) async fn capabilities(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(lease): Extension<Arc<ActivePlatformPluginGenerationLeaseV2>>,
    Extension(auth): Extension<AuthenticatedContext>,
    OriginalUri(uri): OriginalUri,
) -> RouteResult {
    if uri.query().is_some() {
        return Err(
            KnowledgeAuthorityErrorV2::Knowledge(KnowledgeError::InvalidInput).into_response(),
        );
    }
    observe(&state, &lease, &auth)
        .map(Json)
        .map_err(IntoResponse::into_response)
}

pub(in crate::local_runtime::knowledge_authority_v2) fn observe(
    state: &LocalRuntimeState,
    lease: &ActivePlatformPluginGenerationLeaseV2,
    auth: &AuthenticatedContext,
) -> Result<Value, KnowledgeAuthorityErrorV2> {
    let descriptor = lease.descriptor();
    if !auth.user.is_active
        || descriptor.generation > 9_007_199_254_740_991
        || auth.workspace.revision > 9_007_199_254_740_991
    {
        return Err(KnowledgeAuthorityErrorV2::ScopeMismatch);
    }
    if state
        .platform_plugin_authority_v2
        .with_current_generation(descriptor, || ())
        .is_none()
    {
        return Err(KnowledgeAuthorityErrorV2::GenerationMismatch);
    }
    let authority = lease.knowledge_authority(&ScopeV2 {
        kind: ScopeKindV2::Project,
        tenant_id: Some(auth.workspace.tenant_id.clone()),
        project_id: Some(auth.workspace.project_id.clone()),
        session_id: None,
    })?;
    let connection = state
        .session_store
        .connection()
        .map_err(|_| KnowledgeAuthorityErrorV2::Forbidden)?;
    let membership = processing_context::live_membership(&connection, auth, false)?;
    state.platform_plugin_authority_v2.with_current_generation(descriptor, || {
        let actions = authority.allowed_actions(&membership.role)?;
        if chrono::Utc::now().timestamp_millis() >= membership.expires_at_ms {
            return Err(KnowledgeAuthorityErrorV2::Forbidden);
        }
        Ok(json!({"contract_version": VERSION, "actor_id":auth.user.user_id,
            "scope": {"tenant_id":auth.workspace.tenant_id,"project_id":auth.workspace.project_id,
                "context_revision":auth.workspace.revision,"profile_id":descriptor.profile_id,
                "generation":descriptor.generation,"digest":descriptor.digest},
            "result": {"availability":if actions.is_empty(){"unavailable"}else{"degraded"},
                "reason_code":if actions.is_empty(){"knowledge_release_closed"}else{"desktop_project_memories_actions_partial"},
                "service_version":env!("CARGO_PKG_VERSION"),"contract_version":VERSION,
                "allowed_actions":actions,"scope":{"tenant_id":auth.workspace.tenant_id,"project_id":auth.workspace.project_id,
                    "workspace_id":null,"instance_id":null},"authority_revision":auth.workspace.revision,
                "retryable":false,"authority_source":"sidecar","supporting_authority_sources":[],"provenance":"observed"}
        }))
    }).ok_or(KnowledgeAuthorityErrorV2::GenerationMismatch)?
}
