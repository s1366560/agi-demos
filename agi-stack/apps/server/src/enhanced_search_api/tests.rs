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
use crate::channel_api::{DevChannelService, SharedChannels};
use crate::hitl_api::{DevHitlResponseService, SharedHitlResponses};
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
    let channels: SharedChannels = Arc::new(DevChannelService::new());
    let events: Arc<dyn EventStream> = Arc::new(InMemoryEventStream::new());
    let hitl: SharedHitlResponses = Arc::new(DevHitlResponseService::new(Arc::clone(&events)));

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
        channels,
        hitl,
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
