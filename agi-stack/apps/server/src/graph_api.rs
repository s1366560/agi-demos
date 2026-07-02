//! P4 knowledge-graph REST foundation over the portable [`GraphStore`] port.
//!
//! This intentionally maps only the GraphStore six-method surface that is already
//! implemented across in-memory / SQLite / Neo4j:
//! entity upsert, relationship upsert, project-scoped entity search/get,
//! outgoing neighbours, and depth-bounded subgraph. Community read and
//! synchronous rebuild endpoints are projected from a project snapshot with the
//! portable core Louvain math; the broader Python graph router still owns
//! persisted community rebuild workflows and tenant-wide pagination until those
//! semantics are migrated with parity goldens.

use std::collections::{BTreeMap, BTreeSet};

use axum::{
    extract::{Path, Query, State},
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
struct GraphApiError {
    status: StatusCode,
    detail: String,
}

impl GraphApiError {
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

    fn not_implemented(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::NOT_IMPLEMENTED, detail)
    }

    fn internal(detail: impl std::fmt::Display) -> Self {
        Self::new(StatusCode::INTERNAL_SERVER_ERROR, detail.to_string())
    }
}

impl IntoResponse for GraphApiError {
    fn into_response(self) -> Response {
        (self.status, Json(json!({ "detail": self.detail }))).into_response()
    }
}

type GraphApiResult<T> = Result<T, GraphApiError>;

fn rfc3339(ms: i64) -> String {
    chrono::DateTime::<chrono::Utc>::from_timestamp_millis(ms)
        .unwrap_or_else(|| chrono::DateTime::<chrono::Utc>::from_timestamp_millis(0).unwrap())
        .to_rfc3339_opts(chrono::SecondsFormat::Secs, true)
}

fn now_ms() -> i64 {
    chrono::Utc::now().timestamp_millis()
}

fn require_project_id(project_id: Option<&str>) -> GraphApiResult<&str> {
    match project_id {
        Some(project_id) if !project_id.trim().is_empty() => Ok(project_id),
        _ => Err(GraphApiError::bad_request("project_id is required")),
    }
}

fn cap_limit(limit: Option<usize>) -> usize {
    limit.unwrap_or(50).clamp(1, 200)
}

fn cap_scan_limit(limit: Option<usize>) -> usize {
    limit.unwrap_or(1_000).clamp(1, 1_000)
}

async fn ensure_project_access(
    app: &AppState,
    identity: &Identity,
    project_id: &str,
) -> GraphApiResult<()> {
    let allowed = app
        .auth
        .can_access_project(&identity.user_id, project_id)
        .await
        .map_err(GraphApiError::internal)?;
    if allowed {
        Ok(())
    } else {
        Err(GraphApiError::forbidden("Access denied to project"))
    }
}

async fn ensure_project_write(
    app: &AppState,
    identity: &Identity,
    project_id: &str,
) -> GraphApiResult<()> {
    let allowed = app
        .auth
        .can_write_project(&identity.user_id, project_id)
        .await
        .map_err(GraphApiError::internal)?;
    if allowed {
        Ok(())
    } else {
        Err(GraphApiError::forbidden("Access denied to project"))
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
struct EntityView {
    uuid: String,
    name: String,
    entity_type: String,
    summary: String,
    tenant_id: Option<String>,
    project_id: String,
    created_at: String,
}

impl From<GraphEntity> for EntityView {
    fn from(entity: GraphEntity) -> Self {
        Self {
            uuid: entity.uuid,
            name: entity.name,
            entity_type: entity.entity_type,
            summary: entity.summary,
            tenant_id: entity.tenant_id,
            project_id: entity.project_id,
            created_at: rfc3339(entity.created_at_ms),
        }
    }
}

#[derive(Debug, Serialize, PartialEq)]
struct EntityPage {
    entities: Vec<EntityView>,
    total: usize,
    limit: usize,
    offset: usize,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
struct EntityTypeCount {
    entity_type: String,
    count: usize,
}

#[derive(Debug, Serialize, PartialEq)]
struct EntityTypesResponse {
    entity_types: Vec<EntityTypeCount>,
    total: usize,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
struct RelationshipView {
    uuid: String,
    source_uuid: String,
    target_uuid: String,
    relation_type: String,
    fact: String,
    score: f32,
    project_id: String,
    created_at: String,
}

impl From<Relationship> for RelationshipView {
    fn from(rel: Relationship) -> Self {
        Self {
            uuid: rel.uuid,
            source_uuid: rel.source_uuid,
            target_uuid: rel.target_uuid,
            relation_type: rel.relation_type,
            fact: rel.fact,
            score: rel.score,
            project_id: rel.project_id,
            created_at: rfc3339(rel.created_at_ms),
        }
    }
}

#[derive(Debug, Serialize, PartialEq)]
struct EntityRelationships {
    relationships: Vec<Value>,
    total: usize,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
struct CommunityView {
    uuid: String,
    name: String,
    summary: String,
    member_count: usize,
    tenant_id: Option<String>,
    project_id: String,
    formed_at: Option<String>,
    created_at: Option<String>,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
struct CommunityPage {
    communities: Vec<CommunityView>,
    total: usize,
    limit: usize,
    offset: usize,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
struct CommunityMembers {
    members: Vec<EntityView>,
    total: usize,
}

#[derive(Debug, Serialize, PartialEq)]
struct RebuildCommunitiesResponse {
    status: String,
    message: String,
    communities_count: usize,
    entities_processed: usize,
}

#[derive(Debug, Deserialize)]
struct EntityQuery {
    project_id: Option<String>,
    q: Option<String>,
    limit: Option<usize>,
    offset: Option<usize>,
}

#[derive(Debug, Deserialize)]
struct CommunityQuery {
    project_id: Option<String>,
    min_members: Option<usize>,
    limit: Option<usize>,
    offset: Option<usize>,
}

#[derive(Debug, Deserialize)]
struct RebuildCommunitiesQuery {
    project_id: Option<String>,
    #[serde(default)]
    background: bool,
}

#[derive(Debug, Deserialize)]
struct EntityPathQuery {
    project_id: Option<String>,
}

#[derive(Debug, Deserialize)]
struct RelationshipQuery {
    project_id: Option<String>,
    limit: Option<usize>,
}

#[derive(Debug, Deserialize)]
struct CommunityMembersQuery {
    project_id: Option<String>,
    limit: Option<usize>,
}

#[derive(Debug, Deserialize)]
struct EntityUpsertPayload {
    uuid: String,
    name: String,
    entity_type: String,
    #[serde(default)]
    summary: String,
    project_id: String,
    #[serde(default)]
    tenant_id: Option<String>,
    #[serde(default)]
    created_at_ms: Option<i64>,
    #[serde(default)]
    name_embedding: Option<Vec<f32>>,
}

impl EntityUpsertPayload {
    fn into_entity(self) -> GraphEntity {
        GraphEntity {
            uuid: self.uuid,
            name: self.name,
            entity_type: self.entity_type,
            summary: self.summary,
            project_id: self.project_id,
            tenant_id: self.tenant_id,
            created_at_ms: self.created_at_ms.unwrap_or_else(now_ms),
            name_embedding: self.name_embedding,
        }
    }
}

#[derive(Debug, Deserialize)]
struct RelationshipUpsertPayload {
    uuid: String,
    source_uuid: String,
    target_uuid: String,
    #[serde(default = "default_relation_type")]
    relation_type: String,
    #[serde(default)]
    fact: String,
    #[serde(default = "default_score")]
    score: f32,
    project_id: String,
    #[serde(default)]
    created_at_ms: Option<i64>,
}

fn default_relation_type() -> String {
    "MENTIONS".to_string()
}

fn default_score() -> f32 {
    1.0
}

impl RelationshipUpsertPayload {
    fn into_relationship(self) -> Relationship {
        Relationship {
            uuid: self.uuid,
            source_uuid: self.source_uuid,
            target_uuid: self.target_uuid,
            relation_type: self.relation_type,
            fact: self.fact,
            score: self.score,
            project_id: self.project_id,
            created_at_ms: self.created_at_ms.unwrap_or_else(now_ms),
        }
    }
}

#[derive(Debug, Deserialize)]
struct SubgraphRequest {
    node_uuids: Vec<String>,
    #[serde(default = "default_include_neighbors")]
    include_neighbors: bool,
    #[serde(default = "default_subgraph_limit")]
    limit: usize,
    #[serde(default)]
    project_id: Option<String>,
    #[serde(default)]
    tenant_id: Option<String>,
}

fn default_include_neighbors() -> bool {
    true
}

fn default_subgraph_limit() -> usize {
    100
}

async fn list_entities(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(query): Query<EntityQuery>,
) -> GraphApiResult<Json<EntityPage>> {
    let project_id = require_project_id(query.project_id.as_deref())?;
    ensure_project_access(&app, &identity, project_id).await?;

    let limit = cap_limit(query.limit);
    let offset = query.offset.unwrap_or(0);
    let fetch = limit.saturating_add(offset).clamp(1, 1_000);
    let q = query.q.as_deref().unwrap_or("");
    let hits = app
        .graph
        .search_entities(project_id, q, fetch)
        .await
        .map_err(GraphApiError::internal)?;

    let entities: Vec<EntityView> = hits
        .into_iter()
        .skip(offset)
        .take(limit)
        .map(EntityView::from)
        .collect();
    Ok(Json(EntityPage {
        total: entities.len(),
        entities,
        limit,
        offset,
    }))
}

async fn get_entity_types(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(query): Query<EntityPathQuery>,
) -> GraphApiResult<Json<EntityTypesResponse>> {
    let project_id = require_project_id(query.project_id.as_deref())?;
    ensure_project_access(&app, &identity, project_id).await?;

    let snapshot = graph_project_snapshot(&app, project_id, 1_000).await?;
    let mut counts: BTreeMap<String, usize> = BTreeMap::new();
    for entity in snapshot.entities {
        *counts.entry(entity.entity_type).or_insert(0) += 1;
    }
    let mut entity_types: Vec<EntityTypeCount> = counts
        .into_iter()
        .map(|(entity_type, count)| EntityTypeCount { entity_type, count })
        .collect();
    entity_types.sort_by(|a, b| {
        b.count
            .cmp(&a.count)
            .then_with(|| a.entity_type.cmp(&b.entity_type))
    });
    Ok(Json(EntityTypesResponse {
        total: entity_types.len(),
        entity_types,
    }))
}

async fn get_entity(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(uuid): Path<String>,
    Query(query): Query<EntityPathQuery>,
) -> GraphApiResult<Json<EntityView>> {
    let project_id = require_project_id(query.project_id.as_deref())?;
    ensure_project_access(&app, &identity, project_id).await?;

    match app
        .graph
        .get_entity(project_id, &uuid)
        .await
        .map_err(GraphApiError::internal)?
    {
        Some(entity) => Ok(Json(EntityView::from(entity))),
        None => Err(GraphApiError::not_found("Entity not found")),
    }
}

async fn get_entity_relationships(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(uuid): Path<String>,
    Query(query): Query<RelationshipQuery>,
) -> GraphApiResult<Json<EntityRelationships>> {
    let project_id = require_project_id(query.project_id.as_deref())?;
    ensure_project_access(&app, &identity, project_id).await?;

    let Some(_entity) = app
        .graph
        .get_entity(project_id, &uuid)
        .await
        .map_err(GraphApiError::internal)?
    else {
        return Err(GraphApiError::not_found("Entity not found"));
    };

    let limit = cap_limit(query.limit);
    let subgraph = app
        .graph
        .subgraph(project_id, &uuid, 1)
        .await
        .map_err(GraphApiError::internal)?;
    let by_uuid: BTreeMap<String, GraphEntity> = subgraph
        .entities
        .iter()
        .cloned()
        .map(|entity| (entity.uuid.clone(), entity))
        .collect();
    let relationships: Vec<Value> = subgraph
        .relationships
        .into_iter()
        .filter(|rel| rel.source_uuid == uuid)
        .take(limit)
        .map(|rel| {
            let related_entity = by_uuid
                .get(&rel.target_uuid)
                .cloned()
                .map(EntityView::from)
                .map(serde_json::to_value)
                .transpose()
                .unwrap_or(None)
                .unwrap_or(Value::Null);
            json!({
                "edge_id": rel.uuid,
                "relation_type": rel.relation_type,
                "direction": "outgoing",
                "fact": rel.fact,
                "score": rel.score,
                "created_at": rfc3339(rel.created_at_ms),
                "related_entity": related_entity,
            })
        })
        .collect();
    Ok(Json(EntityRelationships {
        total: relationships.len(),
        relationships,
    }))
}

async fn list_communities(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(query): Query<CommunityQuery>,
) -> GraphApiResult<Json<CommunityPage>> {
    let project_id = require_project_id(query.project_id.as_deref())?;
    ensure_project_access(&app, &identity, project_id).await?;

    let limit = cap_limit(query.limit);
    let offset = query.offset.unwrap_or(0);
    let min_members = query.min_members.unwrap_or(DEFAULT_MIN_COMMUNITY_SIZE);
    let snapshot = graph_project_snapshot(&app, project_id, cap_scan_limit(None)).await?;
    let mut communities = community_views(project_id, snapshot, min_members);
    let total = communities.len();
    communities = communities.into_iter().skip(offset).take(limit).collect();
    Ok(Json(CommunityPage {
        communities,
        total,
        limit,
        offset,
    }))
}

async fn rebuild_communities(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(query): Query<RebuildCommunitiesQuery>,
) -> GraphApiResult<Json<RebuildCommunitiesResponse>> {
    let project_id = require_project_id(query.project_id.as_deref())?;
    ensure_project_write(&app, &identity, project_id).await?;

    if query.background {
        return Err(GraphApiError::not_implemented(
            "Background community rebuild is not implemented in Rust",
        ));
    }

    let snapshot = graph_project_snapshot(&app, project_id, cap_scan_limit(None)).await?;
    let entities_processed = snapshot.entities.len();
    let communities_count = community_views(project_id, snapshot, DEFAULT_MIN_COMMUNITY_SIZE).len();

    Ok(Json(RebuildCommunitiesResponse {
        status: "success".to_string(),
        message: "Communities rebuilt successfully".to_string(),
        communities_count,
        entities_processed,
    }))
}

async fn get_community(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(community_id): Path<String>,
    Query(query): Query<EntityPathQuery>,
) -> GraphApiResult<Json<CommunityView>> {
    let project_id = require_project_id(query.project_id.as_deref())?;
    ensure_project_access(&app, &identity, project_id).await?;

    find_community(&app, project_id, &community_id, DEFAULT_MIN_COMMUNITY_SIZE)
        .await?
        .map(|(community, _)| Json(community))
        .ok_or_else(|| GraphApiError::not_found("Community not found"))
}

async fn get_community_members(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(community_id): Path<String>,
    Query(query): Query<CommunityMembersQuery>,
) -> GraphApiResult<Json<CommunityMembers>> {
    let project_id = require_project_id(query.project_id.as_deref())?;
    ensure_project_access(&app, &identity, project_id).await?;

    let (_, mut members) =
        find_community(&app, project_id, &community_id, DEFAULT_MIN_COMMUNITY_SIZE)
            .await?
            .ok_or_else(|| GraphApiError::not_found("Community not found"))?;
    let total = members.len();
    members.truncate(cap_limit(query.limit));
    Ok(Json(CommunityMembers { members, total }))
}

async fn upsert_entity(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Json(payload): Json<EntityUpsertPayload>,
) -> GraphApiResult<impl IntoResponse> {
    ensure_project_write(&app, &identity, &payload.project_id).await?;
    let entity = payload.into_entity();
    app.graph
        .upsert_entity(entity.clone())
        .await
        .map_err(GraphApiError::internal)?;
    Ok((StatusCode::CREATED, Json(EntityView::from(entity))))
}

async fn upsert_relationship(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Json(payload): Json<RelationshipUpsertPayload>,
) -> GraphApiResult<impl IntoResponse> {
    ensure_project_write(&app, &identity, &payload.project_id).await?;
    let rel = payload.into_relationship();
    app.graph
        .upsert_relationship(rel.clone())
        .await
        .map_err(GraphApiError::internal)?;
    Ok((StatusCode::CREATED, Json(RelationshipView::from(rel))))
}

async fn get_graph(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(query): Query<EntityQuery>,
) -> GraphApiResult<Json<Value>> {
    let project_id = require_project_id(query.project_id.as_deref())?;
    ensure_project_access(&app, &identity, project_id).await?;

    let limit = cap_limit(query.limit);
    let q = query.q.as_deref().unwrap_or("");
    let seeds = app
        .graph
        .search_entities(project_id, q, limit)
        .await
        .map_err(GraphApiError::internal)?;
    let seed_ids: Vec<String> = seeds.into_iter().map(|entity| entity.uuid).collect();
    let graph = merge_subgraphs(&app, project_id, &seed_ids, 1, limit).await?;
    Ok(Json(subgraph_elements(graph)))
}

async fn get_subgraph(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Json(req): Json<SubgraphRequest>,
) -> GraphApiResult<Json<Value>> {
    let project_id = require_project_id(req.project_id.as_deref())?;
    ensure_project_access(&app, &identity, project_id).await?;

    let _tenant_id = req.tenant_id;
    let depth = if req.include_neighbors { 1 } else { 0 };
    let graph = merge_subgraphs(
        &app,
        project_id,
        &req.node_uuids,
        depth,
        req.limit.clamp(1, 200),
    )
    .await?;
    Ok(Json(subgraph_elements(graph)))
}

async fn graph_project_snapshot(
    app: &AppState,
    project_id: &str,
    limit: usize,
) -> GraphApiResult<Subgraph> {
    let seeds = app
        .graph
        .search_entities(project_id, "", limit)
        .await
        .map_err(GraphApiError::internal)?;
    let seed_ids: Vec<String> = seeds.into_iter().map(|entity| entity.uuid).collect();
    merge_subgraphs(app, project_id, &seed_ids, 1, limit).await
}

async fn merge_subgraphs(
    app: &AppState,
    project_id: &str,
    seed_ids: &[String],
    depth: usize,
    limit: usize,
) -> GraphApiResult<Subgraph> {
    let mut entity_ids = BTreeSet::new();
    let mut rel_ids = BTreeSet::new();
    let mut entities = Vec::new();
    let mut relationships = Vec::new();

    for seed_id in seed_ids.iter().take(limit) {
        let subgraph = app
            .graph
            .subgraph(project_id, seed_id, depth)
            .await
            .map_err(GraphApiError::internal)?;
        for entity in subgraph.entities {
            if entity_ids.insert(entity.uuid.clone()) {
                entities.push(entity);
            }
        }
        for rel in subgraph.relationships {
            if rel_ids.insert(rel.uuid.clone()) {
                relationships.push(rel);
            }
        }
    }

    entities.sort_by(|a, b| a.uuid.cmp(&b.uuid));
    relationships.sort_by(|a, b| a.uuid.cmp(&b.uuid));
    entities.truncate(limit);
    let entity_ids: BTreeSet<String> = entities.iter().map(|entity| entity.uuid.clone()).collect();
    relationships.retain(|rel| {
        entity_ids.contains(&rel.source_uuid) && entity_ids.contains(&rel.target_uuid)
    });
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

fn community_summary(members: &[EntityView]) -> String {
    members
        .iter()
        .map(|entity| entity.name.as_str())
        .collect::<Vec<_>>()
        .join(", ")
}

fn community_views(project_id: &str, graph: Subgraph, min_members: usize) -> Vec<CommunityView> {
    let nodes: Vec<String> = graph
        .entities
        .iter()
        .map(|entity| entity.uuid.clone())
        .collect();
    let edges: Vec<CommunityEdge> = graph
        .relationships
        .iter()
        .map(|rel| CommunityEdge {
            source: rel.source_uuid.clone(),
            target: rel.target_uuid.clone(),
            weight: relationship_weight(rel),
        })
        .collect();
    let by_uuid: BTreeMap<String, EntityView> = graph
        .entities
        .into_iter()
        .map(|entity| {
            let view = EntityView::from(entity);
            (view.uuid.clone(), view)
        })
        .collect();

    detect_communities(&nodes, &edges, min_members)
        .into_iter()
        .map(|community| {
            let members: Vec<EntityView> = community
                .members
                .iter()
                .filter_map(|uuid| by_uuid.get(uuid).cloned())
                .collect();
            let tenant_id = members.iter().find_map(|entity| entity.tenant_id.clone());
            CommunityView {
                uuid: community_id(project_id, &community.name, &community.members),
                name: community.name,
                summary: community_summary(&members),
                member_count: community.member_count,
                tenant_id,
                project_id: project_id.to_string(),
                formed_at: None,
                created_at: None,
            }
        })
        .collect()
}

async fn find_community(
    app: &AppState,
    project_id: &str,
    community_uuid: &str,
    min_members: usize,
) -> GraphApiResult<Option<(CommunityView, Vec<EntityView>)>> {
    let snapshot = graph_project_snapshot(app, project_id, cap_scan_limit(None)).await?;
    let views = community_views(project_id, snapshot.clone(), min_members);
    let Some(view) = views
        .into_iter()
        .find(|community| community.uuid == community_uuid)
    else {
        return Ok(None);
    };
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
    let Some(community) = detect_communities(&nodes, &edges, min_members)
        .into_iter()
        .find(|community| {
            community_id(project_id, &community.name, &community.members) == community_uuid
        })
    else {
        return Ok(None);
    };
    let by_uuid: BTreeMap<String, EntityView> = snapshot
        .entities
        .into_iter()
        .map(|entity| {
            let view = EntityView::from(entity);
            (view.uuid.clone(), view)
        })
        .collect();
    let members = community
        .members
        .into_iter()
        .filter_map(|uuid| by_uuid.get(&uuid).cloned())
        .collect();
    Ok(Some((view, members)))
}

fn subgraph_elements(graph: Subgraph) -> Value {
    let nodes: Vec<Value> = graph
        .entities
        .into_iter()
        .map(|entity| {
            let view = EntityView::from(entity);
            json!({
                "data": {
                    "id": view.uuid,
                    "label": view.entity_type,
                    "name": view.name,
                    "entity_type": view.entity_type,
                    "summary": view.summary,
                    "tenant_id": view.tenant_id,
                    "project_id": view.project_id,
                    "created_at": view.created_at,
                }
            })
        })
        .collect();
    let edges: Vec<Value> = graph
        .relationships
        .into_iter()
        .map(|rel| {
            json!({
                "data": {
                    "id": rel.uuid,
                    "source": rel.source_uuid,
                    "target": rel.target_uuid,
                    "label": rel.relation_type,
                    "fact": rel.fact,
                    "score": rel.score,
                    "project_id": rel.project_id,
                    "created_at": rfc3339(rel.created_at_ms),
                }
            })
        })
        .collect();
    json!({ "elements": { "nodes": nodes, "edges": edges } })
}

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/api/v1/graph/communities/", get(list_communities))
        .route("/api/v1/graph/communities", get(list_communities))
        .route(
            "/api/v1/graph/communities/rebuild",
            post(rebuild_communities),
        )
        .route("/api/v1/graph/communities/:uuid", get(get_community))
        .route(
            "/api/v1/graph/communities/:uuid/members",
            get(get_community_members),
        )
        .route(
            "/api/v1/graph/entities/",
            get(list_entities).post(upsert_entity),
        )
        .route(
            "/api/v1/graph/entities",
            get(list_entities).post(upsert_entity),
        )
        .route("/api/v1/graph/entities/types", get(get_entity_types))
        .route("/api/v1/graph/entities/:uuid", get(get_entity))
        .route(
            "/api/v1/graph/entities/:uuid/relationships",
            get(get_entity_relationships),
        )
        .route("/api/v1/graph/relationships/", post(upsert_relationship))
        .route("/api/v1/graph/relationships", post(upsert_relationship))
        .route("/api/v1/graph/memory/graph", get(get_graph))
        .route("/api/v1/graph/memory/graph/subgraph", post(get_subgraph))
}

#[cfg(test)]
mod tests {
    use std::sync::{atomic::AtomicU64, Arc, Mutex};

    use axum::extract::{Path, Query, State};
    use serde_json::json;

    use agistack_adapters_mem::{
        HashEmbedding, InMemoryCheckpointStore, InMemoryContainerRuntime, InMemoryEventStream,
        InMemoryGraphStore, InMemoryMemoryRepository, InMemoryVectorIndex, StubLlm, SystemClock,
    };
    use agistack_core::ports::{CheckpointStore, EventStream, ToolHost};
    use agistack_core::{MemoryService, ReActEngine};
    use agistack_plugin_host::{ControlPlane, DataPlaneReconciler, PluginHost};

    use super::*;
    use crate::auth::{DevAuthenticator, SharedAuthenticator};
    use crate::identity::{DevIdentityService, SharedIdentity};
    use crate::sandbox_api::ProjectSandboxService;
    use crate::shares_api::{DevShareService, SharedShares};
    use crate::skill_api::{DevSkillService, SharedSkills};
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
            workspaces,
            graph: Arc::new(InMemoryGraphStore::new()),
            sandboxes: Arc::new(ProjectSandboxService::new(
                Arc::new(InMemoryContainerRuntime::new()),
                "redis:7-alpine",
            )),
        }
    }

    fn sample_entity(uuid: &str, name: &str) -> EntityUpsertPayload {
        EntityUpsertPayload {
            uuid: uuid.to_string(),
            name: name.to_string(),
            entity_type: "Concept".to_string(),
            summary: format!("{name} summary"),
            project_id: "p1".to_string(),
            tenant_id: Some("t1".to_string()),
            created_at_ms: Some(1_700_000_000_000),
            name_embedding: None,
        }
    }

    fn sample_entity_type(uuid: &str, name: &str, entity_type: &str) -> EntityUpsertPayload {
        EntityUpsertPayload {
            entity_type: entity_type.to_string(),
            ..sample_entity(uuid, name)
        }
    }

    async fn seed_relationship(app: &AppState, uuid: &str, source: &str, target: &str) {
        upsert_relationship(
            State(app.clone()),
            Extension(identity()),
            Json(RelationshipUpsertPayload {
                uuid: uuid.to_string(),
                source_uuid: source.to_string(),
                target_uuid: target.to_string(),
                relation_type: "MENTIONS".to_string(),
                fact: format!("{source} mentions {target}"),
                score: 1.0,
                project_id: "p1".to_string(),
                created_at_ms: Some(1_700_000_000_000),
            }),
        )
        .await
        .unwrap();
    }

    async fn seed_two_community_graph(app: &AppState) {
        for uuid in ["a", "b", "c", "x", "y", "z"] {
            upsert_entity(
                State(app.clone()),
                Extension(identity()),
                Json(sample_entity(uuid, &uuid.to_uppercase())),
            )
            .await
            .unwrap();
        }
        for (uuid, source, target) in [
            ("r1", "a", "b"),
            ("r2", "b", "c"),
            ("r3", "a", "c"),
            ("r4", "x", "y"),
            ("r5", "y", "z"),
            ("r6", "x", "z"),
            ("r7", "c", "x"),
        ] {
            seed_relationship(app, uuid, source, target).await;
        }
    }

    #[tokio::test]
    async fn graph_entity_upsert_search_get_roundtrips() {
        let app = test_state();
        upsert_entity(
            State(app.clone()),
            Extension(identity()),
            Json(sample_entity("e1", "Rust")),
        )
        .await
        .unwrap();

        let Json(page) = list_entities(
            State(app.clone()),
            Extension(identity()),
            Query(EntityQuery {
                project_id: Some("p1".to_string()),
                q: Some("rust".to_string()),
                limit: Some(10),
                offset: None,
            }),
        )
        .await
        .unwrap();
        assert_eq!(page.total, 1);
        assert_eq!(page.entities[0].uuid, "e1");

        let Json(entity) = get_entity(
            State(app),
            Extension(identity()),
            Path("e1".to_string()),
            Query(EntityPathQuery {
                project_id: Some("p1".to_string()),
            }),
        )
        .await
        .unwrap();
        assert_eq!(entity.name, "Rust");
        assert_eq!(entity.created_at, "2023-11-14T22:13:20Z");
    }

    #[test]
    fn graph_router_builds_with_static_and_dynamic_routes() {
        let _router: Router<AppState> = router();
    }

    #[tokio::test]
    async fn entity_types_are_counted_from_project_snapshot() {
        let app = test_state();
        for payload in [
            sample_entity_type("e1", "Rust", "Language"),
            sample_entity_type("e2", "Tokio", "Library"),
            sample_entity_type("e3", "Axum", "Library"),
        ] {
            upsert_entity(State(app.clone()), Extension(identity()), Json(payload))
                .await
                .unwrap();
        }

        let Json(types) = get_entity_types(
            State(app),
            Extension(identity()),
            Query(EntityPathQuery {
                project_id: Some("p1".to_string()),
            }),
        )
        .await
        .unwrap();

        assert_eq!(types.total, 2);
        assert_eq!(
            types.entity_types,
            vec![
                EntityTypeCount {
                    entity_type: "Library".to_string(),
                    count: 2,
                },
                EntityTypeCount {
                    entity_type: "Language".to_string(),
                    count: 1,
                },
            ]
        );
    }

    #[tokio::test]
    async fn relationships_and_subgraph_project_to_cytoscape_elements() {
        let app = test_state();
        for payload in [sample_entity("e1", "Alpha"), sample_entity("e2", "Beta")] {
            upsert_entity(State(app.clone()), Extension(identity()), Json(payload))
                .await
                .unwrap();
        }
        upsert_relationship(
            State(app.clone()),
            Extension(identity()),
            Json(RelationshipUpsertPayload {
                uuid: "r1".to_string(),
                source_uuid: "e1".to_string(),
                target_uuid: "e2".to_string(),
                relation_type: "MENTIONS".to_string(),
                fact: "Alpha mentions Beta".to_string(),
                score: 0.9,
                project_id: "p1".to_string(),
                created_at_ms: Some(1_700_000_000_000),
            }),
        )
        .await
        .unwrap();

        let Json(relationships) = get_entity_relationships(
            State(app.clone()),
            Extension(identity()),
            Path("e1".to_string()),
            Query(RelationshipQuery {
                project_id: Some("p1".to_string()),
                limit: Some(10),
            }),
        )
        .await
        .unwrap();
        assert_eq!(relationships.total, 1);
        assert_eq!(relationships.relationships[0]["edge_id"], "r1");

        let Json(elements) = get_subgraph(
            State(app),
            Extension(identity()),
            Json(SubgraphRequest {
                node_uuids: vec!["e1".to_string()],
                include_neighbors: true,
                limit: 100,
                project_id: Some("p1".to_string()),
                tenant_id: None,
            }),
        )
        .await
        .unwrap();
        assert_eq!(elements["elements"]["nodes"].as_array().unwrap().len(), 2);
        assert_eq!(elements["elements"]["edges"][0]["data"]["id"], "r1");
    }

    #[tokio::test]
    async fn communities_are_detected_and_members_are_addressable() {
        let app = test_state();
        seed_two_community_graph(&app).await;

        let Json(page) = list_communities(
            State(app.clone()),
            Extension(identity()),
            Query(CommunityQuery {
                project_id: Some("p1".to_string()),
                min_members: Some(2),
                limit: Some(10),
                offset: None,
            }),
        )
        .await
        .unwrap();
        assert_eq!(page.total, 2);
        assert!(page
            .communities
            .iter()
            .all(|community| community.member_count == 3));

        let community_id = page.communities[0].uuid.clone();
        let Json(community) = get_community(
            State(app.clone()),
            Extension(identity()),
            Path(community_id.clone()),
            Query(EntityPathQuery {
                project_id: Some("p1".to_string()),
            }),
        )
        .await
        .unwrap();
        assert_eq!(community.uuid, community_id);
        assert_eq!(community.member_count, 3);

        let Json(members) = get_community_members(
            State(app),
            Extension(identity()),
            Path(community_id),
            Query(CommunityMembersQuery {
                project_id: Some("p1".to_string()),
                limit: Some(2),
            }),
        )
        .await
        .unwrap();
        assert_eq!(members.total, 3);
        assert_eq!(members.members.len(), 2);
    }

    #[tokio::test]
    async fn rebuild_communities_counts_project_snapshot() {
        let app = test_state();
        seed_two_community_graph(&app).await;

        let Json(response) = rebuild_communities(
            State(app),
            Extension(identity()),
            Query(RebuildCommunitiesQuery {
                project_id: Some("p1".to_string()),
                background: false,
            }),
        )
        .await
        .unwrap();

        assert_eq!(
            response,
            RebuildCommunitiesResponse {
                status: "success".to_string(),
                message: "Communities rebuilt successfully".to_string(),
                communities_count: 2,
                entities_processed: 6,
            }
        );
    }

    #[tokio::test]
    async fn rebuild_communities_background_is_explicitly_unimplemented() {
        let app = test_state();
        let error = rebuild_communities(
            State(app),
            Extension(identity()),
            Query(RebuildCommunitiesQuery {
                project_id: Some("p1".to_string()),
                background: true,
            }),
        )
        .await
        .unwrap_err();

        assert_eq!(error.status, StatusCode::NOT_IMPLEMENTED);
        assert_eq!(
            error.detail,
            "Background community rebuild is not implemented in Rust"
        );
    }

    #[test]
    fn entity_view_matches_golden() {
        let view = EntityView::from(sample_entity("e1", "Rust").into_entity());
        let actual = serde_json::to_value(view).unwrap();
        let expected = json!({
            "uuid": "e1",
            "name": "Rust",
            "entity_type": "Concept",
            "summary": "Rust summary",
            "tenant_id": "t1",
            "project_id": "p1",
            "created_at": "2023-11-14T22:13:20Z",
        });
        assert_eq!(actual, expected);
    }
}
