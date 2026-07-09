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
use crate::admin_access::{DevAdminAccessService, SharedAdminAccess};
use crate::admin_dlq_api::{DevAdminDlqService, SharedAdminDlq};
use crate::agent_conversations_api::{DevAgentConversationService, SharedAgentConversations};
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
    let agent_conversations: SharedAgentConversations =
        Arc::new(DevAgentConversationService::new(Arc::clone(&events)));
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
        agent_event_writer: None,
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
        agent_conversations,
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

fn entity(uuid: &str, name: &str, entity_type: &str, created_at_ms: i64) -> GraphEntity {
    entity_in_project(uuid, name, entity_type, created_at_ms, "p1", Some("t1"))
}

fn entity_in_project(
    uuid: &str,
    name: &str,
    entity_type: &str,
    created_at_ms: i64,
    project_id: &str,
    tenant_id: Option<&str>,
) -> GraphEntity {
    GraphEntity {
        uuid: uuid.to_string(),
        name: name.to_string(),
        entity_type: entity_type.to_string(),
        summary: format!("{name} summary"),
        project_id: project_id.to_string(),
        tenant_id: tenant_id.map(str::to_string),
        created_at_ms,
        name_embedding: None,
    }
}

fn relationship(uuid: &str, source: &str, target: &str, relation_type: &str) -> Relationship {
    relationship_in_project(uuid, source, target, relation_type, "p1")
}

fn relationship_in_project(
    uuid: &str,
    source: &str,
    target: &str,
    relation_type: &str,
    project_id: &str,
) -> Relationship {
    Relationship {
        uuid: uuid.to_string(),
        source_uuid: source.to_string(),
        target_uuid: target.to_string(),
        relation_type: relation_type.to_string(),
        fact: format!("{source} {relation_type} {target}"),
        score: 1.0,
        project_id: project_id.to_string(),
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
            tenant_id: None,
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
async fn memory_search_fanout_uses_identity_project_membership() {
    let app = test_state();
    app.graph
        .upsert_entity(entity_in_project(
            "dev-alpha",
            "Dev Alpha",
            "Concept",
            1_700_000_000_000,
            "dev-project",
            Some("dev-tenant"),
        ))
        .await
        .unwrap();
    app.graph
        .upsert_entity(entity_in_project(
            "other-alpha",
            "Other Alpha",
            "Concept",
            1_700_000_000_000,
            "p1",
            Some("t1"),
        ))
        .await
        .unwrap();

    let Json(result) = memory_search(
        State(app),
        Extension(identity()),
        Json(MemorySearchRequest {
            query: "Alpha".to_string(),
            limit: Some(10),
            tenant_id: None,
            project_id: None,
        }),
    )
    .await
    .unwrap();

    let golden: Value = serde_json::from_str(include_str!(
        "../../tests/golden/enhanced_search_memory_fanout.json"
    ))
    .expect("enhanced search fanout golden parses");
    agistack_parity::assert_parity(&golden, &result);
    assert_eq!(result["total"], 1);
    assert_eq!(result["results"][0]["uuid"], "dev-alpha");
    assert_eq!(
        result["results"][0]["metadata"]["project_id"],
        "dev-project"
    );
    assert_eq!(result["scope"]["project_ids"][0], "dev-project");
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
async fn graph_traversal_fanout_uses_identity_project_membership_for_start_entity() {
    let app = test_state();
    for entity in [
        entity_in_project(
            "dev-a",
            "Dev Alpha",
            "Concept",
            1_700_000_000_000,
            "dev-project",
            Some("dev-tenant"),
        ),
        entity_in_project(
            "dev-b",
            "Dev Beta",
            "Concept",
            1_700_010_000_000,
            "dev-project",
            Some("dev-tenant"),
        ),
        entity_in_project(
            "dev-c",
            "Dev Gamma",
            "Concept",
            1_700_020_000_000,
            "dev-project",
            Some("dev-tenant"),
        ),
        entity_in_project(
            "other-a",
            "Other Alpha",
            "Concept",
            1_700_000_000_000,
            "p1",
            Some("t1"),
        ),
    ] {
        app.graph.upsert_entity(entity).await.unwrap();
    }
    for rel in [
        relationship_in_project("dev-r1", "dev-a", "dev-b", "MENTIONS", "dev-project"),
        relationship_in_project("dev-r2", "dev-b", "dev-c", "MENTIONS", "dev-project"),
        relationship_in_project("other-r1", "other-a", "dev-a", "MENTIONS", "p1"),
    ] {
        app.graph.upsert_relationship(rel).await.unwrap();
    }

    let Json(result) = search_graph_traversal(
        State(app),
        Extension(identity()),
        Json(TraversalSearchRequest {
            start_entity_uuid: "dev-a".to_string(),
            max_depth: 2,
            relationship_types: Some(vec!["MENTIONS".to_string()]),
            limit: Some(10),
            tenant_id: None,
            project_id: None,
        }),
    )
    .await
    .unwrap();

    let golden: Value = serde_json::from_str(include_str!(
        "../../tests/golden/enhanced_search_traversal_fanout.json"
    ))
    .expect("enhanced search traversal fanout golden parses");
    agistack_parity::assert_parity(&golden, &result);
    assert_eq!(result["total"], 3);
    assert_eq!(result["scope"]["project_ids"][0], "dev-project");
    assert!(result["results"].as_array().unwrap().iter().all(|item| {
        item["metadata"]["project_id"] == "dev-project" && item["uuid"] != "other-a"
    }));
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
async fn community_search_fanout_uses_identity_project_membership() {
    let app = test_state();
    for entity in [
        entity_in_project(
            "dev-a",
            "Dev Alpha",
            "Concept",
            1_700_000_000_000,
            "dev-project",
            Some("dev-tenant"),
        ),
        entity_in_project(
            "dev-b",
            "Dev Beta",
            "Concept",
            1_700_010_000_000,
            "dev-project",
            Some("dev-tenant"),
        ),
        entity_in_project(
            "dev-c",
            "Dev Gamma",
            "Concept",
            1_700_020_000_000,
            "dev-project",
            Some("dev-tenant"),
        ),
        entity_in_project(
            "other-a",
            "Other Alpha",
            "Concept",
            1_700_000_000_000,
            "p1",
            Some("t1"),
        ),
    ] {
        app.graph.upsert_entity(entity).await.unwrap();
    }
    for rel in [
        relationship_in_project("dev-r1", "dev-a", "dev-b", "MENTIONS", "dev-project"),
        relationship_in_project("dev-r2", "dev-b", "dev-c", "MENTIONS", "dev-project"),
        relationship_in_project("dev-r3", "dev-a", "dev-c", "MENTIONS", "dev-project"),
    ] {
        app.graph.upsert_relationship(rel).await.unwrap();
    }
    let snapshot = project_snapshot(&app, "dev-project").await.unwrap();
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
    let id = community_id("dev-project", &community.name, &community.members);

    let Json(result) = search_community(
        State(app),
        Extension(identity()),
        Json(CommunitySearchRequest {
            community_uuid: id,
            limit: Some(2),
            include_episodes: true,
            project_id: None,
        }),
    )
    .await
    .unwrap();

    let golden: Value = serde_json::from_str(include_str!(
        "../../tests/golden/enhanced_search_community_fanout.json"
    ))
    .expect("enhanced search community fanout golden parses");
    agistack_parity::assert_parity(&golden, &result);
    assert_eq!(result["total"], 2);
    assert_eq!(result["scope"]["project_ids"][0], "dev-project");
    assert_eq!(
        result["results"][0]["metadata"]["project_id"],
        "dev-project"
    );
}

#[tokio::test]
async fn capabilities_and_error_envelopes_are_fastapi_compatible() {
    let Json(capabilities) = search_capabilities().await;
    assert_eq!(
        capabilities["search_types"]["faceted"]["endpoint"],
        "/api/v1/search-enhanced/faceted"
    );
    let golden: Value = serde_json::from_str(include_str!(
        "../../tests/golden/enhanced_search_capabilities.json"
    ))
    .expect("enhanced search capabilities golden parses");
    agistack_parity::assert_parity(&golden, &capabilities);

    let app = test_state();
    let err = memory_search(
        State(app),
        Extension(identity()),
        Json(MemorySearchRequest {
            query: "".to_string(),
            limit: None,
            tenant_id: None,
            project_id: Some("p1".to_string()),
        }),
    )
    .await
    .unwrap_err();
    let response = err.into_response();
    assert_eq!(response.status(), StatusCode::BAD_REQUEST);
}
