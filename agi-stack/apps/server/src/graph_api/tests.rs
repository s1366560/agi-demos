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
use crate::agent_events_api::{DevAgentEventReplayService, SharedAgentEvents};
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
    let agent_events: SharedAgentEvents =
        Arc::new(DevAgentEventReplayService::new(Arc::clone(&events)));
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
        skill_evolution_worker: None,
        tenant_skill_configs,
        workspaces,
        channels,
        hitl,
        agent_events,
        workspace_plan_outbox_worker: None,
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
