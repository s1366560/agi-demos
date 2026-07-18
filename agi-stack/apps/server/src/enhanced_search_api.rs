//! P4 enhanced-search REST foundation over the portable [`GraphStore`] port.
//!
//! Query-style endpoints support the Python-compatible `project_id` optional
//! contract by fanning out across the current user's accessible project list
//! when `project_id` is omitted. Community and graph-traversal lookups can also
//! resolve an omitted `project_id` by searching only identity-visible projects
//! for the stable community or start-entity handle. FastAPI-style error
//! envelopes are preserved for safe gateway rollback.

use std::collections::{BTreeMap, BTreeSet};

use axum::{
    extract::State,
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::{get, post},
    Extension, Json, Router,
};
use futures_util::{stream, StreamExt};
use serde_json::{json, Value};

use agistack_core::model::{GraphEntity, Relationship, Subgraph};
use agistack_core::{detect_communities, CommunityEdge, DEFAULT_MIN_COMMUNITY_SIZE};

use crate::auth::Identity;
use crate::identity::{IdentityError, ProjectListInput};
use crate::AppState;

#[cfg(test)]
mod tests;
mod views;

use views::*;

#[derive(Debug)]
struct SearchApiError {
    status: StatusCode,
    detail: String,
}

impl SearchApiError {
    fn new(status: StatusCode, detail: impl Into<String>) -> Self {
        Self {
            status,
            detail: detail.into(),
        }
    }

    fn bad_request(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::BAD_REQUEST, detail)
    }

    fn forbidden(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::FORBIDDEN, detail)
    }

    fn not_found(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::NOT_FOUND, detail)
    }

    fn internal(detail: impl std::fmt::Display) -> Self {
        Self::new(StatusCode::INTERNAL_SERVER_ERROR, detail.to_string())
    }
}

impl IntoResponse for SearchApiError {
    fn into_response(self) -> Response {
        (self.status, Json(json!({ "detail": self.detail }))).into_response()
    }
}

type SearchApiResult<T> = Result<T, SearchApiError>;

const FANOUT_PROJECT_PAGE_SIZE: i64 = 100;
const FANOUT_PROJECT_PAGE_LIMIT: i64 = 10;
/// Bounded concurrency for the per-project graph fan-out when `project_id` is
/// omitted: wide enough to hide per-project round-trip latency, narrow enough
/// to avoid flooding the store on wide scopes.
const SCOPE_FANOUT_CONCURRENCY: usize = 8;

#[derive(Debug, Clone)]
struct SearchScope {
    project_ids: Vec<String>,
    tenant_id: Option<String>,
    fanout: bool,
}

impl SearchScope {
    fn explicit(project_id: &str) -> Self {
        Self {
            project_ids: vec![project_id.to_string()],
            tenant_id: None,
            fanout: false,
        }
    }

    fn fanout(project_ids: Vec<String>, tenant_id: Option<&str>) -> Self {
        Self {
            project_ids,
            tenant_id: tenant_id.map(str::to_string),
            fanout: true,
        }
    }

    fn is_fanout(&self) -> bool {
        self.fanout
    }

    fn explicit_project_id(&self) -> Option<&str> {
        if self.fanout {
            None
        } else {
            self.project_ids.first().map(String::as_str)
        }
    }

    fn response_scope(&self) -> Value {
        json!({
            "fanout": true,
            "project_ids": self.project_ids.clone(),
            "tenant_id": self.tenant_id.clone(),
        })
    }

    fn filters_applied(&self) -> Value {
        if let Some(project_id) = self.explicit_project_id() {
            json!({ "project_id": project_id })
        } else {
            json!({
                "project_ids": self.project_ids.clone(),
                "tenant_id": self.tenant_id.clone(),
            })
        }
    }
}

fn rfc3339(ms: i64) -> String {
    chrono::DateTime::<chrono::Utc>::from_timestamp_millis(ms)
        .unwrap_or(chrono::DateTime::<chrono::Utc>::UNIX_EPOCH)
        .to_rfc3339_opts(chrono::SecondsFormat::Secs, true)
}

fn parse_iso_ms(value: Option<&str>, field: &str) -> SearchApiResult<Option<i64>> {
    let Some(value) = value.filter(|v| !v.trim().is_empty()) else {
        return Ok(None);
    };
    chrono::DateTime::parse_from_rfc3339(value)
        .map(|dt| Some(dt.timestamp_millis()))
        .map_err(|_| {
            if field == "since" {
                SearchApiError::bad_request("Invalid 'since' datetime format")
            } else {
                SearchApiError::bad_request("Invalid 'until' datetime format")
            }
        })
}

fn require_query(query: &str) -> SearchApiResult<()> {
    if query.trim().is_empty() {
        Err(SearchApiError::bad_request("Query is required"))
    } else {
        Ok(())
    }
}

fn cap_limit(limit: Option<usize>) -> usize {
    limit.unwrap_or(50).clamp(1, 200)
}

async fn ensure_project_access(
    app: &AppState,
    identity: &Identity,
    project_id: &str,
) -> SearchApiResult<()> {
    let allowed = app
        .auth
        .can_access_project(&identity.user_id, project_id)
        .await
        .map_err(SearchApiError::internal)?;
    if allowed {
        Ok(())
    } else {
        Err(SearchApiError::forbidden("Access denied to project"))
    }
}

fn identity_error(err: IdentityError) -> SearchApiError {
    SearchApiError::new(err.status, err.detail)
}

fn nonblank(value: Option<&str>) -> Option<&str> {
    value.map(str::trim).filter(|value| !value.is_empty())
}

async fn resolve_search_scope(
    app: &AppState,
    identity: &Identity,
    project_id: Option<&str>,
    tenant_id: Option<&str>,
) -> SearchApiResult<SearchScope> {
    if let Some(project_id) = nonblank(project_id) {
        ensure_project_access(app, identity, project_id).await?;
        return Ok(SearchScope::explicit(project_id));
    }

    let tenant_id = nonblank(tenant_id);
    let mut project_ids = Vec::new();
    let mut page = 1;
    while page <= FANOUT_PROJECT_PAGE_LIMIT {
        let page_result = app
            .identity
            .list_projects(
                &identity.user_id,
                ProjectListInput {
                    tenant_id,
                    search: None,
                    visibility: "all",
                    owner_id: None,
                    page,
                    page_size: FANOUT_PROJECT_PAGE_SIZE,
                },
            )
            .await
            .map_err(identity_error)?;
        let returned = page_result.projects.len() as i64;
        project_ids.extend(page_result.projects.into_iter().map(|project| project.id));
        if returned == 0 || project_ids.len() as i64 >= page_result.total {
            break;
        }
        page += 1;
    }
    project_ids.sort();
    project_ids.dedup();
    Ok(SearchScope::fanout(project_ids, tenant_id))
}

async fn search_scope_entities(
    app: &AppState,
    scope: &SearchScope,
    query: &str,
    per_project_limit: usize,
) -> SearchApiResult<Vec<GraphEntity>> {
    // Query projects concurrently, but keep the sequential contract: `buffered`
    // yields per-project results in scope order, so hits concatenate in scope
    // order and the first error in scope order aborts the merge.
    let per_project: Vec<_> = stream::iter(
        scope
            .project_ids
            .iter()
            .cloned()
            .map(|project_id| {
                let graph = app.graph.clone();
                async move {
                    graph
                        .search_entities(&project_id, query, per_project_limit)
                        .await
                }
            }),
    )
    .buffered(SCOPE_FANOUT_CONCURRENCY)
    .collect()
    .await;

    let mut entities = Vec::new();
    for hits in per_project {
        entities.append(&mut hits.map_err(SearchApiError::internal)?);
    }
    Ok(entities)
}

async fn find_start_entity_project_in_scope(
    app: &AppState,
    scope: &SearchScope,
    start_entity_uuid: &str,
) -> SearchApiResult<Option<String>> {
    // Probe all scope projects concurrently, then walk the results in scope
    // order so the selection stays deterministic: the first error in scope
    // order aborts, otherwise the first project holding the entity wins.
    let probes: Vec<_> = stream::iter(scope.project_ids.iter().cloned().map(|project_id| {
        let graph = app.graph.clone();
        async move { graph.get_entity(&project_id, start_entity_uuid).await }
    }))
    .buffered(SCOPE_FANOUT_CONCURRENCY)
    .collect()
    .await;

    for (project_id, probe) in scope.project_ids.iter().zip(probes) {
        if probe.map_err(SearchApiError::internal)?.is_some() {
            return Ok(Some(project_id.clone()));
        }
    }
    Ok(None)
}

fn add_fanout_scope(body: &mut Value, scope: &SearchScope) {
    if scope.is_fanout() {
        body["scope"] = scope.response_scope();
    }
}

fn result_from_entity(
    entity: GraphEntity,
    score: f32,
    kind: &str,
    include_project_id: bool,
) -> Value {
    let project_id = entity.project_id.clone();
    let mut result =
        serde_json::to_value(SearchResult::from_entity(entity, score, kind)).unwrap_or(Value::Null);
    if include_project_id {
        result["metadata"]["project_id"] = Value::String(project_id);
    }
    result
}

fn advanced_result(entity: GraphEntity, score: f32, include_project_id: bool) -> Value {
    let project_id = entity.project_id.clone();
    let mut result = SearchResult::advanced(entity, score);
    if include_project_id {
        result["metadata"]["project_id"] = Value::String(project_id);
    }
    result
}

async fn search_advanced(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Json(req): Json<AdvancedSearchRequest>,
) -> SearchApiResult<Json<Value>> {
    require_query(&req.query)?;
    let since_ms = parse_iso_ms(req.since.as_deref(), "since")?;
    let _ = (&req.focal_node_uuid, &req.reranker);
    let limit = cap_limit(req.limit);
    let scope = resolve_search_scope(
        &app,
        &identity,
        req.project_id.as_deref(),
        req.tenant_id.as_deref(),
    )
    .await?;

    let entities = search_scope_entities(&app, &scope, req.query.trim(), limit).await?;
    let results: Vec<Value> = entities
        .into_iter()
        .filter(|entity| since_ms.is_none_or(|since| entity.created_at_ms >= since))
        .take(limit)
        .enumerate()
        .map(|(idx, entity)| advanced_result(entity, positional_score(idx), scope.is_fanout()))
        .collect();
    let mut body = json!({
        "results": results,
        "total": results.len(),
        "search_type": "advanced",
        "strategy": req.strategy,
    });
    add_fanout_scope(&mut body, &scope);
    Ok(Json(body))
}

async fn search_graph_traversal(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Json(req): Json<TraversalSearchRequest>,
) -> SearchApiResult<Json<Value>> {
    let scope = resolve_search_scope(
        &app,
        &identity,
        req.project_id.as_deref(),
        req.tenant_id.as_deref(),
    )
    .await?;
    let Some(project_id) =
        find_start_entity_project_in_scope(&app, &scope, &req.start_entity_uuid).await?
    else {
        return Err(SearchApiError::not_found("Entity not found"));
    };
    let include_project_id = scope.is_fanout();

    let depth = req.max_depth.clamp(1, 5);
    let limit = cap_limit(req.limit);
    let graph = app
        .graph
        .subgraph(&project_id, &req.start_entity_uuid, depth)
        .await
        .map_err(SearchApiError::internal)?;
    let allowed_relationships: Option<BTreeSet<String>> = req
        .relationship_types
        .map(|items| items.into_iter().collect());
    let reachable = reachable_entities(graph, &req.start_entity_uuid, allowed_relationships);
    let items: Vec<Value> = reachable
        .into_iter()
        .take(limit)
        .map(|entity| {
            let created_at = rfc3339(entity.created_at_ms);
            let project_id = entity.project_id;
            let uuid = entity.uuid;
            let name = entity.name;
            let entity_type = entity.entity_type;
            let mut item = json!({
                "uuid": uuid.clone(),
                "name": name.clone(),
                "type": entity_type.clone(),
                "summary": entity.summary,
                "content": "",
                "created_at": created_at.clone(),
                "metadata": {
                    "uuid": uuid,
                    "name": name,
                    "type": entity_type,
                    "created_at": created_at,
                },
            });
            if include_project_id {
                item["metadata"]["project_id"] = Value::String(project_id);
            }
            item
        })
        .collect();

    let mut body = json!({
        "results": items,
        "total": items.len(),
        "search_type": "graph_traversal",
    });
    add_fanout_scope(&mut body, &scope);
    Ok(Json(body))
}

async fn search_community(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Json(req): Json<CommunitySearchRequest>,
) -> SearchApiResult<Json<Value>> {
    let scope = resolve_search_scope(&app, &identity, req.project_id.as_deref(), None).await?;
    let _ = req.include_episodes;
    let limit = cap_limit(req.limit);
    let Some((_project_id, _community, members)) =
        find_community_in_scope(&app, &scope, &req.community_uuid).await?
    else {
        return Err(SearchApiError::not_found("Community not found"));
    };
    let items: Vec<Value> = members
        .into_iter()
        .take(limit)
        .enumerate()
        .map(|(idx, entity)| {
            result_from_entity(entity, positional_score(idx), "entity", scope.is_fanout())
        })
        .collect();
    let mut body = json!({
        "results": items,
        "total": items.len(),
        "search_type": "community",
    });
    add_fanout_scope(&mut body, &scope);
    Ok(Json(body))
}

async fn search_temporal(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Json(req): Json<TemporalSearchRequest>,
) -> SearchApiResult<Json<Value>> {
    require_query(&req.query)?;
    let since_ms = parse_iso_ms(req.since.as_deref(), "since")?;
    let until_ms = parse_iso_ms(req.until.as_deref(), "until")?;
    let limit = cap_limit(req.limit);
    let scope = resolve_search_scope(
        &app,
        &identity,
        req.project_id.as_deref(),
        req.tenant_id.as_deref(),
    )
    .await?;

    let entities = search_scope_entities(&app, &scope, req.query.trim(), limit).await?;
    let results: Vec<Value> = entities
        .into_iter()
        .filter(|entity| since_ms.is_none_or(|since| entity.created_at_ms >= since))
        .filter(|entity| until_ms.is_none_or(|until| entity.created_at_ms <= until))
        .take(limit)
        .enumerate()
        .map(|(idx, entity)| {
            result_from_entity(entity, positional_score(idx), "entity", scope.is_fanout())
        })
        .collect();
    let mut body = json!({
        "results": results,
        "total": results.len(),
        "search_type": "temporal",
        "time_range": {
            "since": req.since,
            "until": req.until,
        },
    });
    add_fanout_scope(&mut body, &scope);
    Ok(Json(body))
}

async fn search_faceted(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Json(req): Json<FacetedSearchRequest>,
) -> SearchApiResult<Json<Value>> {
    require_query(&req.query)?;
    let _ = &req.tags;
    let since_ms = parse_iso_ms(req.since.as_deref(), "since")?;
    let limit = cap_limit(req.limit);
    let offset = req.offset.unwrap_or(0);
    let scope = resolve_search_scope(
        &app,
        &identity,
        req.project_id.as_deref(),
        req.tenant_id.as_deref(),
    )
    .await?;
    let entity_filter: Option<BTreeSet<String>> = req
        .entity_types
        .as_ref()
        .map(|items| items.iter().cloned().collect());
    let has_post_filters = since_ms.is_some()
        || entity_filter
            .as_ref()
            .is_some_and(|types| !types.is_empty());
    let fetch = if has_post_filters {
        1_000
    } else {
        limit.saturating_add(offset).clamp(1, 1_000)
    };

    let mut entities = search_scope_entities(&app, &scope, req.query.trim(), fetch).await?;
    entities.retain(|entity| {
        since_ms.is_none_or(|since| entity.created_at_ms >= since)
            && entity_filter
                .as_ref()
                .is_none_or(|types| types.contains(&entity.entity_type))
    });
    let total = entities.len();
    let paged: Vec<GraphEntity> = entities.into_iter().skip(offset).take(limit).collect();
    let mut entity_type_counts: BTreeMap<String, usize> = BTreeMap::new();
    for entity in &paged {
        *entity_type_counts
            .entry(entity.entity_type.clone())
            .or_insert(0) += 1;
    }
    let results: Vec<Value> = paged
        .into_iter()
        .enumerate()
        .map(|(idx, entity)| {
            result_from_entity(entity, positional_score(idx), "entity", scope.is_fanout())
        })
        .collect();

    let mut body = json!({
        "results": results,
        "facets": {
            "entity_types": entity_type_counts,
            "total": results.len(),
        },
        "total": total,
        "limit": limit,
        "offset": offset,
        "search_type": "faceted",
    });
    add_fanout_scope(&mut body, &scope);
    Ok(Json(body))
}

async fn search_capabilities() -> Json<Value> {
    Json(json!({
        "search_types": {
            "semantic": {
                "description": "Semantic search using embeddings and hybrid retrieval",
                "endpoint": "/api/v1/memory/search",
                "parameters": {
                    "query": "string (required)",
                    "limit": "integer (1-100)",
                    "tenant_id": "string (optional)",
                    "project_id": "string (optional)",
                },
            },
            "graph_traversal": {
                "description": "Search by traversing the knowledge graph",
                "endpoint": "/api/v1/search-enhanced/graph-traversal",
                "parameters": {
                    "start_entity_uuid": "string (required)",
                    "max_depth": "integer (1-5)",
                    "relationship_types": "array of strings (optional)",
                    "limit": "integer (1-200)",
                    "project_id": "string (optional; omitted fans out across accessible projects to resolve start entity)",
                },
            },
            "community": {
                "description": "Search within a specific community",
                "endpoint": "/api/v1/search-enhanced/community",
                "parameters": {
                    "community_uuid": "string (required)",
                    "limit": "integer (1-200)",
                    "include_episodes": "boolean",
                    "project_id": "string (optional; omitted fans out across accessible projects)",
                },
            },
            "temporal": {
                "description": "Search within a time range",
                "endpoint": "/api/v1/search-enhanced/temporal",
                "parameters": {
                    "query": "string (required)",
                    "since": "ISO datetime string (optional)",
                    "until": "ISO datetime string (optional)",
                    "limit": "integer (1-200)",
                },
            },
            "faceted": {
                "description": "Search with faceted filtering",
                "endpoint": "/api/v1/search-enhanced/faceted",
                "parameters": {
                    "query": "string (required)",
                    "entity_types": "array of strings (optional)",
                    "tags": "array of strings (optional)",
                    "since": "ISO datetime string (optional)",
                    "limit": "integer (1-200)",
                    "offset": "integer (0+)",
                },
            },
        },
        "filters": {
            "entity_types": [
                "Person",
                "Organization",
                "Product",
                "Location",
                "Event",
                "Concept",
                "Custom",
            ],
            "relationship_types": [
                "RELATES_TO",
                "MENTIONS",
                "PART_OF",
                "CONTAINS",
                "BELONGS_TO",
                "OWNS",
                "LOCATED_AT",
            ],
        },
    }))
}

async fn memory_search(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Json(req): Json<MemorySearchRequest>,
) -> SearchApiResult<Json<Value>> {
    require_query(&req.query)?;
    let limit = req.limit.unwrap_or(10).clamp(1, 200);
    let scope = resolve_search_scope(
        &app,
        &identity,
        req.project_id.as_deref(),
        req.tenant_id.as_deref(),
    )
    .await?;
    let entities = search_scope_entities(&app, &scope, req.query.trim(), limit).await?;
    let results: Vec<Value> = entities
        .into_iter()
        .take(limit)
        .enumerate()
        .map(|(idx, entity)| {
            result_from_entity(entity, positional_score(idx), "entity", scope.is_fanout())
        })
        .collect();
    let mut body = json!({
        "results": results,
        "total": results.len(),
        "query": req.query,
        "filters_applied": scope.filters_applied(),
        "search_metadata": {
            "strategy": "hybrid_search",
            "limit": limit,
        },
    });
    add_fanout_scope(&mut body, &scope);
    Ok(Json(body))
}

fn positional_score(idx: usize) -> f32 {
    (1.0 - (idx as f32 * 0.01)).max(0.0)
}

fn reachable_entities(
    graph: Subgraph,
    seed: &str,
    relationship_types: Option<BTreeSet<String>>,
) -> Vec<GraphEntity> {
    let by_uuid: BTreeMap<String, GraphEntity> = graph
        .entities
        .into_iter()
        .map(|entity| (entity.uuid.clone(), entity))
        .collect();
    let mut ids = BTreeSet::new();
    ids.insert(seed.to_string());
    for rel in graph.relationships {
        if relationship_types
            .as_ref()
            .is_some_and(|types| !types.contains(&rel.relation_type))
        {
            continue;
        }
        ids.insert(rel.source_uuid);
        ids.insert(rel.target_uuid);
    }
    ids.into_iter()
        .filter_map(|uuid| by_uuid.get(&uuid).cloned())
        .collect()
}

async fn project_snapshot(app: &AppState, project_id: &str) -> SearchApiResult<Subgraph> {
    let seeds = app
        .graph
        .search_entities(project_id, "", 1_000)
        .await
        .map_err(SearchApiError::internal)?;
    merge_subgraphs(app, project_id, &seeds).await
}

async fn merge_subgraphs(
    app: &AppState,
    project_id: &str,
    seeds: &[GraphEntity],
) -> SearchApiResult<Subgraph> {
    let seed_ids: Vec<String> = seeds.iter().map(|seed| seed.uuid.clone()).collect();
    crate::graph_api::merge_seed_subgraphs(&app.graph, project_id, &seed_ids, 1, 1_000)
        .await
        .map_err(SearchApiError::internal)
}

fn relationship_weight(rel: &Relationship) -> f64 {
    if rel.score.is_finite() && rel.score > 0.0 {
        rel.score as f64
    } else {
        1.0
    }
}

fn community_id(project_id: &str, name: &str, members: &[String]) -> String {
    let mut hash = 0xcbf2_9ce4_8422_2325_u64;
    for part in std::iter::once(project_id)
        .chain(std::iter::once(name))
        .chain(members.iter().map(String::as_str))
    {
        for byte in part.as_bytes() {
            hash ^= *byte as u64;
            hash = hash.wrapping_mul(0x0000_0100_0000_01b3);
        }
        hash ^= 0xff;
        hash = hash.wrapping_mul(0x0000_0100_0000_01b3);
    }
    format!("community_{hash:016x}")
}

async fn find_community(
    app: &AppState,
    project_id: &str,
    community_uuid: &str,
) -> SearchApiResult<Option<(Value, Vec<GraphEntity>)>> {
    let snapshot = project_snapshot(app, project_id).await?;
    let nodes: Vec<String> = snapshot
        .entities
        .iter()
        .map(|entity| entity.uuid.clone())
        .collect();
    let edges: Vec<CommunityEdge> = snapshot
        .relationships
        .iter()
        .map(|rel| CommunityEdge {
            source: rel.source_uuid.clone(),
            target: rel.target_uuid.clone(),
            weight: relationship_weight(rel),
        })
        .collect();
    let by_uuid: BTreeMap<String, GraphEntity> = snapshot
        .entities
        .into_iter()
        .map(|entity| (entity.uuid.clone(), entity))
        .collect();
    for community in detect_communities(&nodes, &edges, DEFAULT_MIN_COMMUNITY_SIZE) {
        let uuid = community_id(project_id, &community.name, &community.members);
        if uuid != community_uuid {
            continue;
        }
        let members: Vec<GraphEntity> = community
            .members
            .iter()
            .filter_map(|uuid| by_uuid.get(uuid).cloned())
            .collect();
        let summary = members
            .iter()
            .map(|entity| entity.name.as_str())
            .collect::<Vec<_>>()
            .join(", ");
        return Ok(Some((
            json!({
                "uuid": uuid,
                "name": community.name,
                "summary": summary,
                "member_count": community.member_count,
                "project_id": project_id,
            }),
            members,
        )));
    }
    Ok(None)
}

async fn find_community_in_scope(
    app: &AppState,
    scope: &SearchScope,
    community_uuid: &str,
) -> SearchApiResult<Option<(String, Value, Vec<GraphEntity>)>> {
    for project_id in &scope.project_ids {
        if let Some((community, members)) = find_community(app, project_id, community_uuid).await? {
            return Ok(Some((project_id.clone(), community, members)));
        }
    }
    Ok(None)
}

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/api/v1/search-enhanced/advanced", post(search_advanced))
        .route(
            "/api/v1/search-enhanced/graph-traversal",
            post(search_graph_traversal),
        )
        .route("/api/v1/search-enhanced/community", post(search_community))
        .route("/api/v1/search-enhanced/temporal", post(search_temporal))
        .route("/api/v1/search-enhanced/faceted", post(search_faceted))
        .route(
            "/api/v1/search-enhanced/capabilities",
            get(search_capabilities),
        )
        .route("/api/v1/memory/search", post(memory_search))
}
