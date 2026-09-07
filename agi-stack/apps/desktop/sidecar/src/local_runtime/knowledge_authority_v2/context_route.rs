//! Scope discovery is independent of knowledge publication and never opens storage.
use super::*;
pub(super) async fn context(
    Extension(lease): Extension<Arc<ActivePlatformPluginGenerationLeaseV2>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
) -> RouteResult {
    if !authenticated.user.is_active {
        return Err(KnowledgeAuthorityErrorV2::ScopeMismatch.into_response());
    }
    let descriptor = lease.descriptor();
    if descriptor.generation > 9_007_199_254_740_991
        || authenticated.workspace.revision > 9_007_199_254_740_991
    {
        return Err(rejection(
            StatusCode::SERVICE_UNAVAILABLE,
            "knowledge_scope_revision_unrepresentable",
            "native scope revision cannot be represented by the client",
        ));
    }
    let scope = KnowledgeOperationScopeV2 {
        tenant_id: authenticated.workspace.tenant_id.clone(),
        project_id: authenticated.workspace.project_id.clone(),
        context_revision: authenticated.workspace.revision,
        profile_id: descriptor.profile_id.clone(),
        generation: descriptor.generation,
        digest: descriptor.digest.clone(),
    };
    Ok(Json(json!({"contract_version":VERSION,"scope":scope})))
}
