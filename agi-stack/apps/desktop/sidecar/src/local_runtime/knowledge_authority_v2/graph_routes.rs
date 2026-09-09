//! Derived-record sync resolution RPCs. Both ride the sync-release middleware
//! and require a writer; the pull path is local-only, the push path settles
//! through the verified cloud transport.
use super::super::contracts::{GraphResolutionRequest, GraphResolvePushRequest};
use super::*;

pub(super) async fn resolve_graph_pull(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(lease): Extension<Arc<ActivePlatformPluginGenerationLeaseV2>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    headers: HeaderMap,
    Json(request): Json<GraphResolutionRequest>,
) -> RouteResult {
    let operation = KnowledgeOperationV2::admit(lease, &authenticated, &request.scope)
        .map_err(IntoResponse::into_response)?
        .admit_capability(&state, &authenticated, "resolve_graph_pull")
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
        .resolve_graph_pull_conflicts(&broker, key, request.resolution)
        .await
        .map_err(IntoResponse::into_response)?;
    Ok(Json(
        json!({"contract_version":VERSION,"scope":request.scope,"result":result}),
    ))
}

pub(super) async fn resolve_graph_push(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(lease): Extension<Arc<ActivePlatformPluginGenerationLeaseV2>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Json(request): Json<GraphResolvePushRequest>,
) -> RouteResult {
    let operation = KnowledgeOperationV2::admit(lease, &authenticated, &request.scope)
        .map_err(IntoResponse::into_response)?
        .admit_capability(&state, &authenticated, "resolve_graph_push")
        .map_err(IntoResponse::into_response)?;
    let broker = state
        .platform_plugin_authority_v2
        .trusted_sessions()
        .ok_or_else(|| KnowledgeAuthorityErrorV2::TransportUnavailable.into_response())?;
    let scope = request.scope.clone();
    let result = operation
        .resolve_graph_push(&broker, request)
        .await
        .map_err(IntoResponse::into_response)?;
    Ok(Json(
        json!({"contract_version":VERSION,"scope":scope,"result":result}),
    ))
}
