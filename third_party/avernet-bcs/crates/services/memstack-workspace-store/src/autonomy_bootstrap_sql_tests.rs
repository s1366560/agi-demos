use std::error::Error;

use bcs_db_api::{DbPlugin, DbStatement};
use bcs_db_local::LocalSqliteDbPlugin;

use super::*;

fn claim() -> WorkspaceAutonomyBootstrapClaim {
    WorkspaceAutonomyBootstrapClaim {
        bootstrap_id: "bootstrap-1".to_string(),
        tenant_id: "tenant-1".to_string(),
        project_id: "project-1".to_string(),
        workspace_id: "workspace-1".to_string(),
        actor_id: "owner-1".to_string(),
        objective_title: "Autonomous Workspace".to_string(),
        objective_description: Some("Advance the root objective".to_string()),
        attempt_count: 1,
        worker_id: "worker-1".to_string(),
        lease_expires_at_ms: 200,
        lease_generation: 1,
    }
}

#[test]
fn ensure_is_idempotent_and_skips_an_existing_goal_root() {
    let ensure = WorkspaceAutonomyBootstrapEnsure {
        tenant_id: "tenant-1",
        project_id: "project-1",
        workspace_id: "workspace-1",
        actor_id: "owner-1",
        objective_title: "Autonomous Workspace",
        objective_description: None,
        created_at_ms: 100,
    };
    for flavor in [DbSqlFlavor::Postgres, DbSqlFlavor::Sqlite] {
        let statement = ensure_statement(flavor, &ensure);
        assert!(statement.sql().contains("NOT EXISTS"));
        assert!(statement.sql().contains("goal_root"));
        assert!(statement.sql().contains("workspace_id"));
        match flavor {
            DbSqlFlavor::Postgres => {
                assert!(
                    statement
                        .sql()
                        .contains("ON CONFLICT (workspace_id) DO NOTHING")
                );
                assert!(!statement.sql().contains('?'));
            }
            DbSqlFlavor::Sqlite => {
                assert!(statement.sql().starts_with("INSERT OR IGNORE"));
                assert_eq!(
                    statement.sql().matches('?').count(),
                    statement.params().len()
                );
            }
            DbSqlFlavor::Mysql => unreachable!(),
        }
    }
}

#[tokio::test]
async fn completion_requires_scoped_objective_and_goal_root_identity() -> Result<(), Box<dyn Error>>
{
    let db = LocalSqliteDbPlugin::new()?;
    for ddl in [
        "CREATE TABLE workspace_autonomy_bootstrap_outbox (bootstrap_id TEXT PRIMARY KEY, \
         tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, \
         status TEXT NOT NULL, lease_owner TEXT, lease_expires_at_ms INTEGER, \
         lease_generation INTEGER NOT NULL, objective_id TEXT, root_task_id TEXT, \
         last_error TEXT, completed_at_ms INTEGER)",
        "CREATE TABLE workspace_objectives (objective_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, \
         project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, objective_type TEXT NOT NULL, \
         parent_objective_id TEXT)",
        "CREATE TABLE workspace_tasks (task_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, \
         project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, metadata_json TEXT NOT NULL)",
        "INSERT INTO workspace_autonomy_bootstrap_outbox (bootstrap_id, tenant_id, project_id, \
         workspace_id, status, lease_owner, lease_expires_at_ms, lease_generation) VALUES \
         ('bootstrap-1', 'tenant-1', 'project-1', 'workspace-1', 'processing', 'worker-1', 200, 1)",
    ] {
        db.execute(DbStatement::new(ddl)).await?;
    }
    let store = WorkspaceAutonomyBootstrapStore::new(&db, DbSqlFlavor::Sqlite);
    let claim = claim();

    let missing = store.complete(&claim, "objective-1", "root-1", 300).await;
    assert!(matches!(
        missing,
        Err(WorkspaceAutonomyBootstrapStoreError::LeaseLost)
    ));

    db.execute(DbStatement::new(
        "INSERT INTO workspace_objectives (objective_id, tenant_id, project_id, workspace_id, \
         objective_type) VALUES ('objective-1', 'tenant-2', 'project-1', 'workspace-1', \
         'objective')",
    ))
    .await?;
    db.execute(DbStatement::new(
        "INSERT INTO workspace_tasks (task_id, tenant_id, project_id, workspace_id, metadata_json) \
         VALUES ('root-1', 'tenant-2', 'project-1', 'workspace-1', \
         '{\"task_role\":\"goal_root\",\"objective_id\":\"objective-1\"}')",
    ))
    .await?;
    let cross_scope = store.complete(&claim, "objective-1", "root-1", 300).await;
    assert!(matches!(
        cross_scope,
        Err(WorkspaceAutonomyBootstrapStoreError::LeaseLost)
    ));

    db.execute(DbStatement::new(
        "UPDATE workspace_objectives SET tenant_id = 'tenant-1' WHERE objective_id = 'objective-1'",
    ))
    .await?;
    db.execute(DbStatement::new(
        "UPDATE workspace_tasks SET tenant_id = 'tenant-1', metadata_json = \
         '{\"task_role\":\"goal_root\",\"objective_id\":\"other-objective\"}' \
         WHERE task_id = 'root-1'",
    ))
    .await?;
    let wrong_identity = store.complete(&claim, "objective-1", "root-1", 300).await;
    assert!(matches!(
        wrong_identity,
        Err(WorkspaceAutonomyBootstrapStoreError::LeaseLost)
    ));

    db.execute(DbStatement::new(
        "UPDATE workspace_tasks SET metadata_json = \
         '{\"task_role\":\"goal_root\",\"objective_id\":\"objective-1\"}' \
         WHERE task_id = 'root-1'",
    ))
    .await?;
    store.complete(&claim, "objective-1", "root-1", 300).await?;
    let rows = db
        .query(DbStatement::new(
            "SELECT status, objective_id, root_task_id FROM \
             workspace_autonomy_bootstrap_outbox WHERE bootstrap_id = 'bootstrap-1'",
        ))
        .await?;
    assert_eq!(rows[0].get_string("status")?.as_deref(), Some("completed"));
    assert_eq!(
        rows[0].get_string("objective_id")?.as_deref(),
        Some("objective-1")
    );
    assert_eq!(
        rows[0].get_string("root_task_id")?.as_deref(),
        Some("root-1")
    );
    Ok(())
}
