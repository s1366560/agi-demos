//! Narrow storage RPCs. They share the normal native launch/session/scope/
//! generation middleware; capability publication stays closed independently.

use axum::{
    extract::{Extension, State},
    http::{HeaderMap, StatusCode},
    response::{IntoResponse, Response},
    routing::{get, post},
    Json, Router,
};

use super::*;
use crate::local_runtime::LocalRuntimeState;

#[path = "capability_routes.rs"]
pub(super) mod capability_routes;
#[path = "cloud_routes.rs"]
mod cloud_routes;
#[path = "context_route.rs"]
mod context_route;
#[path = "graph_routes.rs"]
mod graph_routes;
#[path = "processing_routes.rs"]
mod processing_routes;
#[path = "resolution_routes.rs"]
mod resolution_routes;
#[path = "sync_admission.rs"]
mod sync_admission;
#[path = "sync_connection_routes.rs"]
mod sync_connection_routes;

#[path = "project_schema_routes.rs"]
mod project_schema_routes;

pub(super) fn router() -> Router<Arc<LocalRuntimeState>> {
    Router::new()
        .merge(project_schema_routes::router())
        .route("/api/v1/knowledge/context", get(context_route::context))
        .route(
            "/api/v1/knowledge/capabilities",
            get(capability_routes::capabilities),
        )
        .route("/api/v1/knowledge/query", post(query))
        .route(
            "/api/v1/knowledge/processing-query",
            post(processing_routes::query),
        )
        .route(
            "/api/v1/knowledge/processing-command",
            post(processing_routes::command),
        )
        .route("/api/v1/knowledge/mutations", post(mutate))
        .merge(
            Router::new()
                .merge(sync_connection_routes::router())
                .route("/api/v1/knowledge/sync-link", post(configure_sync_link))
                .route("/api/v1/knowledge/sync-unbind", post(unbind))
                .route("/api/v1/knowledge/sync-push", post(push_once))
                .route("/api/v1/knowledge/sync-pull", post(pull_once))
                .route(
                    "/api/v1/knowledge/sync-resolve-push",
                    post(cloud_routes::resolve),
                )
                .route(
                    "/api/v1/knowledge/sync-resume-resolution",
                    post(cloud_routes::resume),
                )
                .route(
                    "/api/v1/knowledge/sync-reconcile-resolution",
                    post(cloud_routes::reconcile),
                )
                .route(
                    "/api/v1/knowledge/sync-cloud-query",
                    post(cloud_routes::query),
                )
                .route(
                    "/api/v1/knowledge/sync-resolve-pull",
                    post(resolution_routes::resolve_pull),
                )
                .route(
                    "/api/v1/knowledge/sync-resolve-graph-pull",
                    post(graph_routes::resolve_graph_pull),
                )
                .route(
                    "/api/v1/knowledge/sync-resolve-graph-push",
                    post(graph_routes::resolve_graph_push),
                )
                .route_layer(axum::middleware::from_fn(
                    sync_admission::require_sync_release,
                )),
        )
}

use super::contracts::{
    KnowledgeQuery, MutationRequest, PullRequest, PushRequest, QueryRequest, SyncLinkRequest,
    SyncUnbindRequest,
};

type RouteResult = Result<Json<Value>, Response>;

async fn query(
    Extension(lease): Extension<Arc<ActivePlatformPluginGenerationLeaseV2>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Json(request): Json<QueryRequest>,
) -> RouteResult {
    let operation = KnowledgeOperationV2::admit(lease, &authenticated, &request.scope)
        .map_err(IntoResponse::into_response)?;
    if !matches!(
        &request.query,
        KnowledgeQuery::Get { .. }
            | KnowledgeQuery::List { .. }
            | KnowledgeQuery::Changes { .. }
            | KnowledgeQuery::Change { .. }
    ) {
        operation
            .authority
            .require_sync_release()
            .map_err(IntoResponse::into_response)?;
    }
    let result = match request.query {
        KnowledgeQuery::RemoteBaseline { id } => {
            json!({"version":operation.remote_baseline(&id).await.map_err(IntoResponse::into_response)?})
        }
        KnowledgeQuery::PullConflictContext { id } => {
            json!({"context":operation.pull_conflict_context(&id).await.map_err(IntoResponse::into_response)?})
        }
        KnowledgeQuery::ResolutionHistory { id, limit } => {
            validate_limit(limit).map_err(invalid_page)?;
            json!({"items":operation.resolution_history(&id, limit).await.map_err(IntoResponse::into_response)?})
        }
        KnowledgeQuery::PullConflicts { limit } => {
            validate_limit(limit).map_err(invalid_page)?;
            json!({"items":operation.pull_conflicts(limit).await.map_err(IntoResponse::into_response)?})
        }
        KnowledgeQuery::PushConflicts { limit } => {
            validate_limit(limit).map_err(invalid_page)?;
            json!({"items":operation.push_conflicts(limit).await.map_err(IntoResponse::into_response)?})
        }
        KnowledgeQuery::SyncStatus {} => {
            json!({"status":operation.sync_status().await.map_err(IntoResponse::into_response)?})
        }
        KnowledgeQuery::SyncOutbox {
            after_sequence,
            limit,
        } => {
            validate_limit(limit).map_err(invalid_page)?;
            let items = operation
                .sync_outbox(after_sequence, limit)
                .await
                .map_err(IntoResponse::into_response)?;
            let next_sequence = items
                .last()
                .map_or(after_sequence, |item| item.local_change.sequence);
            json!({"items":items,"next_sequence":next_sequence})
        }
        KnowledgeQuery::Get { id } => {
            json!({"memory": operation.get(&id).await.map_err(IntoResponse::into_response)?.ok_or_else(not_found)?})
        }
        KnowledgeQuery::List { limit, offset } => {
            validate_limit(limit).map_err(invalid_page)?;
            let mut items = operation
                .list(limit + 1, offset)
                .await
                .map_err(IntoResponse::into_response)?;
            let has_more = items.len() > limit;
            items.truncate(limit);
            json!({"items": items, "offset": offset, "limit": limit, "has_more": has_more})
        }
        KnowledgeQuery::Changes {
            after_sequence,
            limit,
        } => {
            validate_limit(limit).map_err(invalid_page)?;
            let items = operation
                .changes(after_sequence, limit)
                .await
                .map_err(IntoResponse::into_response)?;
            let next_sequence = items
                .last()
                .map_or(after_sequence, |change| change.sequence);
            json!({"items": items, "next_sequence": next_sequence})
        }
        KnowledgeQuery::Change { sequence } => {
            json!({"change": operation.change(sequence).await.map_err(IntoResponse::into_response)?.ok_or_else(not_found)?})
        }
        KnowledgeQuery::GraphPullConflicts { limit } => {
            validate_limit(limit).map_err(invalid_page)?;
            json!({"items":operation.graph_pull_conflicts(limit).await.map_err(IntoResponse::into_response)?})
        }
        KnowledgeQuery::GraphPushConflicts { limit } => {
            validate_limit(limit).map_err(invalid_page)?;
            json!({"items":operation.graph_push_conflicts(limit).await.map_err(IntoResponse::into_response)?})
        }
        KnowledgeQuery::GraphPullConflictContext { id } => {
            json!({"context":operation.graph_pull_conflict_context(&id).await.map_err(IntoResponse::into_response)?})
        }
        KnowledgeQuery::GraphResolutionHistory { id, limit } => {
            validate_limit(limit).map_err(invalid_page)?;
            json!({"items":operation.graph_resolution_history(&id, limit).await.map_err(IntoResponse::into_response)?})
        }
        KnowledgeQuery::RemoteGraphBaseline { id } => {
            json!({"version":operation.remote_graph_baseline(&id).await.map_err(IntoResponse::into_response)?})
        }
        KnowledgeQuery::SyncedGraphProjection { id } => {
            json!({"projection":operation.synced_graph_projection(&id).await.map_err(IntoResponse::into_response)?})
        }
        KnowledgeQuery::SyncedGraphProjections { limit, offset } => {
            validate_limit(limit).map_err(invalid_page)?;
            json!({"items":operation.synced_graph_projections(limit, offset).await.map_err(IntoResponse::into_response)?})
        }
    };
    Ok(Json(
        json!({"contract_version": VERSION, "scope": request.scope, "result": result}),
    ))
}

async fn mutate(
    Extension(lease): Extension<Arc<ActivePlatformPluginGenerationLeaseV2>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    headers: HeaderMap,
    Json(request): Json<MutationRequest>,
) -> RouteResult {
    let operation = KnowledgeOperationV2::admit(lease, &authenticated, &request.scope)
        .map_err(IntoResponse::into_response)?;
    let key = headers
        .get("idempotency-key")
        .and_then(|value| value.to_str().ok())
        .filter(|value| !value.is_empty() && value.len() <= 512 && *value == value.trim())
        .ok_or_else(|| {
            rejection(
                StatusCode::BAD_REQUEST,
                "knowledge_idempotency_key_required",
                "a bounded idempotency key is required",
            )
        })?;
    match &request.mutation {
        MemoryMutation::Create { memory } => {
            if memory.author_id != authenticated.user.user_id {
                return Err(KnowledgeAuthorityErrorV2::Forbidden.into_response());
            }
        }
        MemoryMutation::Update {
            expected_revision, ..
        }
        | MemoryMutation::Delete {
            expected_revision, ..
        } => {
            let header_revision = headers
                .get("x-expected-revision")
                .and_then(|value| value.to_str().ok())
                .and_then(|value| value.parse::<u32>().ok())
                .ok_or_else(|| {
                    rejection(
                        StatusCode::PRECONDITION_REQUIRED,
                        "knowledge_expected_revision_required",
                        "the expected revision header is required",
                    )
                })?;
            if header_revision != *expected_revision {
                return Err(rejection(
                    StatusCode::BAD_REQUEST,
                    "knowledge_revision_payload_mismatch",
                    "the revision header must match the mutation",
                ));
            }
        }
    }
    let outcome = operation
        .mutate(key, request.mutation)
        .await
        .map_err(IntoResponse::into_response)?;
    Ok(Json(
        json!({"contract_version": VERSION, "scope": request.scope, "result": {
            "receipt": outcome.receipt, "replayed": outcome.replayed, "processing_status": "accepted"
        }}),
    ))
}

async fn configure_sync_link(
    Extension(lease): Extension<Arc<ActivePlatformPluginGenerationLeaseV2>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Json(request): Json<SyncLinkRequest>,
) -> RouteResult {
    let operation = KnowledgeOperationV2::admit(lease, &authenticated, &request.scope)
        .map_err(IntoResponse::into_response)?;
    let status = operation
        .configure_sync_link(request.link)
        .await
        .map_err(IntoResponse::into_response)?;
    Ok(Json(
        json!({"contract_version":VERSION,"scope":request.scope,"result": {
            "status":status,"association_state":"configured","remote_authorization":"unverified"
        }}),
    ))
}

async fn unbind(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(lease): Extension<Arc<ActivePlatformPluginGenerationLeaseV2>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Json(request): Json<SyncUnbindRequest>,
) -> RouteResult {
    let operation = KnowledgeOperationV2::admit(lease, &authenticated, &request.scope)
        .map_err(IntoResponse::into_response)?
        .admit_capability(&state, &authenticated, "sync_unbind")
        .map_err(IntoResponse::into_response)?;
    let result = operation
        .sync_unbind(&state, &authenticated, request.policy)
        .await
        .map_err(IntoResponse::into_response)?;
    Ok(Json(
        json!({"contract_version":VERSION,"scope":request.scope,"result":result}),
    ))
}

async fn push_once(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(lease): Extension<Arc<ActivePlatformPluginGenerationLeaseV2>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Json(request): Json<PushRequest>,
) -> RouteResult {
    let operation = KnowledgeOperationV2::admit(lease, &authenticated, &request.scope)
        .map_err(IntoResponse::into_response)?;
    let broker = state
        .platform_plugin_authority_v2
        .trusted_sessions()
        .ok_or_else(|| KnowledgeAuthorityErrorV2::TransportUnavailable.into_response())?;
    let result = operation
        .push_once(&broker)
        .await
        .map_err(IntoResponse::into_response)?;
    // Derived records ride the same drain loop: once the memory outbox is
    // empty, one pending graph record is pushed per call. Receipts share the
    // memory receipt wire shape, so the response contract is unchanged.
    let result = match result {
        Some(receipt) => Some(json!(receipt)),
        None => operation
            .graph_push_once(&broker)
            .await
            .map_err(IntoResponse::into_response)?
            .map(|receipt| json!(receipt)),
    };
    Ok(Json(
        json!({"contract_version":VERSION,"scope":request.scope,"result":result}),
    ))
}

async fn pull_once(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(lease): Extension<Arc<ActivePlatformPluginGenerationLeaseV2>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Json(request): Json<PullRequest>,
) -> RouteResult {
    let operation = KnowledgeOperationV2::admit(lease, &authenticated, &request.scope)
        .map_err(IntoResponse::into_response)?;
    let broker = state
        .platform_plugin_authority_v2
        .trusted_sessions()
        .ok_or_else(|| KnowledgeAuthorityErrorV2::TransportUnavailable.into_response())?;
    let result = operation
        .pull_once(&broker)
        .await
        .map_err(IntoResponse::into_response)?;
    // Once the memory stream is drained at the current cursor, the same call
    // advances the derived-record stream. Both receipts share one wire shape.
    let result = if result.applied == 0 && result.conflicts == 0 && !result.has_more {
        let graph = operation
            .graph_pull_once(&broker)
            .await
            .map_err(IntoResponse::into_response)?;
        json!(graph)
    } else {
        json!(result)
    };
    Ok(Json(
        json!({"contract_version":VERSION,"scope":request.scope,"result":result}),
    ))
}

fn validate_limit(limit: usize) -> Result<(), &'static str> {
    if (1..=200).contains(&limit) {
        return Ok(());
    }
    Err("page size must be between 1 and 200")
}

fn invalid_page(message: &'static str) -> Response {
    rejection(
        StatusCode::UNPROCESSABLE_ENTITY,
        "knowledge_page_size_invalid",
        message,
    )
}

fn not_found() -> Response {
    KnowledgeAuthorityErrorV2::Knowledge(KnowledgeError::NotFound).into_response()
}

fn rejection(status: StatusCode, code: &str, message: &str) -> Response {
    (
        status,
        Json(json!({"error": {"code": code, "message": message, "target": "desktop-sidecar"}})),
    )
        .into_response()
}

impl IntoResponse for KnowledgeAuthorityErrorV2 {
    fn into_response(self) -> Response {
        let (status, code, message) = match self {
            Self::EmbeddingUnavailable => (
                StatusCode::SERVICE_UNAVAILABLE,
                "knowledge_embedding_provider_unavailable",
                "the selected embedding provider is unavailable",
            ),
            Self::ProcessingUnavailable => (
                StatusCode::SERVICE_UNAVAILABLE,
                "knowledge_processing_provider_unavailable",
                "the workspace extraction provider is unavailable",
            ),
            Self::CloudConnectionMismatch => (
                StatusCode::CONFLICT,
                "knowledge_sync_connection_mismatch",
                "the cloud connection must be observed again",
            ),
            Self::CloudGenerationMismatch => (
                StatusCode::PRECONDITION_FAILED,
                "knowledge_sync_cloud_generation_mismatch",
                "the cloud synchronization generation must be observed again",
            ),
            Self::SyncNotEnrolled => (
                StatusCode::CONFLICT,
                "knowledge_sync_not_enrolled",
                "the cloud project must be explicitly enrolled",
            ),
            Self::TransportUnavailable => (
                StatusCode::SERVICE_UNAVAILABLE,
                "knowledge_sync_transport_unavailable",
                "trusted cloud synchronization transport is unavailable",
            ),
            Self::RemoteRejected => (
                StatusCode::BAD_GATEWAY,
                "knowledge_sync_remote_failed",
                "cloud synchronization request failed",
            ),
            Self::ReleaseClosed => (
                StatusCode::SERVICE_UNAVAILABLE,
                "knowledge_release_closed",
                "knowledge and synchronization release is closed",
            ),
            Self::Disposed => (
                StatusCode::SERVICE_UNAVAILABLE,
                "knowledge_generation_disposed",
                "knowledge authority is disposed",
            ),
            Self::ScopeMismatch => (
                StatusCode::FORBIDDEN,
                "knowledge_scope_mismatch",
                "request is outside the authenticated workspace",
            ),
            Self::GenerationMismatch => (
                StatusCode::CONFLICT,
                "knowledge_generation_mismatch",
                "request generation is stale",
            ),
            Self::Forbidden => (
                StatusCode::FORBIDDEN,
                "knowledge_write_forbidden",
                "knowledge mutation permission required",
            ),
            Self::Service(_) => (
                StatusCode::SERVICE_UNAVAILABLE,
                "local_project_memories_authority_unavailable",
                "knowledge service is unavailable in this generation",
            ),
            Self::Knowledge(KnowledgeError::InvalidInput) => (
                StatusCode::UNPROCESSABLE_ENTITY,
                "knowledge_invalid_input",
                "knowledge input is invalid",
            ),
            Self::Knowledge(KnowledgeError::NotFound) => (
                StatusCode::NOT_FOUND,
                "knowledge_not_found",
                "knowledge object was not found",
            ),
            Self::Knowledge(KnowledgeError::Conflict) => (
                StatusCode::CONFLICT,
                "knowledge_revision_conflict",
                "knowledge revision conflict",
            ),
            Self::Knowledge(KnowledgeError::IdempotencyConflict) => (
                StatusCode::CONFLICT,
                "knowledge_idempotency_conflict",
                "idempotency key belongs to a different request",
            ),
            Self::Knowledge(KnowledgeError::Storage(_)) | Self::Storage(_) => (
                StatusCode::INTERNAL_SERVER_ERROR,
                "knowledge_storage_error",
                "knowledge storage operation failed",
            ),
        };
        rejection(status, code, message)
    }
}
