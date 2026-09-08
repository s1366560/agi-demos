use super::*;
use crate::local_runtime::knowledge_authority_v2::sync::CloudResolutionDispatch;
use crate::trusted_session::TrustedSessionBroker;

fn dispatch(
    result: CloudResolutionDispatch,
    scope: KnowledgeOperationScopeV2,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    match result {
        CloudResolutionDispatch::Resolved(result) => Ok(Json(json!({
            "contract_version": VERSION,
            "scope": scope,
            "result": result,
        }))),
        CloudResolutionDispatch::Stale(id) => Err((
            StatusCode::CONFLICT,
            Json(json!({
                "error": {
                    "code": "knowledge_sync_resolution_stale",
                    "message": "refresh the conflict and submit a new explicit decision",
                    "resolution_id": id,
                    "target": "desktop-sidecar",
                },
            })),
        )),
    }
}

fn broker(state: &LocalRuntimeState) -> Result<TrustedSessionBroker, KnowledgeAuthorityErrorV2> {
    state
        .platform_plugin_authority_v2
        .trusted_sessions()
        .ok_or(KnowledgeAuthorityErrorV2::TransportUnavailable)
}
use super::super::contracts::{
    CloudQuery, CloudQueryRequest, ReconcileRequest, ResolveRequest, ResumeRequest,
};

pub(super) async fn resolve(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(lease): Extension<Arc<ActivePlatformPluginGenerationLeaseV2>>,
    Extension(auth): Extension<AuthenticatedContext>,
    headers: HeaderMap,
    Json(body): Json<ResolveRequest>,
) -> RouteResult {
    let operation = KnowledgeOperationV2::admit(lease, &auth, &body.scope)
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
    let result = operation
        .resolve_cloud_conflict(
            &broker(&state).map_err(IntoResponse::into_response)?,
            key,
            body.resolution,
        )
        .await
        .map_err(IntoResponse::into_response)?;
    dispatch(result, body.scope).map_err(IntoResponse::into_response)
}
pub(super) async fn resume(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(lease): Extension<Arc<ActivePlatformPluginGenerationLeaseV2>>,
    Extension(auth): Extension<AuthenticatedContext>,
    Json(body): Json<ResumeRequest>,
) -> RouteResult {
    let operation = KnowledgeOperationV2::admit(lease, &auth, &body.scope)
        .map_err(IntoResponse::into_response)?;
    let result = operation
        .resume_cloud_resolution(
            &broker(&state).map_err(IntoResponse::into_response)?,
            &body.resolution_id,
        )
        .await
        .map_err(IntoResponse::into_response)?;
    dispatch(result, body.scope).map_err(IntoResponse::into_response)
}
pub(super) async fn reconcile(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(lease): Extension<Arc<ActivePlatformPluginGenerationLeaseV2>>,
    Extension(auth): Extension<AuthenticatedContext>,
    Json(body): Json<ReconcileRequest>,
) -> RouteResult {
    let operation = KnowledgeOperationV2::admit(lease, &auth, &body.scope)
        .map_err(IntoResponse::into_response)?;
    let result = operation
        .reconcile_cloud_resolution(
            &broker(&state).map_err(IntoResponse::into_response)?,
            &body.resolution_id,
            body.reconciliation,
        )
        .await
        .map_err(IntoResponse::into_response)?;
    Ok(Json(
        json!({"contract_version":VERSION,"scope":body.scope,"result":result}),
    ))
}
pub(super) async fn query(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(lease): Extension<Arc<ActivePlatformPluginGenerationLeaseV2>>,
    Extension(auth): Extension<AuthenticatedContext>,
    Json(body): Json<CloudQueryRequest>,
) -> RouteResult {
    let operation = KnowledgeOperationV2::admit(lease, &auth, &body.scope)
        .map_err(IntoResponse::into_response)?;
    let broker = broker(&state).map_err(IntoResponse::into_response)?;
    let result = match body.query {
        CloudQuery::ResolutionByKey { idempotency_key } => {
            json!({
                "record": operation.cloud_resolution_by_key(&broker, &idempotency_key)
                    .await.map_err(IntoResponse::into_response)?,
            })
        }
        CloudQuery::PendingResolutions {
            before_resolution_id,
            limit,
        } => {
            validate_limit(limit).map_err(invalid_page)?;
            let page = operation
                .pending_cloud_resolutions(&broker, before_resolution_id.as_deref(), limit)
                .await
                .map_err(IntoResponse::into_response)?;
            json!({
                "items": page.items,
                "next_before_resolution_id": page.next_before_resolution_id,
            })
        }
        CloudQuery::ConflictContext { local_sequence } => {
            json!({
                "context":operation.cloud_conflict_context(&broker,
                local_sequence).await.map_err(IntoResponse::into_response)?
            })
        }
        CloudQuery::Resolution { resolution_id } => {
            json!({
                "record":operation.cloud_resolution_record(&broker,
                &resolution_id).await.map_err(IntoResponse::into_response)?
            })
        }
        CloudQuery::Resolutions { limit } => {
            validate_limit(limit).map_err(invalid_page)?;
            json!({"items":operation.cloud_resolution_records(&broker,limit).await.map_err(IntoResponse::into_response)?})
        }
        CloudQuery::ReconciliationContext { resolution_id } => {
            json!({
                "context":operation.cloud_reconciliation_context(&broker,
                &resolution_id).await.map_err(IntoResponse::into_response)?
            })
        }
    };
    Ok(Json(
        json!({"contract_version":VERSION,"scope":body.scope,"result":result}),
    ))
}
