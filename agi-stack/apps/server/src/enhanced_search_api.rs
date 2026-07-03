//! P4 enhanced-search REST foundation over the portable [`GraphStore`] port.
//!
//! This is intentionally project-scoped. Python's enhanced-search router can
//! fan out across tenant/user project sets and persisted Community/Episodic
//! nodes; the Rust side does not expose that scope-listing contract yet. These
//! endpoints therefore require `project_id`, keep FastAPI-style error envelopes,
//! and provide a safe foundation for later parity/gateway work.

use std::collections::{BTreeMap, BTreeSet};

use axum::{
    extract::State,
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::{get, post},
    Extension, Json, Router,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use agistack_core::model::{GraphEntity, Relationship, Subgraph};
use agistack_core::{detect_communities, CommunityEdge, DEFAULT_MIN_COMMUNITY_SIZE};

use crate::auth::Identity;
use crate::AppState;

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

fn require_project_id(project_id: Option<&str>) -> SearchApiResult<&str> {
    match project_id {
        Some(project_id) if !project_id.trim().is_empty() => Ok(project_id),
        _ => Err(SearchApiError::bad_request("project_id is required")),
    }
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

#[derive(Debug, Clone, Serialize, PartialEq)]
struct SearchResult {
    uuid: String,
    name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    summary: Option<String>,
    content: String,
    #[serde(rename = "type")]
    kind: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    entity_type: Option<String>,
    score: f32,
    created_at: String,
    metadata: Value,
}

impl SearchResult {
    fn from_entity(entity: GraphEntity, score: f32, kind: &str) -> Self {
        let created_at = rfc3339(entity.created_at_ms);
        let uuid = entity.uuid;
        let name = entity.name;
        let entity_type = entity.entity_type;
        let content = if entity.summary.is_empty() {
            name.clone()
        } else {
            entity.summary.clone()
        };
        Self {
            uuid: uuid.clone(),
            name: name.clone(),
            summary: Some(entity.summary.clone()),
            content,
            kind: kind.to_string(),
            entity_type: Some(entity_type.clone()),
            score,
            created_at: created_at.clone(),
            metadata: json!({
                "uuid": uuid,
                "name": name,
                "type": entity_type.clone(),
                "entity_type": entity_type,
                "created_at": created_at,
            }),
        }
    }

    fn advanced(entity: GraphEntity, score: f32) -> Value {
        let content = if entity.summary.is_empty() {
            entity.name.clone()
        } else {
            entity.summary.clone()
        };
        json!({
            "content": content,
            "score": score,
            "source": "Knowledge Graph",
            "type": "Entity",
            "metadata": {
                "uuid": entity.uuid,
                "name": entity.name,
                "entity_type": entity.entity_type,
            },
        })
    }
}

#[derive(Debug, Deserialize)]
struct AdvancedSearchRequest {
    query: String,
    #[serde(default = "default_strategy")]
    strategy: String,
    #[serde(default)]
    focal_node_uuid: Option<String>,
    #[serde(default)]
    reranker: Option<String>,
    #[serde(default)]
    tenant_id: Option<String>,
    #[serde(default)]
    project_id: Option<String>,
    #[serde(default)]
    since: Option<String>,
    #[serde(default)]
    limit: Option<usize>,
}

fn default_strategy() -> String {
    "COMBINED_HYBRID_SEARCH_RRF".to_string()
}

#[derive(Debug, Deserialize)]
struct TraversalSearchRequest {
    start_entity_uuid: String,
    #[serde(default = "default_depth")]
    max_depth: usize,
    #[serde(default)]
    relationship_types: Option<Vec<String>>,
    #[serde(default)]
    limit: Option<usize>,
    #[serde(default)]
    tenant_id: Option<String>,
    #[serde(default)]
    project_id: Option<String>,
}

fn default_depth() -> usize {
    2
}

#[derive(Debug, Deserialize)]
struct CommunitySearchRequest {
    community_uuid: String,
    #[serde(default)]
    limit: Option<usize>,
    #[serde(default = "default_include_episodes")]
    include_episodes: bool,
    #[serde(default)]
    project_id: Option<String>,
}

fn default_include_episodes() -> bool {
    true
}

#[derive(Debug, Deserialize)]
struct TemporalSearchRequest {
    query: String,
    #[serde(default)]
    since: Option<String>,
    #[serde(default)]
    until: Option<String>,
    #[serde(default)]
    limit: Option<usize>,
    #[serde(default)]
    tenant_id: Option<String>,
    #[serde(default)]
    project_id: Option<String>,
}

#[derive(Debug, Deserialize)]
struct FacetedSearchRequest {
    query: String,
    #[serde(default)]
    entity_types: Option<Vec<String>>,
    #[serde(default)]
    tags: Option<Vec<String>>,
    #[serde(default)]
    since: Option<String>,
    #[serde(default)]
    limit: Option<usize>,
    #[serde(default)]
    offset: Option<usize>,
    #[serde(default)]
    tenant_id: Option<String>,
    #[serde(default)]
    project_id: Option<String>,
}

#[derive(Debug, Deserialize)]
struct MemorySearchRequest {
    query: String,
    #[serde(default)]
    limit: Option<usize>,
    #[serde(default)]
    project_id: Option<String>,
}

async fn search_advanced(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Json(req): Json<AdvancedSearchRequest>,
) -> SearchApiResult<Json<Value>> {
    require_query(&req.query)?;
    let project_id = require_project_id(req.project_id.as_deref())?;
    ensure_project_access(&app, &identity, project_id).await?;
    let since_ms = parse_iso_ms(req.since.as_deref(), "since")?;
    let _ = (&req.tenant_id, &req.focal_node_uuid, &req.reranker);

    let entities = app
        .graph
        .search_entities(project_id, req.query.trim(), cap_limit(req.limit))
        .await
        .map_err(SearchApiError::internal)?;
    let results: Vec<Value> = entities
        .into_iter()
        .filter(|entity| since_ms.is_none_or(|since| entity.created_at_ms >= since))
        .enumerate()
        .map(|(idx, entity)| SearchResult::advanced(entity, positional_score(idx)))
        .collect();
    Ok(Json(json!({
        "results": results,
        "total": results.len(),
        "search_type": "advanced",
        "strategy": req.strategy,
    })))
}

async fn search_graph_traversal(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Json(req): Json<TraversalSearchRequest>,
) -> SearchApiResult<Json<Value>> {
    let project_id = require_project_id(req.project_id.as_deref())?;
    ensure_project_access(&app, &identity, project_id).await?;
    let _ = &req.tenant_id;
    let Some(_start) = app
        .graph
        .get_entity(project_id, &req.start_entity_uuid)
        .await
        .map_err(SearchApiError::internal)?
    else {
        return Err(SearchApiError::not_found("Entity not found"));
    };

    let depth = req.max_depth.clamp(1, 5);
    let limit = cap_limit(req.limit);
    let graph = app
        .graph
        .subgraph(project_id, &req.start_entity_uuid, depth)
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
            let uuid = entity.uuid;
            let name = entity.name;
            let entity_type = entity.entity_type;
            json!({
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
            })
        })
        .collect();

    Ok(Json(json!({
        "results": items,
        "total": items.len(),
        "search_type": "graph_traversal",
    })))
}

async fn search_community(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Json(req): Json<CommunitySearchRequest>,
) -> SearchApiResult<Json<Value>> {
    let project_id = require_project_id(req.project_id.as_deref())?;
    ensure_project_access(&app, &identity, project_id).await?;
    let _ = req.include_episodes;
    let limit = cap_limit(req.limit);
    let Some((_community, members)) = find_community(&app, project_id, &req.community_uuid).await?
    else {
        return Err(SearchApiError::not_found("Community not found"));
    };
    let items: Vec<Value> = members
        .into_iter()
        .take(limit)
        .enumerate()
        .map(|(idx, entity)| {
            let result = SearchResult::from_entity(entity, positional_score(idx), "entity");
            serde_json::to_value(result).unwrap_or(Value::Null)
        })
        .collect();
    Ok(Json(json!({
        "results": items,
        "total": items.len(),
        "search_type": "community",
    })))
}

async fn search_temporal(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Json(req): Json<TemporalSearchRequest>,
) -> SearchApiResult<Json<Value>> {
    require_query(&req.query)?;
    let project_id = require_project_id(req.project_id.as_deref())?;
    ensure_project_access(&app, &identity, project_id).await?;
    let _ = &req.tenant_id;
    let since_ms = parse_iso_ms(req.since.as_deref(), "since")?;
    let until_ms = parse_iso_ms(req.until.as_deref(), "until")?;

    let entities = app
        .graph
        .search_entities(project_id, req.query.trim(), cap_limit(req.limit))
        .await
        .map_err(SearchApiError::internal)?;
    let results: Vec<Value> = entities
        .into_iter()
        .filter(|entity| since_ms.is_none_or(|since| entity.created_at_ms >= since))
        .filter(|entity| until_ms.is_none_or(|until| entity.created_at_ms <= until))
        .enumerate()
        .map(|(idx, entity)| {
            serde_json::to_value(SearchResult::from_entity(
                entity,
                positional_score(idx),
                "entity",
            ))
            .unwrap_or(Value::Null)
        })
        .collect();
    Ok(Json(json!({
        "results": results,
        "total": results.len(),
        "search_type": "temporal",
        "time_range": {
            "since": req.since,
            "until": req.until,
        },
    })))
}

async fn search_faceted(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Json(req): Json<FacetedSearchRequest>,
) -> SearchApiResult<Json<Value>> {
    require_query(&req.query)?;
    let project_id = require_project_id(req.project_id.as_deref())?;
    ensure_project_access(&app, &identity, project_id).await?;
    let _ = (&req.tags, &req.tenant_id);
    let since_ms = parse_iso_ms(req.since.as_deref(), "since")?;
    let limit = cap_limit(req.limit);
    let offset = req.offset.unwrap_or(0);
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

    let mut entities = app
        .graph
        .search_entities(project_id, req.query.trim(), fetch)
        .await
        .map_err(SearchApiError::internal)?;
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
            serde_json::to_value(SearchResult::from_entity(
                entity,
                positional_score(idx),
                "entity",
            ))
            .unwrap_or(Value::Null)
        })
        .collect();

    Ok(Json(json!({
        "results": results,
        "facets": {
            "entity_types": entity_type_counts,
            "total": results.len(),
        },
        "total": total,
        "limit": limit,
        "offset": offset,
        "search_type": "faceted",
    })))
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
                },
            },
            "community": {
                "description": "Search within a specific community",
                "endpoint": "/api/v1/search-enhanced/community",
                "parameters": {
                    "community_uuid": "string (required)",
                    "limit": "integer (1-200)",
                    "include_episodes": "boolean",
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
    let project_id = require_project_id(req.project_id.as_deref())?;
    ensure_project_access(&app, &identity, project_id).await?;
    let limit = req.limit.unwrap_or(10).clamp(1, 200);
    let entities = app
        .graph
        .search_entities(project_id, req.query.trim(), limit)
        .await
        .map_err(SearchApiError::internal)?;
    let results: Vec<Value> = entities
        .into_iter()
        .enumerate()
        .map(|(idx, entity)| {
            serde_json::to_value(SearchResult::from_entity(
                entity,
                positional_score(idx),
                "entity",
            ))
            .unwrap_or(Value::Null)
        })
        .collect();
    Ok(Json(json!({
        "results": results,
        "total": results.len(),
        "query": req.query,
        "filters_applied": { "project_id": project_id },
        "search_metadata": {
            "strategy": "hybrid_search",
            "limit": limit,
        },
    })))
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
    let mut seen_entities = BTreeSet::new();
    let mut seen_relationships = BTreeSet::new();
    let mut entities = Vec::new();
    let mut relationships = Vec::new();
    for seed in seeds.iter().take(1_000) {
        let graph = app
            .graph
            .subgraph(project_id, &seed.uuid, 1)
            .await
            .map_err(SearchApiError::internal)?;
        for entity in graph.entities {
            if seen_entities.insert(entity.uuid.clone()) {
                entities.push(entity);
            }
        }
        for rel in graph.relationships {
            if seen_relationships.insert(rel.uuid.clone()) {
                relationships.push(rel);
            }
        }
    }
    entities.sort_by(|a, b| a.uuid.cmp(&b.uuid));
    relationships.sort_by(|a, b| a.uuid.cmp(&b.uuid));
    Ok(Subgraph {
        entities,
        relationships,
    })
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

#[cfg(test)]
mod tests {
    use std::sync::{atomic::AtomicU64, Arc, Mutex};

    use axum::extract::State;

    use agistack_adapters_mem::{
        HashEmbedding, InMemoryCheckpointStore, InMemoryContainerRuntime, InMemoryEventStream,
        InMemoryGraphStore, InMemoryMemoryRepository, InMemoryVectorIndex, StubLlm, SystemClock,
    };
    use agistack_core::model::{GraphEntity, Relationship};
    use agistack_core::ports::{CheckpointStore, EventStream, ToolHost};
    use agistack_core::{MemoryService, ReActEngine};
    use agistack_plugin_host::{ControlPlane, DataPlaneReconciler, PluginHost};

    use super::*;
    use crate::auth::{DevAuthenticator, SharedAuthenticator};
    use crate::identity::{DevIdentityService, SharedIdentity};
    use crate::sandbox_api::ProjectSandboxService;
    use crate::shares_api::{DevShareService, SharedShares};
    use crate::skill_api::{DevSkillService, SharedSkills};
    use crate::tenant_skill_config_api::{DevTenantSkillConfigService, SharedTenantSkillConfigs};
    use crate::trust_api::{DevTrustService, SharedTrust};
    use crate::workspace_api::{DevWorkspaceService, SharedWorkspaces};

    fn identity() -> Identity {
        Identity {
            user_id: "dev-user".to_string(),
            _api_key_id: "dev-key".to_string(),
        }
    }

    fn test_state() -> AppState {
        let registry = crate::build_registry();
        let llm = Arc::new(StubLlm);
        let checkpoint: Arc<dyn CheckpointStore> = Arc::new(InMemoryCheckpointStore::new());
        let tool_host: Arc<dyn ToolHost> = Arc::new(registry.clone());
        let memory = Arc::new(
            MemoryService::new(
                Arc::new(InMemoryMemoryRepository::new()),
                llm.clone(),
                Arc::new(HashEmbedding::new(64)),
                Arc::new(SystemClock),
            )
            .with_vectors(Arc::new(InMemoryVectorIndex::new())),
        );
        let auth: SharedAuthenticator = Arc::new(DevAuthenticator::new("dev-user"));
        let identity_svc: SharedIdentity = Arc::new(DevIdentityService::new("dev-user"));
        let shares: SharedShares = Arc::new(DevShareService::new("dev-user"));
        let trust: SharedTrust = Arc::new(DevTrustService::new("dev-user"));
        let skills: SharedSkills = Arc::new(DevSkillService::new("dev-tenant"));
        let tenant_skill_configs: SharedTenantSkillConfigs =
            Arc::new(DevTenantSkillConfigService::new("dev-tenant"));
        let workspaces: SharedWorkspaces = Arc::new(DevWorkspaceService::new("dev-user"));
        let events: Arc<dyn EventStream> = Arc::new(InMemoryEventStream::new());

        AppState {
            memory,
            engine: Arc::new(ReActEngine::new(
                llm,
                tool_host,
                checkpoint,
                Arc::new(SystemClock),
            )),
            events,
            event_counter: Arc::new(AtomicU64::new(0)),
            registry: registry.clone(),
            plugins: Arc::new(PluginHost::new(registry.clone())),
            control: Arc::new(Mutex::new(ControlPlane::new())),
            reconciler: Arc::new(Mutex::new(DataPlaneReconciler::new(registry))),
            auth,
            identity: identity_svc,
            shares,
            trust,
            skills,
            tenant_skill_configs,
            workspaces,
            workspace_plan_outbox_worker: None,
            graph: Arc::new(InMemoryGraphStore::new()),
            sandboxes: Arc::new(ProjectSandboxService::new(
                Arc::new(InMemoryContainerRuntime::new()),
                "redis:7-alpine",
            )),
        }
    }

    fn entity(uuid: &str, name: &str, entity_type: &str, created_at_ms: i64) -> GraphEntity {
        GraphEntity {
            uuid: uuid.to_string(),
            name: name.to_string(),
            entity_type: entity_type.to_string(),
            summary: format!("{name} summary"),
            project_id: "p1".to_string(),
            tenant_id: Some("t1".to_string()),
            created_at_ms,
            name_embedding: None,
        }
    }

    fn relationship(uuid: &str, source: &str, target: &str, relation_type: &str) -> Relationship {
        Relationship {
            uuid: uuid.to_string(),
            source_uuid: source.to_string(),
            target_uuid: target.to_string(),
            relation_type: relation_type.to_string(),
            fact: format!("{source} {relation_type} {target}"),
            score: 1.0,
            project_id: "p1".to_string(),
            created_at_ms: 1_700_000_000_000,
        }
    }

    async fn seed_graph(app: &AppState) {
        let graph = app.graph.clone();
        for entity in [
            entity("a", "Alpha", "Concept", 1_700_000_000_000),
            entity("b", "Beta", "Concept", 1_700_010_000_000),
            entity("c", "Gamma", "Person", 1_700_020_000_000),
            entity("x", "Xray", "Product", 1_700_030_000_000),
            entity("y", "Yankee", "Product", 1_700_040_000_000),
            entity("z", "Zulu", "Product", 1_700_050_000_000),
        ] {
            graph.upsert_entity(entity).await.unwrap();
        }
        for rel in [
            relationship("r1", "a", "b", "MENTIONS"),
            relationship("r2", "b", "c", "MENTIONS"),
            relationship("r3", "a", "c", "MENTIONS"),
            relationship("r4", "x", "y", "RELATES_TO"),
            relationship("r5", "y", "z", "RELATES_TO"),
            relationship("r6", "x", "z", "RELATES_TO"),
            relationship("r7", "c", "x", "MENTIONS"),
        ] {
            graph.upsert_relationship(rel).await.unwrap();
        }
    }

    #[test]
    fn enhanced_search_router_builds() {
        let _router: Router<AppState> = router();
    }

    #[tokio::test]
    async fn advanced_and_memory_search_project_entities() {
        let app = test_state();
        seed_graph(&app).await;

        let Json(advanced) = search_advanced(
            State(app.clone()),
            Extension(identity()),
            Json(AdvancedSearchRequest {
                query: "Alpha".to_string(),
                strategy: default_strategy(),
                focal_node_uuid: None,
                reranker: None,
                tenant_id: None,
                project_id: Some("p1".to_string()),
                since: None,
                limit: Some(10),
            }),
        )
        .await
        .unwrap();
        assert_eq!(advanced["search_type"], "advanced");
        assert_eq!(advanced["total"], 1);
        assert_eq!(advanced["results"][0]["metadata"]["uuid"], "a");

        let Json(memory) = memory_search(
            State(app),
            Extension(identity()),
            Json(MemorySearchRequest {
                query: "Alpha".to_string(),
                limit: Some(10),
                project_id: Some("p1".to_string()),
            }),
        )
        .await
        .unwrap();
        assert_eq!(memory["query"], "Alpha");
        assert_eq!(memory["results"][0]["uuid"], "a");
        assert_eq!(memory["search_metadata"]["strategy"], "hybrid_search");
    }

    #[tokio::test]
    async fn traversal_temporal_and_faceted_shapes_match_python_contract() {
        let app = test_state();
        seed_graph(&app).await;

        let Json(traversal) = search_graph_traversal(
            State(app.clone()),
            Extension(identity()),
            Json(TraversalSearchRequest {
                start_entity_uuid: "a".to_string(),
                max_depth: 2,
                relationship_types: Some(vec!["MENTIONS".to_string()]),
                limit: Some(10),
                tenant_id: None,
                project_id: Some("p1".to_string()),
            }),
        )
        .await
        .unwrap();
        assert_eq!(traversal["search_type"], "graph_traversal");
        assert_eq!(traversal["total"], 4);

        let Json(temporal) = search_temporal(
            State(app.clone()),
            Extension(identity()),
            Json(TemporalSearchRequest {
                query: "summary".to_string(),
                since: Some("2023-11-14T00:00:00Z".to_string()),
                until: None,
                limit: Some(10),
                tenant_id: None,
                project_id: Some("p1".to_string()),
            }),
        )
        .await
        .unwrap();
        assert_eq!(temporal["search_type"], "temporal");
        assert!(temporal["total"].as_u64().unwrap() >= 1);

        let Json(faceted) = search_faceted(
            State(app),
            Extension(identity()),
            Json(FacetedSearchRequest {
                query: "summary".to_string(),
                entity_types: Some(vec!["Product".to_string()]),
                tags: None,
                since: None,
                limit: Some(2),
                offset: Some(0),
                tenant_id: None,
                project_id: Some("p1".to_string()),
            }),
        )
        .await
        .unwrap();
        assert_eq!(faceted["search_type"], "faceted");
        assert_eq!(faceted["facets"]["entity_types"]["Product"], 2);
    }

    #[tokio::test]
    async fn community_search_uses_portable_louvain_projection() {
        let app = test_state();
        seed_graph(&app).await;

        let snapshot = project_snapshot(&app, "p1").await.unwrap();
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
                weight: 1.0,
            })
            .collect();
        let community = detect_communities(&nodes, &edges, DEFAULT_MIN_COMMUNITY_SIZE)
            .into_iter()
            .next()
            .unwrap();
        let id = community_id("p1", &community.name, &community.members);

        let Json(result) = search_community(
            State(app),
            Extension(identity()),
            Json(CommunitySearchRequest {
                community_uuid: id,
                limit: Some(10),
                include_episodes: true,
                project_id: Some("p1".to_string()),
            }),
        )
        .await
        .unwrap();
        assert_eq!(result["search_type"], "community");
        assert_eq!(result["total"], 3);
    }

    #[tokio::test]
    async fn capabilities_and_error_envelopes_are_fastapi_compatible() {
        let Json(capabilities) = search_capabilities().await;
        assert_eq!(
            capabilities["search_types"]["faceted"]["endpoint"],
            "/api/v1/search-enhanced/faceted"
        );

        let app = test_state();
        let err = memory_search(
            State(app),
            Extension(identity()),
            Json(MemorySearchRequest {
                query: "".to_string(),
                limit: None,
                project_id: Some("p1".to_string()),
            }),
        )
        .await
        .unwrap_err();
        let response = err.into_response();
        assert_eq!(response.status(), StatusCode::BAD_REQUEST);
    }
}
