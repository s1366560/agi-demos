//! New connection routes retain normal local scope and joint-sync admission.
use super::*;
use crate::local_runtime::knowledge_authority_v2::contracts::{
    SyncConnectionRequest, SyncEnrollmentRequest, SyncProjectsRequest, SyncTargetRequest,
    SyncTenantsRequest,
};

pub(super) fn router() -> Router<Arc<LocalRuntimeState>> {
    Router::new()
        .route("/api/v1/knowledge/sync-connection", post(connection))
        .route("/api/v1/knowledge/sync-tenants", post(tenants))
        .route("/api/v1/knowledge/sync-projects", post(projects))
        .route("/api/v1/knowledge/sync-enrollment", post(enrollment))
        .route("/api/v1/knowledge/sync-enroll", post(enroll))
        .route("/api/v1/knowledge/sync-bind", post(bind))
}

async fn connection(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(lease): Extension<Arc<ActivePlatformPluginGenerationLeaseV2>>,
    Extension(auth): Extension<AuthenticatedContext>,
    Json(request): Json<SyncConnectionRequest>,
) -> RouteResult {
    let operation = KnowledgeOperationV2::admit(lease, &auth, &request.scope)
        .map_err(IntoResponse::into_response)?;
    let result = operation
        .sync_connection(&state, &auth)
        .await
        .map_err(IntoResponse::into_response)?;
    Ok(envelope(request.scope, result))
}
async fn tenants(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(lease): Extension<Arc<ActivePlatformPluginGenerationLeaseV2>>,
    Extension(auth): Extension<AuthenticatedContext>,
    Json(request): Json<SyncTenantsRequest>,
) -> RouteResult {
    let operation = KnowledgeOperationV2::admit(lease, &auth, &request.scope)
        .map_err(IntoResponse::into_response)?;
    let result = operation
        .sync_tenants(&state, &auth, &request.expected_connection_revision)
        .await
        .map_err(IntoResponse::into_response)?;
    Ok(envelope(request.scope, result))
}
async fn projects(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(lease): Extension<Arc<ActivePlatformPluginGenerationLeaseV2>>,
    Extension(auth): Extension<AuthenticatedContext>,
    Json(request): Json<SyncProjectsRequest>,
) -> RouteResult {
    let operation = KnowledgeOperationV2::admit(lease, &auth, &request.scope)
        .map_err(IntoResponse::into_response)?;
    let result = operation
        .sync_projects(
            &state,
            &auth,
            &request.expected_connection_revision,
            &request.tenant_id,
        )
        .await
        .map_err(IntoResponse::into_response)?;
    Ok(envelope(request.scope, result))
}
async fn enrollment(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(lease): Extension<Arc<ActivePlatformPluginGenerationLeaseV2>>,
    Extension(auth): Extension<AuthenticatedContext>,
    Json(request): Json<SyncEnrollmentRequest>,
) -> RouteResult {
    let operation = KnowledgeOperationV2::admit(lease, &auth, &request.scope)
        .map_err(IntoResponse::into_response)?;
    let result = operation
        .sync_enrollment(&state, &auth, &request)
        .await
        .map_err(IntoResponse::into_response)?;
    Ok(envelope(request.scope, result))
}
async fn enroll(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(lease): Extension<Arc<ActivePlatformPluginGenerationLeaseV2>>,
    Extension(auth): Extension<AuthenticatedContext>,
    Json(request): Json<SyncTargetRequest>,
) -> RouteResult {
    let operation = KnowledgeOperationV2::admit(lease, &auth, &request.scope)
        .map_err(IntoResponse::into_response)?;
    let result = operation
        .sync_enroll(&state, &auth, &request)
        .await
        .map_err(IntoResponse::into_response)?;
    Ok(envelope(request.scope, result))
}
async fn bind(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(lease): Extension<Arc<ActivePlatformPluginGenerationLeaseV2>>,
    Extension(auth): Extension<AuthenticatedContext>,
    Json(request): Json<SyncTargetRequest>,
) -> RouteResult {
    let operation = KnowledgeOperationV2::admit(lease, &auth, &request.scope)
        .map_err(IntoResponse::into_response)?;
    let result = operation
        .sync_bind(&state, &auth, &request)
        .await
        .map_err(IntoResponse::into_response)?;
    Ok(envelope(request.scope, result))
}
fn envelope(scope: KnowledgeOperationScopeV2, result: Value) -> Json<Value> {
    Json(json!({"contract_version":VERSION,"scope":scope,"result":result}))
}
