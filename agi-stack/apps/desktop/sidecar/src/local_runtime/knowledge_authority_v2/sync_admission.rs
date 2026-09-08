//! Local acceptance cannot activate the separate bidirectional-sync release.
use super::*;
use axum::{extract::Request, middleware::Next};

pub(super) async fn require_sync_release(
    Extension(lease): Extension<Arc<ActivePlatformPluginGenerationLeaseV2>>,
    Extension(auth): Extension<AuthenticatedContext>,
    request: Request,
    next: Next,
) -> Response {
    let result = lease
        .knowledge_authority(&ScopeV2 {
            kind: ScopeKindV2::Project,
            tenant_id: Some(auth.workspace.tenant_id),
            project_id: Some(auth.workspace.project_id),
            session_id: None,
        })
        .map_err(KnowledgeAuthorityErrorV2::from)
        .and_then(|authority| authority.require_sync_release());
    match result {
        Ok(()) => next.run(request).await,
        Err(error) => error.into_response(),
    }
}
