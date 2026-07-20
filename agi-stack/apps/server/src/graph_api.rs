//! P4 knowledge-graph REST foundation over the portable [`GraphStore`] port.
//!
//! This intentionally maps only the GraphStore six-method surface that is already
//! implemented across in-memory / SQLite / Neo4j:
//! entity upsert, relationship upsert, project-scoped entity search/get,
//! outgoing neighbours, and depth-bounded subgraph. Community read and
//! synchronous rebuild endpoints are projected from a project snapshot with the
//! portable core Louvain math. Background community rebuild requests are logged
//! to the shared EventStream and completed by a Rust worker task; broader
//! tenant-wide pagination still stays Python-owned until those semantics are
//! migrated with parity goldens.

use std::collections::{BTreeMap, BTreeSet};
use std::sync::atomic::Ordering;
use std::sync::Arc;

use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::{get, post},
    Extension, Json, Router,
};
use serde_json::{json, Value};

use agistack_adapters_mem::InMemoryGraphStore;
use agistack_core::model::{GraphEntity, Relationship, Subgraph};
use agistack_core::ports::{CoreResult, GraphStore};
use agistack_core::{detect_communities, CommunityEdge, DEFAULT_MIN_COMMUNITY_SIZE};

use crate::auth::Identity;
use crate::AppState;

mod views;

use views::*;

const GRAPH_SNAPSHOT_VERSION: u32 = 1;
const GRAPH_IMPORT_MAX_ENTITIES: usize = 1_000;
const GRAPH_IMPORT_MAX_RELATIONSHIPS: usize = 2_000;
const GRAPH_REBUILD_EVENT_STREAM_MAX_LEN: usize = 1_000;
const PERSISTED_COMMUNITY_ENTITY_TYPE: &str = "Community";
const PERSISTED_COMMUNITY_MEMBER_RELATION_TYPE: &str = "HAS_MEMBER";

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
        .unwrap_or(chrono::DateTime::<chrono::Utc>::UNIX_EPOCH)
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
        return enqueue_background_community_rebuild(app, identity, project_id).await;
    }

    let snapshot = graph_project_snapshot(&app, project_id, cap_scan_limit(None)).await?;
    let entities_processed = count_source_entities(&snapshot);
    let communities = project_communities(project_id, snapshot.clone(), DEFAULT_MIN_COMMUNITY_SIZE);
    let communities_count = communities.len();
    persist_community_projection(&app, project_id, &snapshot, &communities, now_ms()).await?;

    Ok(Json(RebuildCommunitiesResponse {
        status: "success".to_string(),
        message: "Communities rebuilt successfully".to_string(),
        communities_count,
        entities_processed,
        job_id: None,
        job_status: None,
        event_topic: None,
        requested_event_id: None,
    }))
}

async fn enqueue_background_community_rebuild(
    app: AppState,
    identity: Identity,
    project_id: &str,
) -> GraphApiResult<Json<RebuildCommunitiesResponse>> {
    let job_id = next_graph_rebuild_job_id(&app, project_id);
    let topic = graph_rebuild_topic(project_id);
    let requested_event_id = append_graph_rebuild_event(
        &app,
        project_id,
        json!({
            "type": "graph_community_rebuild_requested",
            "job_id": job_id.as_str(),
            "project_id": project_id,
            "requested_by": identity.user_id.as_str(),
            "job_status": "queued",
            "min_community_size": DEFAULT_MIN_COMMUNITY_SIZE,
            "scan_limit": cap_scan_limit(None),
            "created_at": rfc3339(now_ms()),
        }),
    )
    .await?;

    let worker_app = app.clone();
    let worker_project_id = project_id.to_string();
    let worker_job_id = job_id.clone();
    tokio::spawn(async move {
        run_background_community_rebuild(worker_app, worker_project_id, worker_job_id).await;
    });

    Ok(Json(RebuildCommunitiesResponse {
        status: "accepted".to_string(),
        message: "Background community rebuild queued".to_string(),
        communities_count: 0,
        entities_processed: 0,
        job_id: Some(job_id),
        job_status: Some("queued".to_string()),
        event_topic: Some(topic),
        requested_event_id: Some(requested_event_id),
    }))
}

async fn get_rebuild_job(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(job_id): Path<String>,
    Query(query): Query<RebuildCommunityJobQuery>,
) -> GraphApiResult<Json<RebuildCommunityJobStatusResponse>> {
    let project_id = require_project_id(query.project_id.as_deref())?;
    ensure_project_access(&app, &identity, project_id).await?;

    let topic = graph_rebuild_topic(project_id);
    let entries = app
        .events
        .read_after(&topic, "", GRAPH_REBUILD_EVENT_STREAM_MAX_LEN)
        .await
        .map_err(GraphApiError::internal)?;
    let mut events = Vec::new();
    for entry in entries {
        let Ok(payload) = serde_json::from_str::<Value>(&entry.payload) else {
            continue;
        };
        if payload.get("job_id").and_then(Value::as_str) != Some(job_id.as_str()) {
            continue;
        }
        if let Some(event) = graph_rebuild_job_event_view(entry.id, &payload) {
            events.push(event);
        }
    }

    let Some(latest) = events.last() else {
        return Err(GraphApiError::not_found("Community rebuild job not found"));
    };

    Ok(Json(RebuildCommunityJobStatusResponse {
        job_id,
        project_id: project_id.to_string(),
        job_status: latest.job_status.clone(),
        event_topic: topic,
        latest_event_id: latest.event_id.clone(),
        communities_count: latest.communities_count,
        entities_processed: latest.entities_processed,
        persisted_communities_count: latest.persisted_communities_count,
        error: latest.error.clone(),
        events,
    }))
}

fn graph_rebuild_job_event_view(
    event_id: String,
    payload: &Value,
) -> Option<RebuildCommunityJobEventView> {
    Some(RebuildCommunityJobEventView {
        event_id,
        event_type: payload.get("type")?.as_str()?.to_string(),
        job_status: payload.get("job_status")?.as_str()?.to_string(),
        created_at: value_string(payload, "created_at"),
        started_at: value_string(payload, "started_at"),
        completed_at: value_string(payload, "completed_at"),
        failed_at: value_string(payload, "failed_at"),
        communities_count: value_usize(payload, "communities_count"),
        entities_processed: value_usize(payload, "entities_processed"),
        persisted_communities_count: value_usize(payload, "persisted_communities_count"),
        error: value_string(payload, "error"),
    })
}

fn value_string(payload: &Value, key: &str) -> Option<String> {
    payload
        .get(key)
        .and_then(Value::as_str)
        .map(ToString::to_string)
}

fn value_usize(payload: &Value, key: &str) -> Option<usize> {
    payload
        .get(key)
        .and_then(Value::as_u64)
        .and_then(|value| usize::try_from(value).ok())
}

async fn run_background_community_rebuild(app: AppState, project_id: String, job_id: String) {
    let _ = append_graph_rebuild_event(
        &app,
        &project_id,
        json!({
            "type": "graph_community_rebuild_started",
            "job_id": job_id.as_str(),
            "project_id": project_id.as_str(),
            "job_status": "running",
            "started_at": rfc3339(now_ms()),
        }),
    )
    .await;

    match graph_project_snapshot(&app, &project_id, cap_scan_limit(None)).await {
        Ok(snapshot) => {
            let entities_processed = count_source_entities(&snapshot);
            let communities =
                project_communities(&project_id, snapshot.clone(), DEFAULT_MIN_COMMUNITY_SIZE);
            let communities_count = communities.len();
            let persisted_communities_count = match persist_community_projection(
                &app,
                &project_id,
                &snapshot,
                &communities,
                now_ms(),
            )
            .await
            {
                Ok(()) => communities_count,
                Err(err) => {
                    let _ = append_graph_rebuild_event(
                        &app,
                        &project_id,
                        json!({
                            "type": "graph_community_rebuild_failed",
                            "job_id": job_id.as_str(),
                            "project_id": project_id.as_str(),
                            "job_status": "failed",
                            "error": err.detail,
                            "failed_at": rfc3339(now_ms()),
                        }),
                    )
                    .await;
                    return;
                }
            };
            let _ = append_graph_rebuild_event(
                &app,
                &project_id,
                json!({
                    "type": "graph_community_rebuild_completed",
                    "job_id": job_id.as_str(),
                    "project_id": project_id.as_str(),
                    "job_status": "completed",
                    "communities_count": communities_count,
                    "entities_processed": entities_processed,
                    "persisted_communities_count": persisted_communities_count,
                    "completed_at": rfc3339(now_ms()),
                }),
            )
            .await;
        }
        Err(err) => {
            let _ = append_graph_rebuild_event(
                &app,
                &project_id,
                json!({
                    "type": "graph_community_rebuild_failed",
                    "job_id": job_id.as_str(),
                    "project_id": project_id.as_str(),
                    "job_status": "failed",
                    "error": err.detail,
                    "failed_at": rfc3339(now_ms()),
                }),
            )
            .await;
        }
    }
}

async fn append_graph_rebuild_event(
    app: &AppState,
    project_id: &str,
    payload: Value,
) -> GraphApiResult<String> {
    app.events
        .append(
            &graph_rebuild_topic(project_id),
            &payload.to_string(),
            GRAPH_REBUILD_EVENT_STREAM_MAX_LEN,
        )
        .await
        .map_err(GraphApiError::internal)
}

fn graph_rebuild_topic(project_id: &str) -> String {
    format!("graph:community_rebuilds:{project_id}")
}

fn next_graph_rebuild_job_id(app: &AppState, project_id: &str) -> String {
    let seq = app.event_counter.fetch_add(1, Ordering::SeqCst) + 1;
    format!(
        "graph_rebuild_{:016x}_{seq:020}",
        stable_token_hash(project_id)
    )
}

fn stable_token_hash(value: &str) -> u64 {
    let mut hash = 0xcbf2_9ce4_8422_2325_u64;
    for byte in value.as_bytes() {
        hash ^= *byte as u64;
        hash = hash.wrapping_mul(0x0000_0100_0000_01b3);
    }
    hash
}

async fn export_graph(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(query): Query<GraphExportQuery>,
) -> GraphApiResult<Json<GraphExportResponse>> {
    let project_id = require_project_id(query.project_id.as_deref())?;
    ensure_project_access(&app, &identity, project_id).await?;

    let snapshot = graph_project_snapshot(&app, project_id, cap_scan_limit(query.limit)).await?;
    let entities: Vec<EntityUpsertPayload> = snapshot
        .entities
        .into_iter()
        .map(EntityUpsertPayload::from_entity)
        .collect();
    let relationships: Vec<RelationshipUpsertPayload> = snapshot
        .relationships
        .into_iter()
        .map(RelationshipUpsertPayload::from_relationship)
        .collect();
    Ok(Json(GraphExportResponse {
        version: GRAPH_SNAPSHOT_VERSION,
        project_id: project_id.to_string(),
        exported_at: rfc3339(now_ms()),
        stats: GraphExportStats {
            entities_count: entities.len(),
            relationships_count: relationships.len(),
        },
        entities,
        relationships,
    }))
}

async fn import_graph(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Json(payload): Json<GraphImportPayload>,
) -> GraphApiResult<Json<GraphImportResponse>> {
    if payload.version != GRAPH_SNAPSHOT_VERSION {
        return Err(GraphApiError::bad_request(
            "unsupported graph snapshot version",
        ));
    }
    let project_id = require_project_id(Some(payload.project_id.as_str()))?.to_string();
    ensure_project_write(&app, &identity, &project_id).await?;

    if payload.entities.len() > GRAPH_IMPORT_MAX_ENTITIES {
        return Err(GraphApiError::bad_request(
            "too many graph entities to import",
        ));
    }
    if payload.relationships.len() > GRAPH_IMPORT_MAX_RELATIONSHIPS {
        return Err(GraphApiError::bad_request(
            "too many graph relationships to import",
        ));
    }
    for entity in &payload.entities {
        if entity.project_id != project_id {
            return Err(GraphApiError::bad_request(
                "graph import entity project_id must match package project_id",
            ));
        }
    }
    for rel in &payload.relationships {
        if rel.project_id != project_id {
            return Err(GraphApiError::bad_request(
                "graph import relationship project_id must match package project_id",
            ));
        }
    }

    let entities_imported = payload.entities.len();
    let relationships_imported = payload.relationships.len();
    for entity in payload.entities {
        app.graph
            .upsert_entity(entity.into_entity())
            .await
            .map_err(GraphApiError::internal)?;
    }
    for rel in payload.relationships {
        app.graph
            .upsert_relationship(rel.into_relationship())
            .await
            .map_err(GraphApiError::internal)?;
    }

    Ok(Json(GraphImportResponse {
        status: "success".to_string(),
        message: "Graph snapshot imported successfully".to_string(),
        version: GRAPH_SNAPSHOT_VERSION,
        project_id,
        entities_imported,
        relationships_imported,
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

/// Load the project slice once, hydrate a local in-memory graph from it, and
/// merge the per-seed `depth`-hop subgraphs against that local store — one
/// [`GraphStore::project_slice`] call on the backing store instead of one
/// `subgraph` round-trip per seed. The in-memory adapter is the cross-tier
/// parity oracle, so the per-seed BFS semantics match every backend exactly.
pub(crate) async fn merge_seed_subgraphs(
    graph: &Arc<dyn GraphStore>,
    project_id: &str,
    seed_ids: &[String],
    depth: usize,
    max_seeds: usize,
) -> CoreResult<Subgraph> {
    let (slice_entities, slice_relationships) = graph.project_slice(project_id).await?;
    let local = InMemoryGraphStore::from_slice(slice_entities, slice_relationships);
    let mut entity_ids = BTreeSet::new();
    let mut rel_ids = BTreeSet::new();
    let mut entities = Vec::new();
    let mut relationships = Vec::new();

    for seed_id in seed_ids.iter().take(max_seeds) {
        let subgraph = local.subgraph(project_id, seed_id, depth).await?;
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
    Ok(Subgraph {
        entities,
        relationships,
    })
}

async fn merge_subgraphs(
    app: &AppState,
    project_id: &str,
    seed_ids: &[String],
    depth: usize,
    limit: usize,
) -> GraphApiResult<Subgraph> {
    let mut merged = merge_seed_subgraphs(&app.graph, project_id, seed_ids, depth, limit)
        .await
        .map_err(GraphApiError::internal)?;
    merged.entities.truncate(limit);
    let entity_ids: BTreeSet<String> = merged
        .entities
        .iter()
        .map(|entity| entity.uuid.clone())
        .collect();
    merged.relationships.retain(|rel| {
        entity_ids.contains(&rel.source_uuid) && entity_ids.contains(&rel.target_uuid)
    });
    Ok(merged)
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

#[derive(Debug, Clone)]
struct ProjectCommunity {
    view: CommunityView,
    member_uuids: Vec<String>,
    members: Vec<EntityView>,
}

fn is_persisted_community_entity(entity: &GraphEntity) -> bool {
    entity.entity_type == PERSISTED_COMMUNITY_ENTITY_TYPE && entity.uuid.starts_with("community_")
}

fn is_persisted_community_relationship(rel: &Relationship) -> bool {
    rel.relation_type == PERSISTED_COMMUNITY_MEMBER_RELATION_TYPE
        && rel.source_uuid.starts_with("community_")
}

fn count_source_entities(graph: &Subgraph) -> usize {
    graph
        .entities
        .iter()
        .filter(|entity| !is_persisted_community_entity(entity))
        .count()
}

fn community_views(project_id: &str, graph: Subgraph, min_members: usize) -> Vec<CommunityView> {
    project_communities(project_id, graph, min_members)
        .into_iter()
        .map(|community| community.view)
        .collect()
}

fn project_communities(
    project_id: &str,
    graph: Subgraph,
    min_members: usize,
) -> Vec<ProjectCommunity> {
    let source_entities: Vec<GraphEntity> = graph
        .entities
        .into_iter()
        .filter(|entity| !is_persisted_community_entity(entity))
        .collect();
    let source_ids: BTreeSet<String> = source_entities
        .iter()
        .map(|entity| entity.uuid.clone())
        .collect();
    let nodes: Vec<String> = source_entities
        .iter()
        .map(|entity| entity.uuid.clone())
        .collect();
    let edges: Vec<CommunityEdge> = graph
        .relationships
        .into_iter()
        .filter(|rel| {
            !is_persisted_community_relationship(rel)
                && source_ids.contains(&rel.source_uuid)
                && source_ids.contains(&rel.target_uuid)
        })
        .map(|rel| CommunityEdge {
            source: rel.source_uuid.clone(),
            target: rel.target_uuid.clone(),
            weight: relationship_weight(&rel),
        })
        .collect();
    let by_uuid: BTreeMap<String, EntityView> = source_entities
        .into_iter()
        .map(|entity| {
            let view = EntityView::from(entity);
            (view.uuid.clone(), view)
        })
        .collect();

    detect_communities(&nodes, &edges, min_members)
        .into_iter()
        .map(|community| {
            let member_uuids = community.members.clone();
            let members: Vec<EntityView> = community
                .members
                .iter()
                .filter_map(|uuid| by_uuid.get(uuid).cloned())
                .collect();
            let tenant_id = members.iter().find_map(|entity| entity.tenant_id.clone());
            let view = CommunityView {
                uuid: community_id(project_id, &community.name, &community.members),
                name: community.name,
                summary: community_summary(&members),
                member_count: community.member_count,
                tenant_id,
                project_id: project_id.to_string(),
                formed_at: None,
                created_at: None,
            };
            ProjectCommunity {
                view,
                member_uuids,
                members,
            }
        })
        .collect()
}

async fn persist_community_projection(
    app: &AppState,
    project_id: &str,
    existing: &Subgraph,
    communities: &[ProjectCommunity],
    created_at_ms: i64,
) -> GraphApiResult<()> {
    let current_community_ids: BTreeSet<String> = communities
        .iter()
        .map(|community| community.view.uuid.clone())
        .collect();
    let current_member_rel_ids: BTreeSet<String> = communities
        .iter()
        .flat_map(|community| {
            community.member_uuids.iter().map(|member_uuid| {
                community_member_relationship_id(&community.view.uuid, member_uuid)
            })
        })
        .collect();

    for rel in existing
        .relationships
        .iter()
        .filter(|rel| is_persisted_community_relationship(rel))
        .filter(|rel| !current_member_rel_ids.contains(&rel.uuid))
    {
        app.graph
            .delete_relationship(project_id, &rel.uuid)
            .await
            .map_err(GraphApiError::internal)?;
    }

    for entity in existing
        .entities
        .iter()
        .filter(|entity| is_persisted_community_entity(entity))
        .filter(|entity| !current_community_ids.contains(&entity.uuid))
    {
        app.graph
            .delete_entity(project_id, &entity.uuid)
            .await
            .map_err(GraphApiError::internal)?;
    }

    for community in communities {
        app.graph
            .upsert_entity(GraphEntity {
                uuid: community.view.uuid.clone(),
                name: community.view.name.clone(),
                entity_type: PERSISTED_COMMUNITY_ENTITY_TYPE.to_string(),
                summary: community.view.summary.clone(),
                project_id: project_id.to_string(),
                tenant_id: community.view.tenant_id.clone(),
                created_at_ms,
                name_embedding: None,
            })
            .await
            .map_err(GraphApiError::internal)?;
        for member_uuid in &community.member_uuids {
            app.graph
                .upsert_relationship(Relationship {
                    uuid: community_member_relationship_id(&community.view.uuid, member_uuid),
                    source_uuid: community.view.uuid.clone(),
                    target_uuid: member_uuid.clone(),
                    relation_type: PERSISTED_COMMUNITY_MEMBER_RELATION_TYPE.to_string(),
                    fact: format!("{} contains {member_uuid}", community.view.name),
                    score: 1.0,
                    project_id: project_id.to_string(),
                    created_at_ms,
                })
                .await
                .map_err(GraphApiError::internal)?;
        }
    }
    Ok(())
}

fn community_member_relationship_id(community_uuid: &str, member_uuid: &str) -> String {
    format!(
        "community_member_{:016x}",
        stable_pair_hash(community_uuid, member_uuid)
    )
}

fn stable_pair_hash(left: &str, right: &str) -> u64 {
    let mut hash = 0xcbf2_9ce4_8422_2325_u64;
    for part in [left, right] {
        for byte in part.as_bytes() {
            hash ^= *byte as u64;
            hash = hash.wrapping_mul(0x0000_0100_0000_01b3);
        }
        hash ^= 0xff;
        hash = hash.wrapping_mul(0x0000_0100_0000_01b3);
    }
    hash
}

async fn find_community(
    app: &AppState,
    project_id: &str,
    community_uuid: &str,
    min_members: usize,
) -> GraphApiResult<Option<(CommunityView, Vec<EntityView>)>> {
    let snapshot = graph_project_snapshot(app, project_id, cap_scan_limit(None)).await?;
    let communities = project_communities(project_id, snapshot, min_members);
    let Some(community) = communities
        .into_iter()
        .find(|community| community.view.uuid == community_uuid)
    else {
        return Ok(None);
    };
    Ok(Some((community.view, community.members)))
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
        .route("/api/v1/graph/export", get(export_graph))
        .route("/api/v1/graph/import", post(import_graph))
        .route("/api/v1/graph/communities/", get(list_communities))
        .route("/api/v1/graph/communities", get(list_communities))
        .route(
            "/api/v1/graph/communities/rebuild",
            post(rebuild_communities),
        )
        .route(
            "/api/v1/graph/communities/rebuild/jobs/:job_id",
            get(get_rebuild_job),
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
mod tests;
