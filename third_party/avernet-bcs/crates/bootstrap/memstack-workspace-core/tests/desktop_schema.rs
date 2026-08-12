use std::error::Error;

use bcs_db_api::{DbPlugin, DbStatement, DbValue, db_get_column};
use bcs_db_local::LocalSqliteDbPlugin;
use memstack_workspace_core::desktop_schema::run_desktop_workspace_schema_migrations;

const VERSION_ONE_SCHEMA: &str = include_str!("../src/desktop_workspace_schema.sql");
const VERSION_ONE_CHECKSUM: &str =
    "0769cf329066d77eb109511da70e23a84c8f7546646cab3ccb03f9885d952822";

const REQUIRED_TABLES: &[&str] = &[
    "workspace_profiles",
    "workspace_members",
    "workspace_principal_identities",
    "workspace_agent_policies",
    "workspace_agent_bindings",
    "workspace_tasks",
    "workspace_task_attempts",
    "workspace_task_receipts",
    "workspace_blackboard_posts",
    "workspace_blackboard_replies",
    "workspace_files",
    "workspace_topology_nodes",
    "workspace_topology_edges",
    "workspace_objectives",
    "workspace_genes",
    "workspace_authorities",
    "workspace_revision_credentials",
    "workspace_mutation_receipts",
    "workspace_plans",
    "workspace_plan_nodes",
    "workspace_plan_blackboard_entries",
    "workspace_plan_events",
    "workspace_outbox",
    "workspace_pipeline_contracts",
    "workspace_pipeline_runs",
    "workspace_pipeline_stage_runs",
    "workspace_deployments",
    "workspace_agent_runtime_correlations",
    "workspace_execution_terminals",
    "workspace_migration_ledger",
    "workspace_judge_audits",
    "workspace_message_delivery_outbox",
    "workspace_task_dispatch_outbox",
    "workspace_message_correlations",
    "workspace_contexts",
    "workspace_context_events",
    "workspace_context_outbox",
    "workspace_file_operations",
    "workspace_file_compensations",
    "workspace_objective_task_projections",
    "workspace_autonomy_ticks",
    "project_principal_memberships",
];

#[tokio::test]
async fn fresh_desktop_database_creates_the_complete_workspace_extension_schema()
-> Result<(), Box<dyn Error>> {
    let db = LocalSqliteDbPlugin::new()?;

    bcs::migrations::run_sqlite_migrations(&db).await?;

    run_desktop_workspace_schema_migrations(&db).await?;

    for table in REQUIRED_TABLES {
        let rows = db
            .query(DbStatement::with_params(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
                vec![DbValue::from(*table)],
            ))
            .await?;
        assert_eq!(rows.len(), 1, "missing {table}");
    }
    Ok(())
}

#[tokio::test]
async fn desktop_workspace_schema_is_idempotent_and_checksum_guarded() -> Result<(), Box<dyn Error>>
{
    let db = LocalSqliteDbPlugin::new()?;
    bcs::migrations::run_sqlite_migrations(&db).await?;
    run_desktop_workspace_schema_migrations(&db).await?;
    run_desktop_workspace_schema_migrations(&db).await?;

    let rows = db
        .query(DbStatement::new(
            "SELECT COUNT(*) AS count FROM workspace_sqlite_schema_migrations",
        ))
        .await?;
    assert_eq!(db_get_column::<i64>(&rows[0], "count")?, 2);

    db.execute(DbStatement::new(
        "UPDATE workspace_sqlite_schema_migrations SET checksum = 'tampered' WHERE version = 1",
    ))
    .await?;
    let error = match run_desktop_workspace_schema_migrations(&db).await {
        Err(error) => error,
        Ok(()) => return Err("checksum mismatch did not fail closed".into()),
    };
    assert!(error.to_string().contains("checksum mismatch"));
    Ok(())
}

#[tokio::test]
async fn version_one_database_upgrades_messages_without_losing_base_bcs_rows()
-> Result<(), Box<dyn Error>> {
    let db = LocalSqliteDbPlugin::new()?;
    bcs::migrations::run_sqlite_migrations(&db).await?;
    apply_version_one_schema(&db).await?;
    db.execute(DbStatement::new(
        "INSERT INTO bcs_messages (message_id, group_id, session_id, session_seq, env, \
         sender_id, sender_type, message_type, content, status, created_at, run_id) VALUES \
         ('base-message', 'base-group', 'base-session', 1, 'prod', 'base-sender', 'human', \
          'text', 'base content', 'normal', 1, '')",
    ))
    .await?;

    run_desktop_workspace_schema_migrations(&db).await?;

    let columns = db
        .query(DbStatement::new("PRAGMA table_info(bcs_messages)"))
        .await?;
    let column_names = columns
        .iter()
        .map(|row| db_get_column::<String>(row, "name"))
        .collect::<Result<Vec<_>, _>>()?;
    for expected in [
        "workspace_id",
        "mentions_json",
        "parent_message_id",
        "metadata_json",
        "source_hash",
    ] {
        assert!(
            column_names.iter().any(|name| name == expected),
            "missing {expected}"
        );
    }
    let rows = db
        .query(DbStatement::new(
            "SELECT message_id, workspace_id, mentions_json, parent_message_id, metadata_json, \
             source_hash \
             FROM bcs_messages WHERE message_id = 'base-message'",
        ))
        .await?;
    assert_eq!(rows.len(), 1);
    assert!(matches!(rows[0].get("workspace_id"), Some(DbValue::Null)));
    assert_eq!(db_get_column::<String>(&rows[0], "mentions_json")?, "[]");
    assert!(matches!(
        rows[0].get("parent_message_id"),
        Some(DbValue::Null)
    ));
    assert_eq!(db_get_column::<String>(&rows[0], "metadata_json")?, "{}");
    assert!(matches!(rows[0].get("source_hash"), Some(DbValue::Null)));
    Ok(())
}

async fn apply_version_one_schema(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    let statements = VERSION_ONE_SCHEMA
        .split(';')
        .map(str::trim)
        .filter(|statement| !statement.is_empty())
        .map(DbStatement::new)
        .collect::<Vec<_>>();
    db.execute_batch(statements).await?;
    db.execute(DbStatement::with_params(
        "INSERT INTO workspace_sqlite_schema_migrations (version, name, checksum) \
         VALUES (?, ?, ?)",
        vec![
            DbValue::from(1_i64),
            DbValue::from("memstack_workspace_extension"),
            DbValue::from(VERSION_ONE_CHECKSUM),
        ],
    ))
    .await?;
    Ok(())
}
