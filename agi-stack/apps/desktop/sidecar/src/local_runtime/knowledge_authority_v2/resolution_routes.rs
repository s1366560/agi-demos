use super::*;
use agistack_core::knowledge::sync::resolution::KnowledgePullConflictResolution;
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ResolutionRequest {
    scope: KnowledgeOperationScopeV2,
    resolution: KnowledgePullConflictResolution,
}
pub(super) async fn resolve_pull(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(lease): Extension<Arc<ActivePlatformPluginGenerationLeaseV2>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    headers: HeaderMap,
    Json(request): Json<ResolutionRequest>,
) -> RouteResult {
    let operation = KnowledgeOperationV2::admit(lease, &authenticated, &request.scope)
        .map_err(IntoResponse::into_response)?;
    let key = headers
        .get("idempotency-key")
        .and_then(|v| v.to_str().ok())
        .filter(|v| !v.is_empty() && v.len() <= 512 && *v == v.trim())
        .ok_or_else(|| {
            rejection(
                StatusCode::BAD_REQUEST,
                "knowledge_idempotency_key_required",
                "a bounded idempotency key is required",
            )
        })?;
    let broker = state
        .platform_plugin_authority_v2
        .trusted_sessions()
        .ok_or_else(|| KnowledgeAuthorityErrorV2::TransportUnavailable.into_response())?;
    let result = operation
        .resolve_pull_conflicts(&broker, key, request.resolution)
        .await
        .map_err(IntoResponse::into_response)?;
    Ok(Json(
        json!({"contract_version":VERSION,"scope":request.scope,"result":result}),
    ))
}
