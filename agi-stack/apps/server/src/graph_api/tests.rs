use std::sync::{atomic::AtomicU64, Arc, Mutex};

use axum::extract::{Path, Query, State};
use serde_json::json;
use tokio::time::{sleep, Duration};

use agistack_adapters_mem::{
    HashEmbedding, InMemoryCheckpointStore, InMemoryContainerRuntime, InMemoryEventStream,
    InMemoryGraphStore, InMemoryMemoryRepository, InMemoryVectorIndex, StubLlm, SystemClock,
};
use agistack_core::ports::{CheckpointStore, EventStream, ToolHost};
use agistack_core::{MemoryService, ReActEngine};
use agistack_plugin_host::{ControlPlane, DataPlaneReconciler, PluginHost};

use super::*;
use crate::admin_access::{DevAdminAccessService, SharedAdminAccess};
use crate::admin_dlq_api::{DevAdminDlqService, SharedAdminDlq};
use crate::agent_events_api::{DevAgentEventReplayService, SharedAgentEvents};
use crate::artifacts_api::{DevArtifactService, SharedArtifacts};
use crate::attachments_api::{DevAttachmentService, SharedAttachments};
use crate::audit_api::{DevAuditLogService, SharedAuditLogs};
use crate::auth::{DevAuthenticator, SharedAuthenticator};
use crate::billing_api::{DevBillingService, SharedBilling};
use crate::channel_api::{DevChannelService, SharedChannels};
use crate::cron_api::{DevCronJobService, SharedCronJobs};
use crate::data_api::{DevDataStatsScopeService, SharedDataStats};
use crate::deploy_api::{DevDeployService, SharedDeploys};
use crate::events_api::{DevEventLogService, SharedEventLogs};
use crate::gene_api::{DevGeneService, SharedGenes};
use crate::graph_stores_api::{DevGraphStoreCatalogService, SharedGraphStores};
use crate::hitl_api::{DevHitlResponseService, SharedHitlResponses};
use crate::identity::{DevIdentityService, SharedIdentity};
use crate::instance_api::{DevInstanceService, SharedInstances};
use crate::llm_providers_api::{
    DevLlmProviderAssignmentService, DevLlmProviderCatalogService, DevLlmProviderHealthService,
    DevLlmProviderUsageService, SharedLlmProviderAssignments, SharedLlmProviderHealth,
    SharedLlmProviderUsage, SharedLlmProviders,
};
use crate::notifications_api::{DevNotificationService, SharedNotifications};
use crate::retrieval_stores_api::{DevRetrievalStoreCatalogService, SharedRetrievalStores};
use crate::sandbox_api::ProjectSandboxService;
use crate::schema_api::{DevProjectSchemaService, SharedProjectSchema};
use crate::shares_api::{DevShareService, SharedShares};
use crate::skill_api::{DevSkillService, SharedSkills};
use crate::subagents_api::{DevSubagentTemplateService, SharedSubagentTemplates};
use crate::support_api::{DevSupportService, SharedSupport};
use crate::tenant_skill_config_api::{DevTenantSkillConfigService, SharedTenantSkillConfigs};
use crate::tenant_webhooks_api::{DevTenantWebhookService, SharedTenantWebhooks};
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
    let admin_access: SharedAdminAccess = Arc::new(DevAdminAccessService::new("dev-user"));
    let skills: SharedSkills = Arc::new(DevSkillService::new("dev-tenant"));
    let tenant_skill_configs: SharedTenantSkillConfigs =
        Arc::new(DevTenantSkillConfigService::new("dev-tenant"));
    let workspaces: SharedWorkspaces = Arc::new(DevWorkspaceService::new("dev-user"));
    let channels: SharedChannels = Arc::new(DevChannelService::new());
    let events: Arc<dyn EventStream> = Arc::new(InMemoryEventStream::new());
    let agent_events: SharedAgentEvents =
        Arc::new(DevAgentEventReplayService::new(Arc::clone(&events)));
    let event_logs: SharedEventLogs = Arc::new(DevEventLogService::default());
    let audit_logs: SharedAuditLogs = Arc::new(DevAuditLogService::default());
    let notifications: SharedNotifications = Arc::new(DevNotificationService::default());
    let billing: SharedBilling = Arc::new(DevBillingService::default());
    let support: SharedSupport = Arc::new(DevSupportService::default());
    let artifacts: SharedArtifacts = Arc::new(DevArtifactService::default());
    let attachments: SharedAttachments = Arc::new(DevAttachmentService::default());
    let admin_dlq: SharedAdminDlq = Arc::new(DevAdminDlqService::empty("dev-user"));
    let llm_providers: SharedLlmProviders = Arc::new(DevLlmProviderCatalogService::default());
    let llm_provider_health: SharedLlmProviderHealth =
        Arc::new(DevLlmProviderHealthService::default());
    let llm_provider_assignments: SharedLlmProviderAssignments =
        Arc::new(DevLlmProviderAssignmentService::default());
    let llm_provider_usage: SharedLlmProviderUsage = Arc::new(DevLlmProviderUsageService);
    let tenant_webhooks: SharedTenantWebhooks = Arc::new(DevTenantWebhookService::default());
    let project_schema: SharedProjectSchema = Arc::new(DevProjectSchemaService::default());
    let cron_jobs: SharedCronJobs = Arc::new(DevCronJobService::default());
    let data_stats: SharedDataStats = Arc::new(DevDataStatsScopeService::default());
    let deploys: SharedDeploys = Arc::new(DevDeployService::default());
    let subagent_templates: SharedSubagentTemplates =
        Arc::new(DevSubagentTemplateService::default());
    let instances: SharedInstances = Arc::new(DevInstanceService::default());
    let genes: SharedGenes = Arc::new(DevGeneService::default());
    let graph_stores: SharedGraphStores = Arc::new(DevGraphStoreCatalogService::new("dev-tenant"));
    let retrieval_stores: SharedRetrievalStores =
        Arc::new(DevRetrievalStoreCatalogService::new("dev-tenant"));
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
        admin_access,
        skills,
        skill_evolution_worker: None,
        tenant_skill_configs,
        workspaces,
        channels,
        channel_outbox_delivery_worker: None,
        hitl,
        agent_events,
        event_logs,
        audit_logs,
        notifications,
        billing,
        support,
        artifacts,
        attachments,
        admin_dlq,
        llm_providers,
        llm_provider_health,
        llm_provider_assignments,
        llm_provider_usage,
        tenant_webhooks,
        project_schema,
        cron_jobs,
        data_stats,
        deploys,
        subagent_templates,
        instances,
        genes,
        graph_stores,
        retrieval_stores,
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
            job_id: None,
            job_status: None,
            event_topic: None,
            requested_event_id: None,
        }
    );
}

#[tokio::test]
async fn rebuild_communities_background_persists_job_events_and_worker_completion() {
    let app = test_state();
    seed_two_community_graph(&app).await;

    let Json(response) = rebuild_communities(
        State(app.clone()),
        Extension(identity()),
        Query(RebuildCommunitiesQuery {
            project_id: Some("p1".to_string()),
            background: true,
        }),
    )
    .await
    .unwrap();

    let golden = serde_json::from_str(include_str!(
        "../../tests/golden/graph_community_rebuild_background_queued.json"
    ))
    .unwrap();
    let actual = serde_json::to_value(&response).unwrap();
    agistack_parity::assert_parity(&golden, &actual);

    let job_id = response.job_id.clone().unwrap();
    let events = wait_for_graph_rebuild_completion(&app, "p1", &job_id).await;
    let event_types: Vec<&str> = events
        .iter()
        .filter_map(|event| event["type"].as_str())
        .collect();
    assert_eq!(
        event_types,
        vec![
            "graph_community_rebuild_requested",
            "graph_community_rebuild_started",
            "graph_community_rebuild_completed",
        ]
    );
    assert!(events.iter().all(|event| event["job_id"] == job_id));
    let completed = events
        .iter()
        .find(|event| event["type"] == "graph_community_rebuild_completed")
        .unwrap();
    assert_eq!(completed["job_status"], "completed");
    assert_eq!(completed["communities_count"], 2);
    assert_eq!(completed["entities_processed"], 6);
}

#[tokio::test]
async fn rebuild_communities_job_status_matches_golden() {
    let app = test_state();
    seed_two_community_graph(&app).await;

    let Json(response) = rebuild_communities(
        State(app.clone()),
        Extension(identity()),
        Query(RebuildCommunitiesQuery {
            project_id: Some("p1".to_string()),
            background: true,
        }),
    )
    .await
    .unwrap();

    let job_id = response.job_id.clone().unwrap();
    wait_for_graph_rebuild_completion(&app, "p1", &job_id).await;

    let Json(status) = get_rebuild_job(
        State(app.clone()),
        Extension(identity()),
        Path(job_id.clone()),
        Query(RebuildCommunityJobQuery {
            project_id: Some("p1".to_string()),
        }),
    )
    .await
    .unwrap();

    assert_eq!(status.job_id, job_id);
    assert_eq!(status.job_status, "completed");
    assert_eq!(status.communities_count, Some(2));
    assert_eq!(status.entities_processed, Some(6));
    assert_eq!(status.persisted_communities_count, Some(2));
    assert_eq!(status.events.len(), 3);
    let golden = serde_json::from_str(include_str!(
        "../../tests/golden/graph_community_rebuild_job_status.json"
    ))
    .unwrap();
    let actual = serde_json::to_value(&status).unwrap();
    agistack_parity::assert_parity(&golden, &actual);

    let err = get_rebuild_job(
        State(app),
        Extension(identity()),
        Path("missing-job".to_string()),
        Query(RebuildCommunityJobQuery {
            project_id: Some("p1".to_string()),
        }),
    )
    .await
    .unwrap_err();
    assert_eq!(err.status, StatusCode::NOT_FOUND);
    assert_eq!(err.detail, "Community rebuild job not found");
}

#[tokio::test]
async fn rebuild_communities_persists_community_nodes_without_polluting_detection() {
    let app = test_state();
    seed_two_community_graph(&app).await;

    let Json(response) = rebuild_communities(
        State(app.clone()),
        Extension(identity()),
        Query(RebuildCommunitiesQuery {
            project_id: Some("p1".to_string()),
            background: false,
        }),
    )
    .await
    .unwrap();
    assert_eq!(response.communities_count, 2);
    assert_eq!(response.entities_processed, 6);

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

    let community = page.communities[0].clone();
    let persisted = app
        .graph
        .get_entity("p1", &community.uuid)
        .await
        .unwrap()
        .expect("community entity should be persisted");
    assert_eq!(persisted.entity_type, "Community");
    assert_eq!(persisted.name, community.name);
    assert_eq!(persisted.summary, community.summary);

    let graph = app.graph.subgraph("p1", &community.uuid, 1).await.unwrap();
    assert_eq!(
        graph
            .relationships
            .iter()
            .filter(|rel| rel.relation_type == "HAS_MEMBER")
            .count(),
        3
    );

    let Json(second_response) = rebuild_communities(
        State(app.clone()),
        Extension(identity()),
        Query(RebuildCommunitiesQuery {
            project_id: Some("p1".to_string()),
            background: false,
        }),
    )
    .await
    .unwrap();
    assert_eq!(second_response.communities_count, 2);
    assert_eq!(second_response.entities_processed, 6);
}

#[tokio::test]
async fn rebuild_communities_prunes_stale_persisted_community_artifacts() {
    let app = test_state();
    seed_two_community_graph(&app).await;

    let Json(response) = rebuild_communities(
        State(app.clone()),
        Extension(identity()),
        Query(RebuildCommunitiesQuery {
            project_id: Some("p1".to_string()),
            background: false,
        }),
    )
    .await
    .unwrap();
    assert_eq!(response.communities_count, 2);

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
    let stale_community = page
        .communities
        .iter()
        .find(|community| community.summary.contains('X'))
        .expect("x/y/z community should exist")
        .uuid
        .clone();
    assert!(app
        .graph
        .get_entity("p1", &stale_community)
        .await
        .unwrap()
        .is_some());

    for entity_id in ["x", "y", "z"] {
        app.graph
            .delete_entity("p1", entity_id)
            .await
            .expect("remove source entity");
    }
    assert!(app
        .graph
        .get_entity("p1", &stale_community)
        .await
        .unwrap()
        .is_some());

    let Json(second_response) = rebuild_communities(
        State(app.clone()),
        Extension(identity()),
        Query(RebuildCommunitiesQuery {
            project_id: Some("p1".to_string()),
            background: false,
        }),
    )
    .await
    .unwrap();
    assert_eq!(second_response.communities_count, 1);
    assert_eq!(second_response.entities_processed, 3);

    assert!(app
        .graph
        .get_entity("p1", &stale_community)
        .await
        .unwrap()
        .is_none());
    let Json(entities) = list_entities(
        State(app),
        Extension(identity()),
        Query(EntityQuery {
            project_id: Some("p1".to_string()),
            q: Some(String::new()),
            limit: Some(100),
            offset: None,
        }),
    )
    .await
    .unwrap();
    assert!(!entities
        .entities
        .iter()
        .any(|entity| entity.uuid == stale_community));
}

async fn wait_for_graph_rebuild_completion(
    app: &AppState,
    project_id: &str,
    job_id: &str,
) -> Vec<serde_json::Value> {
    let topic = graph_rebuild_topic(project_id);
    for _ in 0..50 {
        let entries = app.events.read_after(&topic, "", 10).await.unwrap();
        let events: Vec<serde_json::Value> = entries
            .into_iter()
            .map(|entry| serde_json::from_str(&entry.payload).unwrap())
            .filter(|event: &serde_json::Value| event["job_id"] == job_id)
            .collect();
        if events
            .iter()
            .any(|event| event["type"] == "graph_community_rebuild_completed")
        {
            return events;
        }
        sleep(Duration::from_millis(10)).await;
    }
    panic!("background graph community rebuild did not complete");
}

#[tokio::test]
async fn graph_export_matches_golden_and_import_roundtrips_project_snapshot() {
    let app = test_state();
    for payload in [sample_entity("e1", "Alpha"), sample_entity("e2", "Beta")] {
        upsert_entity(State(app.clone()), Extension(identity()), Json(payload))
            .await
            .unwrap();
    }
    seed_relationship(&app, "r1", "e1", "e2").await;

    let Json(exported) = export_graph(
        State(app.clone()),
        Extension(identity()),
        Query(GraphExportQuery {
            project_id: Some("p1".to_string()),
            limit: Some(10),
        }),
    )
    .await
    .unwrap();
    let golden = serde_json::from_str(include_str!(
        "../../tests/golden/graph_export_snapshot.json"
    ))
    .unwrap();
    let actual = serde_json::to_value(&exported).unwrap();
    agistack_parity::assert_parity(&golden, &actual);

    let imported_app = test_state();
    let Json(imported) = import_graph(
        State(imported_app.clone()),
        Extension(identity()),
        Json(GraphImportPayload {
            version: exported.version,
            project_id: exported.project_id.clone(),
            entities: exported.entities.clone(),
            relationships: exported.relationships.clone(),
        }),
    )
    .await
    .unwrap();
    assert_eq!(
        imported,
        GraphImportResponse {
            status: "success".to_string(),
            message: "Graph snapshot imported successfully".to_string(),
            version: 1,
            project_id: "p1".to_string(),
            entities_imported: 2,
            relationships_imported: 1,
        }
    );

    let Json(elements) = get_subgraph(
        State(imported_app),
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
    assert_eq!(elements["elements"]["edges"].as_array().unwrap().len(), 1);
}

#[tokio::test]
async fn graph_import_rejects_cross_project_package_members() {
    let app = test_state();
    let mut entity = sample_entity("e1", "Alpha");
    entity.project_id = "p2".to_string();

    let err = import_graph(
        State(app),
        Extension(identity()),
        Json(GraphImportPayload {
            version: 1,
            project_id: "p1".to_string(),
            entities: vec![entity],
            relationships: Vec::new(),
        }),
    )
    .await
    .unwrap_err();
    assert_eq!(err.status, StatusCode::BAD_REQUEST);
    assert_eq!(
        err.detail,
        "graph import entity project_id must match package project_id"
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
