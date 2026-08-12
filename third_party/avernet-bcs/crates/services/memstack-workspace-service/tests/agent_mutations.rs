use std::error::Error;
use std::sync::atomic::{AtomicUsize, Ordering};

use async_trait::async_trait;
use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement};
use bcs_db_local::LocalSqliteDbPlugin;
use memstack_workspace_service::{
    CreateWorkspaceContentInput, CreateWorkspaceInput, CreateWorkspaceOwnerInput,
    CreateWorkspaceScopeInput, PublicBindWorkspaceAgentInput, PublicUnbindWorkspaceAgentInput,
    PublicUpdateWorkspaceAgentInput, PublicWorkspaceAgentMutationService,
    PublicWorkspaceMutationContext, PublicWorkspaceMutationErrorKind, WorkspaceCreationService,
};
use memstack_workspace_service_api::{
    AgentRegistryAgent, AgentRegistryLookup, AgentRegistryPort, AgentRegistryPortError,
};
use serde_json::{Value, json};

struct StaticRegistry {
    available: bool,
    calls: AtomicUsize,
}

impl StaticRegistry {
    fn available() -> Self {
        Self {
            available: true,
            calls: AtomicUsize::new(0),
        }
    }

    fn missing() -> Self {
        Self {
            available: false,
            calls: AtomicUsize::new(0),
        }
    }
}

#[async_trait]
impl AgentRegistryPort for StaticRegistry {
    async fn resolve(
        &self,
        lookup: &AgentRegistryLookup,
    ) -> Result<Option<AgentRegistryAgent>, AgentRegistryPortError> {
        self.calls.fetch_add(1, Ordering::Relaxed);
        if !self.available {
            return Ok(None);
        }
        Ok(Some(
            AgentRegistryAgent::parse(
                lookup.agent_id().as_str(),
                "planner",
                Some("Registry Planner".to_string()),
                true,
            )
            .map_err(|_| AgentRegistryPortError::Unavailable)?,
        ))
    }
}

#[tokio::test]
async fn bind_update_and_unbind_keep_binding_bot_roster_receipt_and_outbox_atomic()
-> Result<(), Box<dyn Error>> {
    let db = seeded_db().await?;
    let registry = StaticRegistry::available();
    let service = PublicWorkspaceAgentMutationService::new(&db, DbSqlFlavor::Sqlite, &registry);

    let bound = service
        .bind(&bind_input("bind-agent", 1, "agent-1", 2, -1))
        .await?;
    let binding_id = bound.response["id"].as_str().ok_or("missing binding id")?;
    assert_eq!(bound.committed_revision, 2);
    assert_eq!(bound.response["display_name"], "Workspace Planner");
    assert_eq!(
        scalar_i64(
            &db,
            "SELECT COUNT(*) AS value FROM workspace_agent_bindings"
        )
        .await?,
        1
    );
    assert_eq!(
        scalar_i64(&db, "SELECT COUNT(*) AS value FROM bcs_bots").await?,
        1
    );
    assert_eq!(
        scalar_i64(
            &db,
            "SELECT COUNT(*) AS value FROM bcs_group_participants WHERE actor_kind = 'bot'",
        )
        .await?,
        1
    );

    let rebound = service
        .bind(&PublicBindWorkspaceAgentInput {
            context: context("rebind-agent", 2, "owner-1"),
            agent_id: "agent-1".to_string(),
            display_name: Some("Renamed Planner".to_string()),
            description: None,
            config: json!({"mode": "review"}),
            is_active: false,
            hex_q: Some(3),
            hex_r: Some(-1),
            theme_color: Some("12345678901234567890123456789012".to_string()),
            label: Some("review".to_string()),
        })
        .await?;
    assert_eq!(rebound.response["id"], binding_id);
    assert_eq!(rebound.response["is_active"], false);
    assert_eq!(
        scalar_string(
            &db,
            "SELECT payload_json AS value FROM workspace_outbox WHERE event_sequence = 3",
        )
        .await?
        .parse::<Value>()?["is_update"],
        true
    );
    assert_eq!(
        scalar_string(&db, "SELECT status AS value FROM bcs_bots").await?,
        "offline"
    );

    let updated = service
        .update(&PublicUpdateWorkspaceAgentInput {
            context: context("update-agent", 3, "owner-1"),
            workspace_agent_id: binding_id.to_string(),
            display_name: None,
            description: Some("Updated description".to_string()),
            config: None,
            is_active: Some(true),
            hex_q: Some(4),
            hex_r: Some(-2),
            theme_color: None,
            label: Some("relay".to_string()),
        })
        .await?;
    assert_eq!(updated.committed_revision, 4);
    assert_eq!(updated.response["display_name"], "Renamed Planner");
    assert_eq!(updated.response["description"], "Updated description");
    assert_eq!(updated.response["config"], json!({"mode": "review"}));
    assert_eq!(updated.response["hex_q"], 4);
    assert_eq!(
        scalar_string(&db, "SELECT status AS value FROM bcs_bots").await?,
        "online"
    );

    let unbind_input = PublicUnbindWorkspaceAgentInput {
        context: context("unbind-agent", 4, "owner-1"),
        workspace_agent_id: binding_id.to_string(),
    };
    let unbound = service.unbind(&unbind_input).await?;
    let replayed = service.unbind(&unbind_input).await?;
    assert_eq!(unbound.committed_revision, 5);
    assert!(replayed.replayed);
    assert_eq!(
        scalar_i64(
            &db,
            "SELECT COUNT(*) AS value FROM workspace_agent_bindings"
        )
        .await?,
        0
    );
    assert_eq!(
        scalar_i64(&db, "SELECT COUNT(*) AS value FROM bcs_bots").await?,
        0
    );
    assert_eq!(
        scalar_i64(
            &db,
            "SELECT COUNT(*) AS value FROM bcs_group_participants WHERE actor_kind = 'bot'",
        )
        .await?,
        0
    );
    assert_eq!(
        scalar_i64(
            &db,
            "SELECT COUNT(*) AS value FROM workspace_mutation_receipts"
        )
        .await?,
        5
    );
    assert_eq!(
        scalar_i64(&db, "SELECT COUNT(*) AS value FROM workspace_outbox").await?,
        5
    );
    Ok(())
}

#[tokio::test]
async fn occupied_topology_hex_rejects_update_without_partial_agent_writes()
-> Result<(), Box<dyn Error>> {
    let db = seeded_db().await?;
    let registry = StaticRegistry::available();
    let service = PublicWorkspaceAgentMutationService::new(&db, DbSqlFlavor::Sqlite, &registry);
    let bound = service
        .bind(&bind_input("bind-for-conflict", 1, "agent-1", 2, -1))
        .await?;
    let binding_id = bound.response["id"].as_str().ok_or("missing binding id")?;
    db.execute(DbStatement::new(
        "INSERT INTO workspace_topology_nodes (node_id, tenant_id, project_id, workspace_id, hex_q, hex_r) VALUES ('node-1', 'tenant-1', 'project-1', 'workspace-1', 3, -1)",
    ))
    .await?;

    let error = match service
        .update(&PublicUpdateWorkspaceAgentInput {
            context: context("occupied-agent-update", 2, "owner-1"),
            workspace_agent_id: binding_id.to_string(),
            display_name: None,
            description: None,
            config: None,
            is_active: None,
            hex_q: Some(3),
            hex_r: Some(-1),
            theme_color: None,
            label: None,
        })
        .await
    {
        Ok(_) => return Err("occupied topology position must fail".into()),
        Err(error) => error,
    };

    assert_eq!(error.kind(), PublicWorkspaceMutationErrorKind::Validation);
    assert_eq!(
        scalar_i64(&db, "SELECT revision AS value FROM workspace_authorities").await?,
        2
    );
    assert_eq!(
        scalar_i64(&db, "SELECT hex_q AS value FROM workspace_agent_bindings").await?,
        2
    );
    assert_eq!(
        scalar_i64(&db, "SELECT COUNT(*) AS value FROM workspace_outbox").await?,
        2
    );
    Ok(())
}

#[tokio::test]
async fn missing_registry_agent_and_viewer_access_fail_before_any_roster_write()
-> Result<(), Box<dyn Error>> {
    let db = seeded_db().await?;
    let missing_registry = StaticRegistry::missing();
    let missing_service =
        PublicWorkspaceAgentMutationService::new(&db, DbSqlFlavor::Sqlite, &missing_registry);
    let missing_error = match missing_service
        .bind(&bind_input("missing-agent", 1, "agent-missing", 2, -1))
        .await
    {
        Ok(_) => return Err("missing registry Agent must fail".into()),
        Err(error) => error,
    };
    assert_eq!(
        missing_error.kind(),
        PublicWorkspaceMutationErrorKind::Validation
    );
    assert_eq!(missing_registry.calls.load(Ordering::Relaxed), 1);

    db.execute(DbStatement::new(
        "INSERT INTO workspace_members (member_id, tenant_id, project_id, workspace_id, user_id, participant_actor_id, role) VALUES ('viewer-member', 'tenant-1', 'project-1', 'workspace-1', 'viewer-1', 'viewer-1', 'viewer')",
    ))
    .await?;
    let available_registry = StaticRegistry::available();
    let viewer_service =
        PublicWorkspaceAgentMutationService::new(&db, DbSqlFlavor::Sqlite, &available_registry);
    let viewer_error = match viewer_service
        .bind(&PublicBindWorkspaceAgentInput {
            context: context("viewer-bind", 1, "viewer-1"),
            ..bind_input("ignored", 1, "agent-1", 2, -1)
        })
        .await
    {
        Ok(_) => return Err("viewer bind must fail".into()),
        Err(error) => error,
    };
    assert_eq!(
        viewer_error.kind(),
        PublicWorkspaceMutationErrorKind::Forbidden
    );
    assert_eq!(available_registry.calls.load(Ordering::Relaxed), 0);
    assert_eq!(
        scalar_i64(
            &db,
            "SELECT COUNT(*) AS value FROM workspace_agent_bindings"
        )
        .await?,
        0
    );
    assert_eq!(
        scalar_i64(&db, "SELECT revision AS value FROM workspace_authorities").await?,
        1
    );
    assert_eq!(
        scalar_i64(&db, "SELECT COUNT(*) AS value FROM workspace_outbox").await?,
        1
    );
    Ok(())
}

fn bind_input(
    idempotency_key: &str,
    revision: u64,
    agent_id: &str,
    hex_q: i64,
    hex_r: i64,
) -> PublicBindWorkspaceAgentInput {
    PublicBindWorkspaceAgentInput {
        context: context(idempotency_key, revision, "owner-1"),
        agent_id: agent_id.to_string(),
        display_name: Some("Workspace Planner".to_string()),
        description: Some("Plans work".to_string()),
        config: json!({"mode": "plan"}),
        is_active: true,
        hex_q: Some(hex_q),
        hex_r: Some(hex_r),
        theme_color: Some("#8b5cf6".to_string()),
        label: Some("planner".to_string()),
    }
}

fn context(idempotency_key: &str, revision: u64, user_id: &str) -> PublicWorkspaceMutationContext {
    PublicWorkspaceMutationContext {
        tenant_id: "tenant-1".to_string(),
        project_id: "project-1".to_string(),
        workspace_id: "workspace-1".to_string(),
        user_id: user_id.to_string(),
        expected_revision: Some(revision),
        idempotency_key: Some(idempotency_key.to_string()),
    }
}

async fn seeded_db() -> Result<LocalSqliteDbPlugin, Box<dyn Error>> {
    let db = LocalSqliteDbPlugin::new()?;
    for ddl in [
        "CREATE TABLE project_principal_memberships (tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, user_id TEXT NOT NULL, participant_actor_id TEXT NOT NULL, is_active INTEGER NOT NULL, PRIMARY KEY (tenant_id, project_id, user_id))",
        "CREATE TABLE bcs_groups (group_id TEXT NOT NULL, label TEXT, status TEXT NOT NULL, driver_bot TEXT NOT NULL, originator TEXT, env TEXT NOT NULL, routing_policy_json TEXT, context TEXT, group_kind TEXT NOT NULL DEFAULT 'normal', version INTEGER NOT NULL DEFAULT 1, record_status TEXT NOT NULL DEFAULT 'active', lifecycle_status TEXT NOT NULL DEFAULT 'active', group_strategy TEXT NOT NULL DEFAULT 'chat', created_by TEXT, visibility TEXT NOT NULL DEFAULT 'private', gmt_modified TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(group_id, env))",
        "CREATE TABLE bcs_group_participants (group_id TEXT NOT NULL, bot_uuid TEXT NOT NULL, role TEXT NOT NULL, env TEXT NOT NULL, actor_kind TEXT NOT NULL DEFAULT 'bot', mode TEXT NOT NULL DEFAULT 'auto', gmt_create TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, gmt_modified TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(env, group_id, bot_uuid))",
        "CREATE TABLE bcs_bots (bot_uuid TEXT NOT NULL, name TEXT NOT NULL, bot_info TEXT, registered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, env TEXT NOT NULL, visibility TEXT NOT NULL DEFAULT 'public', created_by TEXT, actor_kind TEXT NOT NULL DEFAULT 'bot', status TEXT NOT NULL DEFAULT 'online', is_deleted INTEGER NOT NULL DEFAULT 0, agent_code TEXT, gmt_create TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, gmt_modified TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(bot_uuid, env))",
        "CREATE TABLE workspace_profiles (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, group_id TEXT NOT NULL UNIQUE, name TEXT NOT NULL, description TEXT, created_by TEXT NOT NULL, is_archived INTEGER NOT NULL DEFAULT 0, office_status TEXT NOT NULL DEFAULT 'inactive', hex_layout_config_json TEXT NOT NULL DEFAULT '{}', default_blocking_categories_json TEXT NOT NULL DEFAULT '[]', metadata_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, deleted_at TEXT, deleted_by TEXT, UNIQUE(tenant_id, project_id, workspace_id), UNIQUE(tenant_id, project_id, name))",
        "CREATE TABLE workspace_members (member_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, user_id TEXT NOT NULL, participant_actor_id TEXT NOT NULL, role TEXT NOT NULL, invited_by TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(workspace_id, user_id), UNIQUE(workspace_id, participant_actor_id))",
        "CREATE TABLE workspace_agent_bindings (binding_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, agent_id TEXT NOT NULL, bot_uuid TEXT NOT NULL, participant_actor_id TEXT NOT NULL, display_name TEXT, description TEXT, config_json TEXT NOT NULL DEFAULT '{}', is_active INTEGER NOT NULL DEFAULT 1, hex_q INTEGER, hex_r INTEGER, theme_color TEXT, label TEXT, status TEXT NOT NULL DEFAULT 'idle', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(workspace_id, agent_id), UNIQUE(workspace_id, bot_uuid), UNIQUE(workspace_id, participant_actor_id), UNIQUE(workspace_id, hex_q, hex_r))",
        "CREATE TABLE workspace_topology_nodes (node_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, hex_q INTEGER, hex_r INTEGER)",
        "CREATE TABLE workspace_authorities (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, revision INTEGER NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE workspace_mutation_receipts (receipt_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, actor_id TEXT NOT NULL, contract_version TEXT NOT NULL, surface TEXT NOT NULL, action TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL, expected_revision INTEGER NOT NULL, committed_revision INTEGER, response_json TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, committed_at TEXT, UNIQUE(workspace_id, actor_id, idempotency_key))",
        "CREATE TABLE workspace_outbox (outbox_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, aggregate_type TEXT NOT NULL, aggregate_id TEXT NOT NULL, event_type TEXT NOT NULL, stream_name TEXT NOT NULL, event_sequence INTEGER NOT NULL, payload_json TEXT NOT NULL, metadata_json TEXT NOT NULL, correlation_id TEXT, idempotency_key TEXT NOT NULL, UNIQUE(workspace_id, idempotency_key), UNIQUE(workspace_id, stream_name, event_sequence))",
    ] {
        db.execute(DbStatement::new(ddl)).await?;
    }
    db.execute(DbStatement::new(
        "INSERT INTO project_principal_memberships (tenant_id, project_id, user_id, participant_actor_id, is_active) VALUES ('tenant-1', 'project-1', 'owner-1', 'owner-1', 1)",
    ))
    .await?;
    WorkspaceCreationService::new(&db, DbSqlFlavor::Sqlite)
        .create(&CreateWorkspaceInput {
            scope: CreateWorkspaceScopeInput {
                tenant_id: "tenant-1".to_string(),
                project_id: "project-1".to_string(),
                workspace_id: "workspace-1".to_string(),
                group_id: "group-workspace-1".to_string(),
            },
            owner: CreateWorkspaceOwnerInput {
                member_id: "member-1".to_string(),
                user_id: "owner-1".to_string(),
                is_superuser: false,
            },
            content: CreateWorkspaceContentInput {
                name: "Team Space".to_string(),
                description: Some("Shared workspace".to_string()),
                metadata: json!({"workspace_type": "general"}),
            },
            idempotency_key: "create-intent".to_string(),
        })
        .await?;
    Ok(db)
}

async fn scalar_i64(db: &dyn DbPlugin, sql: &str) -> Result<i64, Box<dyn Error>> {
    let rows = db.query(DbStatement::new(sql)).await?;
    Ok(rows
        .first()
        .ok_or("missing row")?
        .get_i64("value")?
        .ok_or("missing value")?)
}

async fn scalar_string(db: &dyn DbPlugin, sql: &str) -> Result<String, Box<dyn Error>> {
    let rows = db.query(DbStatement::new(sql)).await?;
    Ok(rows
        .first()
        .ok_or("missing row")?
        .get_string("value")?
        .ok_or("missing value")?)
}
