use axum::extract::OriginalUri;
use chrono::DateTime;
use serde::de::DeserializeOwned;

use super::super::*;
use super::{ensure_body_scope, unavailable};
use crate::local_runtime::search_projection::{
    self, LocalSearchPage, LocalSearchProjectionState, LocalSearchQuery,
};

const LOCAL_SEARCH_SERVICE_VERSION: &str = "0.1.0";
const LOCAL_SEARCH_CONTRACT_VERSION: &str = "2.0.0";
const LOCAL_SEARCH_DEGRADED_REASON: &str = "local_embeddings_unavailable";

pub(super) fn router() -> Router<Arc<LocalRuntimeState>> {
    Router::new()
        .route(
            "/api/v1/search-enhanced/capabilities",
            get(search_capabilities),
        )
        .route("/api/v1/search-enhanced/advanced", post(advanced_search))
        .route(
            "/api/v1/search-enhanced/graph-traversal",
            post(graph_traversal_search),
        )
        .route("/api/v1/search-enhanced/temporal", post(temporal_search))
        .route("/api/v1/search-enhanced/faceted", post(faceted_search))
        .route("/api/v1/search-enhanced/community", post(community_search))
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct AdvancedSearchRequest {
    query: String,
    strategy: String,
    focal_node_uuid: Option<String>,
    reranker: Option<String>,
    limit: usize,
    tenant_id: String,
    project_id: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct TemporalSearchRequest {
    query: String,
    since: Option<String>,
    until: Option<String>,
    limit: usize,
    tenant_id: String,
    project_id: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct FacetedSearchRequest {
    query: String,
    entity_types: Vec<String>,
    tags: Vec<String>,
    since: Option<String>,
    limit: usize,
    offset: usize,
    tenant_id: String,
    project_id: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct GraphTraversalSearchRequest {
    start_entity_uuid: String,
    max_depth: usize,
    relationship_types: Vec<String>,
    limit: usize,
    tenant_id: String,
    project_id: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct CommunitySearchRequest {
    community_uuid: String,
    include_episodes: bool,
    limit: usize,
    tenant_id: String,
    project_id: String,
}

async fn search_capabilities(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
) -> LocalJsonResult {
    let projection = refresh(
        &state,
        &authenticated.workspace.tenant_id,
        &authenticated.workspace.project_id,
    )?;
    Ok(Json(json!({
        "service_version": LOCAL_SEARCH_SERVICE_VERSION,
        "contract_version": LOCAL_SEARCH_CONTRACT_VERSION,
        "mode": "keyword_degraded",
        "reason_code": projection_reason(&projection),
        "tenant_id": authenticated.workspace.tenant_id,
        "project_id": authenticated.workspace.project_id,
        "projection_revision": projection.revision,
        "backfill_cursor": projection.backfill_cursor,
        "supported_search_types": ["advanced", "temporal", "faceted"],
        "unavailable_search_types": ["graph_traversal", "community"],
    })))
}

async fn advanced_search(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    uri: OriginalUri,
    Json(body): Json<Value>,
) -> LocalJsonResult {
    ensure_body_scope(&authenticated, &body, true, true)?;
    let request = parse_request::<AdvancedSearchRequest>(body)?;
    validate_scope(&authenticated, &request.tenant_id, &request.project_id)?;
    validate_query(&request.query)?;
    validate_limit(request.limit)?;
    validate_required(&request.strategy, "local_search_strategy_invalid")?;
    validate_optional(&request.focal_node_uuid, "local_search_focal_node_invalid")?;
    validate_optional(&request.reranker, "local_search_reranker_invalid")?;
    let projection = refresh(&state, &request.tenant_id, &request.project_id)?;
    let page = run_search(
        &state,
        LocalSearchQuery {
            tenant_id: &request.tenant_id,
            project_id: &request.project_id,
            query: &request.query,
            since: None,
            until: None,
            entity_types: &[],
            tags: &[],
            limit: request.limit,
            offset: 0,
        },
    )?;
    search_response(&uri, "advanced", request.limit, 0, page, projection, false)
}

async fn temporal_search(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    uri: OriginalUri,
    Json(body): Json<Value>,
) -> LocalJsonResult {
    ensure_body_scope(&authenticated, &body, true, true)?;
    let request = parse_request::<TemporalSearchRequest>(body)?;
    validate_scope(&authenticated, &request.tenant_id, &request.project_id)?;
    validate_query(&request.query)?;
    validate_limit(request.limit)?;
    validate_date(&request.since)?;
    validate_date(&request.until)?;
    if request
        .since
        .as_ref()
        .zip(request.until.as_ref())
        .is_some_and(|(since, until)| since > until)
    {
        return validation_error("local_search_date_range_invalid");
    }
    let projection = refresh(&state, &request.tenant_id, &request.project_id)?;
    let page = run_search(
        &state,
        LocalSearchQuery {
            tenant_id: &request.tenant_id,
            project_id: &request.project_id,
            query: &request.query,
            since: request.since.as_deref(),
            until: request.until.as_deref(),
            entity_types: &[],
            tags: &[],
            limit: request.limit,
            offset: 0,
        },
    )?;
    search_response(&uri, "temporal", request.limit, 0, page, projection, false)
}

async fn faceted_search(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    uri: OriginalUri,
    Json(body): Json<Value>,
) -> LocalJsonResult {
    ensure_body_scope(&authenticated, &body, true, true)?;
    let request = parse_request::<FacetedSearchRequest>(body)?;
    validate_scope(&authenticated, &request.tenant_id, &request.project_id)?;
    validate_query(&request.query)?;
    validate_limit(request.limit)?;
    validate_date(&request.since)?;
    validate_list(&request.entity_types)?;
    validate_list(&request.tags)?;
    let projection = refresh(&state, &request.tenant_id, &request.project_id)?;
    let page = run_search(
        &state,
        LocalSearchQuery {
            tenant_id: &request.tenant_id,
            project_id: &request.project_id,
            query: &request.query,
            since: request.since.as_deref(),
            until: None,
            entity_types: &request.entity_types,
            tags: &request.tags,
            limit: request.limit,
            offset: request.offset,
        },
    )?;
    search_response(
        &uri,
        "faceted",
        request.limit,
        request.offset,
        page,
        projection,
        true,
    )
}

async fn graph_traversal_search(
    Extension(authenticated): Extension<AuthenticatedContext>,
    uri: OriginalUri,
    Json(body): Json<Value>,
) -> LocalJsonResult {
    ensure_body_scope(&authenticated, &body, true, true)?;
    let request = parse_request::<GraphTraversalSearchRequest>(body)?;
    validate_scope(&authenticated, &request.tenant_id, &request.project_id)?;
    validate_required(
        &request.start_entity_uuid,
        "local_search_start_entity_invalid",
    )?;
    if !(1..=5).contains(&request.max_depth) {
        return validation_error("local_search_max_depth_invalid");
    }
    validate_limit(request.limit)?;
    validate_list(&request.relationship_types)?;
    unavailable(
        &uri,
        "search_enhanced",
        "unavailable",
        "local_structured_graph_projection_unavailable",
    )
}

async fn community_search(
    Extension(authenticated): Extension<AuthenticatedContext>,
    uri: OriginalUri,
    Json(body): Json<Value>,
) -> LocalJsonResult {
    ensure_body_scope(&authenticated, &body, true, true)?;
    let request = parse_request::<CommunitySearchRequest>(body)?;
    validate_scope(&authenticated, &request.tenant_id, &request.project_id)?;
    validate_required(&request.community_uuid, "local_search_community_invalid")?;
    validate_limit(request.limit)?;
    let _ = request.include_episodes;
    unavailable(
        &uri,
        "search_enhanced",
        "unavailable",
        "local_structured_community_projection_unavailable",
    )
}

fn refresh(
    state: &LocalRuntimeState,
    tenant_id: &str,
    project_id: &str,
) -> Result<LocalSearchProjectionState, (StatusCode, Json<Value>)> {
    let mut connection = state
        .session_store
        .connection()
        .map_err(search_store_error)?;
    search_projection::refresh_projection(&mut connection, tenant_id, project_id)
        .map_err(search_store_error)
}

fn run_search(
    state: &LocalRuntimeState,
    query: LocalSearchQuery<'_>,
) -> Result<LocalSearchPage, (StatusCode, Json<Value>)> {
    let connection = state
        .session_store
        .connection()
        .map_err(search_store_error)?;
    search_projection::search(&connection, &query).map_err(search_store_error)
}

fn search_response(
    uri: &OriginalUri,
    search_type: &str,
    limit: usize,
    offset: usize,
    page: LocalSearchPage,
    projection: LocalSearchProjectionState,
    include_facets: bool,
) -> LocalJsonResult {
    let results = page
        .results
        .into_iter()
        .map(|result| {
            json!({
                "uuid": result.id,
                "title": result.title,
                "content": result.content,
                "score": result.score,
                "source": result.source,
                "type": result.result_type,
                "created_at": result.created_at,
                "tags": result.tags,
            })
        })
        .collect::<Vec<_>>();
    let facets = include_facets.then(|| {
        json!({
            "entity_types": page.facets,
            "total": page.total,
        })
    });
    Ok(Json(json!({
        "service_version": LOCAL_SEARCH_SERVICE_VERSION,
        "contract_version": LOCAL_SEARCH_CONTRACT_VERSION,
        "mode": "keyword_degraded",
        "reason_code": projection_reason(&projection),
        "projection_revision": projection.revision,
        "backfill_cursor": projection.backfill_cursor,
        "route": uri.path(),
        "results": results,
        "total": page.total,
        "search_type": search_type,
        "limit": limit,
        "offset": offset,
        "facets": facets,
    })))
}

fn projection_reason(projection: &LocalSearchProjectionState) -> &'static str {
    if projection.backfill_cursor.is_some() {
        "local_search_backfill_in_progress"
    } else {
        LOCAL_SEARCH_DEGRADED_REASON
    }
}

fn parse_request<T: DeserializeOwned>(body: Value) -> Result<T, (StatusCode, Json<Value>)> {
    serde_json::from_value(body).map_err(|_| validation_error_value("local_search_payload_invalid"))
}

fn validate_scope(
    authenticated: &AuthenticatedContext,
    tenant_id: &str,
    project_id: &str,
) -> Result<(), (StatusCode, Json<Value>)> {
    ensure_tenant_scope(authenticated, Some(tenant_id))?;
    ensure_project_scope(authenticated, Some(project_id))
}

fn validate_query(query: &str) -> Result<(), (StatusCode, Json<Value>)> {
    if query.trim().is_empty() || query.len() > 2_048 {
        return validation_error("local_search_query_invalid");
    }
    Ok(())
}

fn validate_limit(limit: usize) -> Result<(), (StatusCode, Json<Value>)> {
    if !(1..=200).contains(&limit) {
        return validation_error("local_search_limit_invalid");
    }
    Ok(())
}

fn validate_required(
    value: &str,
    reason_code: &'static str,
) -> Result<(), (StatusCode, Json<Value>)> {
    if value.trim().is_empty() || value.len() > 2_048 {
        return validation_error(reason_code);
    }
    Ok(())
}

fn validate_optional(
    value: &Option<String>,
    reason_code: &'static str,
) -> Result<(), (StatusCode, Json<Value>)> {
    if value
        .as_ref()
        .is_some_and(|value| value.trim().is_empty() || value.len() > 2_048)
    {
        return validation_error(reason_code);
    }
    Ok(())
}

fn validate_date(value: &Option<String>) -> Result<(), (StatusCode, Json<Value>)> {
    if value
        .as_ref()
        .is_some_and(|value| DateTime::parse_from_rfc3339(value).is_err())
    {
        return validation_error("local_search_date_invalid");
    }
    Ok(())
}

fn validate_list(values: &[String]) -> Result<(), (StatusCode, Json<Value>)> {
    if values.len() > 100
        || values
            .iter()
            .any(|value| value.trim().is_empty() || value.len() > 256)
    {
        return validation_error("local_search_filter_invalid");
    }
    Ok(())
}

fn validation_error<T>(reason_code: &'static str) -> Result<T, (StatusCode, Json<Value>)> {
    Err(validation_error_value(reason_code))
}

fn validation_error_value(reason_code: &'static str) -> (StatusCode, Json<Value>) {
    (
        StatusCode::UNPROCESSABLE_ENTITY,
        Json(json!({
            "contract_version": LOCAL_SEARCH_CONTRACT_VERSION,
            "reason_code": reason_code,
            "detail": "local search request is invalid",
        })),
    )
}

fn search_store_error(error: String) -> (StatusCode, Json<Value>) {
    eprintln!("local search projection error: {error}");
    (
        StatusCode::INTERNAL_SERVER_ERROR,
        Json(json!({
            "contract_version": LOCAL_SEARCH_CONTRACT_VERSION,
            "reason_code": "local_search_projection_failed",
            "detail": "local search projection is unavailable",
        })),
    )
}
