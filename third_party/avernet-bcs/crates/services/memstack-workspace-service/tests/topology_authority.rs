use std::error::Error;

use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement};
use bcs_db_local::LocalSqliteDbPlugin;
use memstack_workspace_service::{
    PublicCreateTopologyEdgeInput, PublicCreateTopologyNodeInput, PublicUpdateTopologyNodeFields,
    PublicWorkspaceTopologyContext, PublicWorkspaceTopologyService,
};
use serde_json::json;

#[tokio::test]
async fn topology_nodes_edges_replay_and_coordinate_sync_are_atomic() -> Result<(), Box<dyn Error>>
{
    let db = seeded_topology_db().await?;
    let service = PublicWorkspaceTopologyService::new(&db, DbSqlFlavor::Sqlite);
    let source_input = create_node_input("source-create", 0, "Source", 1, 0);

    let source = service
        .create_node(&source_input)
        .await
        .map_err(|error| std::io::Error::other(format!("create source: {error:?}")))?;
    let replayed = service
        .create_node(&source_input)
        .await
        .map_err(|error| std::io::Error::other(format!("replay source: {error:?}")))?;
    assert!(!source.replayed);
    assert!(replayed.replayed);
    assert_eq!(source.value, replayed.value);

    let target = service
        .create_node(&create_node_input("target-create", 1, "Target", 2, -1))
        .await
        .map_err(|error| std::io::Error::other(format!("create target: {error:?}")))?;
    let edge = service
        .create_edge(&PublicCreateTopologyEdgeInput {
            context: topology_context("edge-create", Some(2)),
            source_node_id: source.value.id.clone(),
            target_node_id: target.value.id.clone(),
            label: Some("depends".to_string()),
            direction: None,
            auto_created: false,
            data: json!({"weight": 1}),
        })
        .await
        .map_err(|error| std::io::Error::other(format!("create edge: {error:?}")))?;
    assert_eq!(edge.value.direction, None);
    assert_eq!(edge.value.source_hex_q, Some(1));
    assert_eq!(edge.value.target_hex_r, Some(-1));

    let updated = service
        .update_node(
            &topology_context("source-update", Some(3)),
            source.value.id.as_str(),
            &PublicUpdateTopologyNodeFields {
                hex_q: Some(3),
                hex_r: Some(-1),
                data: Some(json!({"moved": true})),
                ..PublicUpdateTopologyNodeFields::default()
            },
        )
        .await
        .map_err(|error| std::io::Error::other(format!("update source: {error:?}")))?;
    assert_eq!(updated.value.hex_q, Some(3));
    let stored_edge = service
        .get_edge(&topology_context("read", None), edge.value.id.as_str())
        .await?;
    assert_eq!(stored_edge.source_hex_q, Some(3));
    assert_eq!(stored_edge.source_hex_r, Some(-1));

    assert_eq!(table_count(&db, "workspace_topology_nodes").await?, 2);
    assert_eq!(table_count(&db, "workspace_topology_edges").await?, 1);
    assert_eq!(table_count(&db, "workspace_mutation_receipts").await?, 4);
    assert_eq!(table_count(&db, "workspace_outbox").await?, 4);
    assert_eq!(authority_revision(&db).await?, 4);
    Ok(())
}

#[tokio::test]
async fn topology_permissions_geometry_and_agent_hex_conflicts_preserve_scope()
-> Result<(), Box<dyn Error>> {
    let db = seeded_topology_db().await?;
    let service = PublicWorkspaceTopologyService::new(&db, DbSqlFlavor::Sqlite);
    let occupied = service
        .create_node(&create_node_input("occupied", 0, "Occupied", 4, -1))
        .await;
    assert!(occupied.is_err());
    assert_eq!(table_count(&db, "workspace_topology_nodes").await?, 0);
    assert_eq!(table_count(&db, "workspace_mutation_receipts").await?, 0);
    assert_eq!(table_count(&db, "workspace_outbox").await?, 0);
    assert_eq!(authority_revision(&db).await?, 0);

    let viewer_context = PublicWorkspaceTopologyContext {
        user_id: "viewer-1".to_string(),
        ..topology_context("viewer-create", Some(0))
    };
    let viewer_input = PublicCreateTopologyNodeInput {
        context: viewer_context.clone(),
        ..create_node_input("ignored", 0, "Viewer", 5, -1)
    };
    assert!(service.create_node(&viewer_input).await.is_err());
    assert!(
        service
            .list_nodes(&viewer_context, 1000, 0)
            .await?
            .is_empty()
    );

    let reserved = service
        .create_node(&create_node_input("reserved", 0, "Reserved", 0, 0))
        .await;
    assert!(reserved.is_err());
    let partial_hex = PublicCreateTopologyNodeInput {
        hex_r: None,
        ..create_node_input("partial", 0, "Partial", 1, 0)
    };
    assert!(service.create_node(&partial_hex).await.is_err());
    Ok(())
}

fn create_node_input(
    idempotency_key: &str,
    expected_revision: u64,
    title: &str,
    hex_q: i64,
    hex_r: i64,
) -> PublicCreateTopologyNodeInput {
    PublicCreateTopologyNodeInput {
        context: topology_context(idempotency_key, Some(expected_revision)),
        node_type: "corridor".to_string(),
        ref_id: None,
        title: title.to_string(),
        position_x: 10.0,
        position_y: 20.0,
        hex_q: Some(hex_q),
        hex_r: Some(hex_r),
        status: "active".to_string(),
        tags: json!(["contract"]),
        data: json!({}),
    }
}

fn topology_context(
    idempotency_key: &str,
    expected_revision: Option<u64>,
) -> PublicWorkspaceTopologyContext {
    PublicWorkspaceTopologyContext {
        tenant_id: "tenant-1".to_string(),
        project_id: "project-1".to_string(),
        workspace_id: "workspace-1".to_string(),
        user_id: "user-1".to_string(),
        expected_revision,
        idempotency_key: (idempotency_key != "read").then(|| idempotency_key.to_string()),
    }
}

async fn seeded_topology_db() -> Result<LocalSqliteDbPlugin, Box<dyn Error>> {
    let db = LocalSqliteDbPlugin::new()?;
    for statement in [
        "CREATE TABLE workspace_profiles (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, deleted_at TEXT)",
        "CREATE TABLE workspace_members (tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, user_id TEXT NOT NULL, role TEXT NOT NULL)",
        "CREATE TABLE workspace_agent_bindings (binding_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, hex_q INTEGER, hex_r INTEGER)",
        "CREATE TABLE workspace_authorities (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, revision INTEGER NOT NULL, updated_at TEXT NOT NULL)",
        "CREATE TABLE workspace_mutation_receipts (receipt_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, actor_id TEXT NOT NULL, contract_version TEXT NOT NULL, surface TEXT NOT NULL, action TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL, expected_revision INTEGER NOT NULL, committed_revision INTEGER, response_json TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, committed_at TEXT, UNIQUE(workspace_id, actor_id, idempotency_key))",
        "CREATE TABLE workspace_outbox (outbox_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, aggregate_type TEXT NOT NULL, aggregate_id TEXT NOT NULL, event_type TEXT NOT NULL, stream_name TEXT NOT NULL, event_sequence INTEGER NOT NULL, payload_json TEXT NOT NULL, metadata_json TEXT NOT NULL, correlation_id TEXT, idempotency_key TEXT NOT NULL, UNIQUE(workspace_id, idempotency_key), UNIQUE(workspace_id, stream_name, event_sequence))",
        "CREATE TABLE workspace_topology_nodes (node_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, node_type TEXT NOT NULL, ref_id TEXT, title TEXT NOT NULL, position_x REAL NOT NULL, position_y REAL NOT NULL, hex_q INTEGER, hex_r INTEGER, status TEXT NOT NULL, tags_json TEXT NOT NULL, data_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT, UNIQUE(workspace_id, hex_q, hex_r))",
        "CREATE TABLE workspace_topology_edges (edge_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, source_node_id TEXT NOT NULL, target_node_id TEXT NOT NULL, edge_type TEXT NOT NULL, label TEXT, source_hex_q INTEGER, source_hex_r INTEGER, target_hex_q INTEGER, target_hex_r INTEGER, direction TEXT, auto_created INTEGER NOT NULL, data_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT, UNIQUE(workspace_id, source_node_id, target_node_id, edge_type), FOREIGN KEY(source_node_id) REFERENCES workspace_topology_nodes(node_id) ON DELETE CASCADE, FOREIGN KEY(target_node_id) REFERENCES workspace_topology_nodes(node_id) ON DELETE CASCADE)",
        "INSERT INTO workspace_profiles VALUES ('workspace-1', 'tenant-1', 'project-1', NULL)",
        "INSERT INTO workspace_members VALUES ('tenant-1', 'project-1', 'workspace-1', 'user-1', 'owner')",
        "INSERT INTO workspace_members VALUES ('tenant-1', 'project-1', 'workspace-1', 'viewer-1', 'viewer')",
        "INSERT INTO workspace_agent_bindings VALUES ('binding-1', 'tenant-1', 'project-1', 'workspace-1', 4, -1)",
        "INSERT INTO workspace_authorities VALUES ('workspace-1', 'tenant-1', 'project-1', 0, CURRENT_TIMESTAMP)",
    ] {
        db.execute(DbStatement::new(statement)).await?;
    }
    Ok(db)
}

async fn table_count(db: &dyn DbPlugin, table: &str) -> Result<i64, Box<dyn Error>> {
    let sql = match table {
        "workspace_topology_nodes" => "SELECT COUNT(*) AS value FROM workspace_topology_nodes",
        "workspace_topology_edges" => "SELECT COUNT(*) AS value FROM workspace_topology_edges",
        "workspace_mutation_receipts" => {
            "SELECT COUNT(*) AS value FROM workspace_mutation_receipts"
        }
        "workspace_outbox" => "SELECT COUNT(*) AS value FROM workspace_outbox",
        _ => return Err("unsupported table".into()),
    };
    Ok(db
        .query(DbStatement::new(sql))
        .await?
        .first()
        .ok_or("missing count")?
        .get_i64("value")?
        .ok_or("missing count value")?)
}

async fn authority_revision(db: &dyn DbPlugin) -> Result<i64, Box<dyn Error>> {
    Ok(db
        .query(DbStatement::new(
            "SELECT revision AS value FROM workspace_authorities WHERE workspace_id = 'workspace-1'",
        ))
        .await?
        .first()
        .ok_or("missing authority")?
        .get_i64("value")?
        .ok_or("missing revision")?)
}
