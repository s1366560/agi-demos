//! Versioned SQLite schema for the Desktop Local Workspace extension.

use bcs_db_api::{
    DbError, DbPlugin, DbResult, DbStatement, DbTransactionStep, DbValue, db_get_column,
};

const DESKTOP_SCHEMA_NAME: &str = "memstack_workspace_extension";
const DESKTOP_SCHEMA_MIGRATIONS: &[DesktopSchemaMigration] = &[
    DesktopSchemaMigration {
        version: 1,
        checksum: "0769cf329066d77eb109511da70e23a84c8f7546646cab3ccb03f9885d952822",
        ddl: include_str!("desktop_workspace_schema.sql"),
    },
    DesktopSchemaMigration {
        version: 2,
        checksum: "1bccb0c64aedf17d7edb722f319ae5cbcdff508ec4bb20d33740f0f91300a10e",
        ddl: include_str!("desktop_workspace_schema_v2.sql"),
    },
    DesktopSchemaMigration {
        version: 3,
        checksum: "8fde1ee0543ce14bf24b9f987d3931f55828651239f685f1be6889029f94c86e",
        ddl: include_str!("desktop_workspace_schema_v3.sql"),
    },
    DesktopSchemaMigration {
        version: 4,
        checksum: "ef2364b6998ff4800419fae8d93a34d06b86e10d16bc1fab46028668adf0f52b",
        ddl: include_str!("desktop_workspace_schema_v4.sql"),
    },
    DesktopSchemaMigration {
        version: 5,
        checksum: "6ebd1076e6be079652dcefd875338e3dac11c2cb46b844f4073b76b4a5ecc615",
        ddl: include_str!("desktop_workspace_schema_v5.sql"),
    },
    DesktopSchemaMigration {
        version: 6,
        checksum: "548efccf48bdf5fd769f81abd6aefe9680bdc09d0da53a187a8dedae2cfc798f",
        ddl: include_str!("desktop_workspace_schema_v6.sql"),
    },
    DesktopSchemaMigration {
        version: 7,
        checksum: "2e86cc9a253e5fcc3b3013b454f08f5940e19be7f001bcbd98ad3282cd53231c",
        ddl: include_str!("desktop_workspace_schema_v7.sql"),
    },
];

struct DesktopSchemaMigration {
    version: i64,
    checksum: &'static str,
    ddl: &'static str,
}

/// Create and verify the formal Workspace extension schema in Desktop Local SQLite.
///
/// The checked-in DDL is generated from the Alembic-managed PostgreSQL schema.
/// Cloud startup never calls this function and therefore never executes DDL.
pub async fn run_desktop_workspace_schema_migrations(db: &dyn DbPlugin) -> DbResult<()> {
    db.execute(DbStatement::new(
        "CREATE TABLE IF NOT EXISTS workspace_sqlite_schema_migrations (\
         version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum TEXT NOT NULL, \
         applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
    ))
    .await?;
    ensure_supported_schema_ledger(db).await?;
    for migration in DESKTOP_SCHEMA_MIGRATIONS {
        apply_migration(db, migration).await?;
    }
    Ok(())
}

async fn ensure_supported_schema_ledger(db: &dyn DbPlugin) -> DbResult<()> {
    let (Some(first), Some(latest)) = (
        DESKTOP_SCHEMA_MIGRATIONS.first(),
        DESKTOP_SCHEMA_MIGRATIONS.last(),
    ) else {
        return Err(DbError::InvalidInput(
            "Desktop Workspace SQLite migration manifest is empty".to_string(),
        ));
    };
    let rows = db
        .query(DbStatement::with_params(
            "SELECT version, name FROM workspace_sqlite_schema_migrations \
             WHERE version < ? OR version > ? ORDER BY version ASC LIMIT 1",
            vec![DbValue::from(first.version), DbValue::from(latest.version)],
        ))
        .await?;
    let Some(row) = rows.first() else {
        return Ok(());
    };
    let version = db_get_column::<i64>(row, "version")?;
    let name = db_get_column::<String>(row, "name")?;
    Err(DbError::InvalidInput(format!(
        "Desktop Workspace SQLite migration version {version} ({name}) is not supported by this \
         binary; supported versions are {} through {}",
        first.version, latest.version
    )))
}

async fn apply_migration(db: &dyn DbPlugin, migration: &DesktopSchemaMigration) -> DbResult<()> {
    let rows = db
        .query(DbStatement::with_params(
            "SELECT name, checksum FROM workspace_sqlite_schema_migrations WHERE version = ?",
            vec![DbValue::from(migration.version)],
        ))
        .await?;
    if let Some(row) = rows.first() {
        let name = db_get_column::<String>(row, "name")?;
        let checksum = db_get_column::<String>(row, "checksum")?;
        if name != DESKTOP_SCHEMA_NAME || checksum != migration.checksum {
            return Err(DbError::InvalidInput(format!(
                "Desktop Workspace SQLite migration checksum mismatch for version {}: \
                 applied={checksum}, current={}",
                migration.version, migration.checksum
            )));
        }
        return Ok(());
    }

    let mut steps = split_ddl_statements(migration.ddl)
        .into_iter()
        .filter(|statement| {
            !statement.starts_with("CREATE TABLE IF NOT EXISTS workspace_sqlite_schema_migrations")
        })
        .map(|statement| DbTransactionStep::Execute(DbStatement::new(statement)))
        .collect::<Vec<_>>();
    steps.push(DbTransactionStep::Execute(DbStatement::with_params(
        "INSERT INTO workspace_sqlite_schema_migrations (version, name, checksum) VALUES (?, ?, ?)",
        vec![
            DbValue::from(migration.version),
            DbValue::from(DESKTOP_SCHEMA_NAME),
            DbValue::from(migration.checksum),
        ],
    )));
    db.transaction(steps).await?;
    Ok(())
}

fn split_ddl_statements(ddl: &str) -> Vec<String> {
    let mut statements = Vec::new();
    let mut pending = String::new();
    let mut in_trigger = false;
    for line in ddl.lines() {
        let trimmed = line.trim();
        if pending.trim().is_empty() && trimmed.to_ascii_uppercase().starts_with("CREATE TRIGGER") {
            in_trigger = true;
        }
        pending.push_str(line);
        pending.push('\n');
        if in_trigger {
            if trimmed.eq_ignore_ascii_case("END;") {
                let statement = pending.trim().trim_end_matches(';').trim();
                if !statement.is_empty() {
                    statements.push(statement.to_string());
                }
                pending.clear();
                in_trigger = false;
            }
            continue;
        }
        while let Some(separator) = pending.find(';') {
            let statement = pending[..separator].trim();
            if !statement.is_empty() {
                statements.push(statement.to_string());
            }
            pending.drain(..=separator);
        }
    }
    let statement = pending.trim();
    if !statement.is_empty() {
        statements.push(statement.to_string());
    }
    statements
}

#[cfg(test)]
mod tests {
    use std::error::Error;

    use bcs_db_local::LocalSqliteDbPlugin;
    use sha2::{Digest, Sha256};

    use super::*;

    #[test]
    fn desktop_schema_versions_are_contiguous_and_checksums_match_ddl_bytes()
    -> Result<(), Box<dyn Error>> {
        for (index, migration) in DESKTOP_SCHEMA_MIGRATIONS.iter().enumerate() {
            let expected_version = i64::try_from(index + 1)?;
            assert_eq!(migration.version, expected_version);

            let actual_checksum = hex::encode(Sha256::digest(migration.ddl.as_bytes()));
            assert_eq!(
                actual_checksum, migration.checksum,
                "Desktop Workspace SQLite migration {} checksum is stale",
                migration.version
            );
        }
        Ok(())
    }

    #[tokio::test]
    async fn version_five_backfills_and_reopens_task_dispatch_dead_letter_attention()
    -> Result<(), Box<dyn Error>> {
        let db = database_at_schema_version_four().await?;
        db.execute_batch(
            [
                "INSERT INTO workspace_profiles (workspace_id, tenant_id, project_id, group_id, \
                 name, created_by) VALUES ('workspace-1', 'tenant-1', 'project-1', 'group-1', \
                 'Workspace One', 'actor-1')",
                "INSERT INTO workspace_tasks (task_id, tenant_id, project_id, workspace_id, title, \
                 created_by, metadata_json) VALUES ('root-1', 'tenant-1', 'project-1', \
                 'workspace-1', 'Root task', 'actor-1', '{\"task_role\":\"goal_root\"}')",
                "INSERT INTO workspace_tasks (task_id, tenant_id, project_id, workspace_id, title, \
                 created_by, metadata_json) VALUES ('execution-1', 'tenant-1', 'project-1', \
                 'workspace-1', 'Dispatch task', 'actor-1', \
                 '{\"task_role\":\"execution_task\",\"root_goal_task_id\":\"root-1\"}')",
                "INSERT INTO workspace_tasks (task_id, tenant_id, project_id, workspace_id, title, \
                 created_by, metadata_json) VALUES ('execution-invalid', 'tenant-1', 'project-1', \
                 'workspace-1', 'Invalid dispatch task', 'actor-1', \
                 '{\"task_role\":\"execution_task\"}')",
                "INSERT INTO workspace_task_dispatch_outbox (dispatch_id, tenant_id, project_id, \
                 workspace_id, task_id, user_id, agent_id, workspace_agent_binding_id, bot_uuid, \
                 group_id, conversation_id, delivery_request_id, task_title, status, last_error, \
                 created_at_ms) VALUES ('dispatch-1', 'tenant-1', 'project-1', 'workspace-1', \
                 'execution-1', 'actor-1', 'agent-1', 'binding-1', 'bot-1', 'group-1', \
                 'conversation-1', 'delivery-1', 'Dispatch task', 'dead_letter', \
                 'initial dispatch failure', 123)",
                "INSERT INTO workspace_task_dispatch_outbox (dispatch_id, tenant_id, project_id, \
                 workspace_id, task_id, user_id, agent_id, workspace_agent_binding_id, bot_uuid, \
                 group_id, conversation_id, delivery_request_id, task_title, status, created_at_ms) \
                 VALUES ('dispatch-invalid', 'tenant-1', 'project-1', 'workspace-1', \
                 'execution-invalid', 'actor-1', 'agent-1', 'binding-1', 'bot-1', 'group-1', \
                 'conversation-2', 'delivery-2', 'Invalid dispatch task', 'pending', 124)",
            ]
            .into_iter()
            .map(DbStatement::new)
            .collect(),
        )
        .await?;

        apply_migration(&db, &DESKTOP_SCHEMA_MIGRATIONS[4]).await?;

        let backfilled = db
            .query(DbStatement::new(
                "SELECT attention_id, root_task_id, source_kind, source_id, reason, status, \
                 created_at_ms FROM workspace_autonomy_attentions \
                 WHERE source_kind = 'task_dispatch_dead_letter' AND source_id = 'dispatch-1'",
            ))
            .await?;
        assert_eq!(backfilled.len(), 1);
        assert_eq!(
            db_get_column::<String>(&backfilled[0], "attention_id")?,
            "task-dispatch:dispatch-1"
        );
        assert_eq!(
            db_get_column::<String>(&backfilled[0], "root_task_id")?,
            "root-1"
        );
        assert_eq!(
            db_get_column::<String>(&backfilled[0], "reason")?,
            "initial dispatch failure"
        );
        assert_eq!(db_get_column::<String>(&backfilled[0], "status")?, "open");
        assert_eq!(db_get_column::<i64>(&backfilled[0], "created_at_ms")?, 123);

        db.execute(DbStatement::new(
            "UPDATE workspace_autonomy_attentions SET status = 'resolved', resolved_at_ms = 200, \
             resolved_by_actor_id = 'actor-1' WHERE attention_id = 'task-dispatch:dispatch-1'",
        ))
        .await?;
        db.execute(DbStatement::new(
            "UPDATE workspace_task_dispatch_outbox SET status = 'pending' \
             WHERE dispatch_id = 'dispatch-1'",
        ))
        .await?;
        db.execute(DbStatement::new(
            "UPDATE workspace_task_dispatch_outbox SET status = 'dead_letter', \
             last_error = 'retry dispatch failure' WHERE dispatch_id = 'dispatch-1'",
        ))
        .await?;

        let reopened = db
            .query(DbStatement::new(
                "SELECT root_task_id, reason, status, resolved_at_ms, resolved_by_actor_id \
                 FROM workspace_autonomy_attentions \
                 WHERE attention_id = 'task-dispatch:dispatch-1'",
            ))
            .await?;
        assert_eq!(reopened.len(), 1);
        assert_eq!(
            db_get_column::<String>(&reopened[0], "root_task_id")?,
            "root-1"
        );
        assert_eq!(
            db_get_column::<String>(&reopened[0], "reason")?,
            "retry dispatch failure"
        );
        assert_eq!(db_get_column::<String>(&reopened[0], "status")?, "open");
        assert!(matches!(
            reopened[0].get("resolved_at_ms"),
            Some(DbValue::Null)
        ));
        assert!(matches!(
            reopened[0].get("resolved_by_actor_id"),
            Some(DbValue::Null)
        ));

        let invalid_transition = db
            .execute(DbStatement::new(
                "UPDATE workspace_task_dispatch_outbox SET status = 'dead_letter', \
                 last_error = 'invalid root metadata' WHERE dispatch_id = 'dispatch-invalid'",
            ))
            .await;
        assert!(
            invalid_transition.is_err(),
            "task dispatch without a valid root task must fail closed"
        );
        let invalid_dispatch = db
            .query(DbStatement::new(
                "SELECT status FROM workspace_task_dispatch_outbox \
                 WHERE dispatch_id = 'dispatch-invalid'",
            ))
            .await?;
        assert_eq!(
            db_get_column::<String>(&invalid_dispatch[0], "status")?,
            "pending"
        );
        Ok(())
    }

    #[tokio::test]
    async fn version_seven_backfills_only_autonomous_workspaces_without_a_goal_root()
    -> Result<(), Box<dyn Error>> {
        let db = database_at_schema_version_six().await?;
        db.execute_batch(
            [
                "INSERT INTO workspace_profiles (workspace_id, tenant_id, project_id, group_id, \
                 name, description, created_by, metadata_json) VALUES ('workspace-recover', \
                 'tenant-1', 'project-1', 'group-recover', 'Recover Root', 'Backfill the root', \
                 'creator-1', '{\"collaboration_mode\":\"autonomous\"}')",
                "INSERT INTO workspace_members (member_id, tenant_id, project_id, workspace_id, \
                 user_id, participant_actor_id, role) VALUES ('member-recover', 'tenant-1', \
                 'project-1', 'workspace-recover', 'owner-1', 'owner-1', 'owner')",
                "INSERT INTO workspace_profiles (workspace_id, tenant_id, project_id, group_id, \
                 name, created_by, metadata_json) VALUES ('workspace-rooted', 'tenant-1', \
                 'project-1', 'group-rooted', 'Already Rooted', 'owner-1', \
                 '{\"collaboration_mode\":\"autonomous\"}')",
                "INSERT INTO workspace_tasks (task_id, tenant_id, project_id, workspace_id, title, \
                 created_by, metadata_json) VALUES ('root-existing', 'tenant-1', 'project-1', \
                 'workspace-rooted', 'Existing Root', 'owner-1', \
                 '{\"task_role\":\"goal_root\",\"objective_id\":\"objective-existing\"}')",
                "INSERT INTO workspace_profiles (workspace_id, tenant_id, project_id, group_id, \
                 name, created_by, metadata_json) VALUES ('workspace-single', 'tenant-1', \
                 'project-1', 'group-single', 'Single Agent', 'owner-1', \
                 '{\"collaboration_mode\":\"single_agent\"}')",
                "INSERT INTO workspace_profiles (workspace_id, tenant_id, project_id, group_id, \
                 name, created_by, metadata_json) VALUES ('workspace-legacy', 'tenant-1', \
                 'project-1', 'group-legacy', 'Legacy Autonomous', 'legacy-creator', \
                 '{\"legacy_desktop\":{\"collaboration_mode\":\"autonomous\"}}')",
                "INSERT INTO workspace_profiles (workspace_id, tenant_id, project_id, group_id, \
                 name, created_by, metadata_json) VALUES ('workspace-zblank', 'tenant-1', \
                 'project-1', 'group-zblank', '   ', 'blank-creator', \
                 '{\"collaboration_mode\":\"autonomous\"}')",
            ]
            .into_iter()
            .map(DbStatement::new)
            .collect(),
        )
        .await?;

        apply_migration(&db, &DESKTOP_SCHEMA_MIGRATIONS[6]).await?;
        apply_migration(&db, &DESKTOP_SCHEMA_MIGRATIONS[6]).await?;

        let rows = db
            .query(DbStatement::new(
                "SELECT workspace_id, actor_id, objective_title, objective_description, status \
                 FROM workspace_autonomy_bootstrap_outbox ORDER BY workspace_id",
            ))
            .await?;
        assert_eq!(rows.len(), 3);
        assert_eq!(
            db_get_column::<String>(&rows[0], "workspace_id")?,
            "workspace-legacy"
        );
        assert_eq!(
            db_get_column::<String>(&rows[0], "actor_id")?,
            "legacy-creator"
        );
        assert_eq!(
            db_get_column::<String>(&rows[1], "workspace_id")?,
            "workspace-recover"
        );
        assert_eq!(db_get_column::<String>(&rows[1], "actor_id")?, "owner-1");
        assert_eq!(
            db_get_column::<String>(&rows[1], "objective_title")?,
            "Recover Root"
        );
        assert_eq!(
            db_get_column::<String>(&rows[1], "objective_description")?,
            "Backfill the root"
        );
        assert_eq!(db_get_column::<String>(&rows[1], "status")?, "pending");
        assert_eq!(
            db_get_column::<String>(&rows[2], "workspace_id")?,
            "workspace-zblank"
        );
        assert_eq!(
            db_get_column::<String>(&rows[2], "objective_title")?,
            "Autonomous workspace workspace-zblank"
        );
        Ok(())
    }

    #[tokio::test]
    async fn autonomy_schema_rejects_cross_scope_references_and_snapshot_rewrites()
    -> Result<(), Box<dyn Error>> {
        let db = database_at_schema_version_four().await?;
        db.execute_batch(
            [
                "INSERT INTO workspace_profiles (workspace_id, tenant_id, project_id, group_id, \
                 name, created_by) VALUES ('workspace-1', 'tenant-1', 'project-1', 'group-1', \
                 'Workspace One', 'actor-1')",
                "INSERT INTO workspace_profiles (workspace_id, tenant_id, project_id, group_id, \
                 name, created_by) VALUES ('workspace-2', 'tenant-2', 'project-2', 'group-2', \
                 'Workspace Two', 'actor-2')",
                "INSERT INTO workspace_agent_bindings (binding_id, tenant_id, project_id, \
                 workspace_id, agent_id, bot_uuid, participant_actor_id) VALUES ('binding-1', \
                 'tenant-1', 'project-1', 'workspace-1', 'agent-1', 'bot-1', 'agent:1')",
                "INSERT INTO workspace_agent_bindings (binding_id, tenant_id, project_id, \
                 workspace_id, agent_id, bot_uuid, participant_actor_id) VALUES ('binding-2', \
                 'tenant-2', 'project-2', 'workspace-2', 'agent-2', 'bot-2', 'agent:2')",
                "INSERT INTO workspace_tasks (task_id, tenant_id, project_id, workspace_id, title, \
                 created_by, metadata_json) VALUES ('root-1', 'tenant-1', 'project-1', \
                 'workspace-1', 'Root One', 'actor-1', '{\"task_role\":\"goal_root\"}')",
                "INSERT INTO workspace_tasks (task_id, tenant_id, project_id, workspace_id, title, \
                 created_by, metadata_json) VALUES ('root-2', 'tenant-2', 'project-2', \
                 'workspace-2', 'Root Two', 'actor-2', '{\"task_role\":\"goal_root\"}')",
                "INSERT INTO workspace_judge_audits (audit_id, tenant_id, project_id, workspace_id, \
                 judgment_type, agent_id, tool_name, input_json, output_json, rationale, latency_ms, \
                 status) VALUES ('audit-1', 'tenant-1', 'project-1', 'workspace-1', 'autonomy', \
                 'judge-1', 'judge', '{}', '{}', 'continue', 1, 'completed')",
                "INSERT INTO workspace_judge_audits (audit_id, tenant_id, project_id, workspace_id, \
                 judgment_type, agent_id, tool_name, input_json, output_json, rationale, latency_ms, \
                 status) VALUES ('audit-2', 'tenant-2', 'project-2', 'workspace-2', 'autonomy', \
                 'judge-2', 'judge', '{}', '{}', 'continue', 1, 'completed')",
                "INSERT INTO workspace_autonomy_ticks (tick_id, tenant_id, project_id, workspace_id, \
                 root_task_id, actor_id, verdict, reason, judge_audit_id) VALUES ('tick-1', \
                 'tenant-1', 'project-1', 'workspace-1', 'root-1', 'actor-1', 'continue', \
                 'triggered', 'audit-1')",
                "INSERT INTO workspace_autonomy_ticks (tick_id, tenant_id, project_id, workspace_id, \
                 root_task_id, actor_id, verdict, reason, judge_audit_id) VALUES ('tick-2', \
                 'tenant-2', 'project-2', 'workspace-2', 'root-2', 'actor-2', 'continue', \
                 'triggered', 'audit-2')",
            ]
            .into_iter()
            .map(DbStatement::new)
            .collect(),
        )
        .await?;

        let wrong_tick = db
            .execute(DbStatement::new(
                "INSERT INTO workspace_autonomy_progression_outbox (progression_id, tick_id, \
                 tenant_id, project_id, workspace_id, root_task_id, actor_id, judge_agent_id, \
                 workspace_agent_binding_id, task_title, task_description, created_at_ms) VALUES \
                 ('progression-wrong-tick', 'tick-2', 'tenant-1', 'project-1', 'workspace-1', \
                 'root-1', 'actor-1', 'judge-1', 'binding-1', 'Work', 'Advance', 1)",
            ))
            .await;
        assert!(
            wrong_tick.is_err(),
            "cross-scope tick reference must fail closed"
        );

        let wrong_binding = db
            .execute(DbStatement::new(
                "INSERT INTO workspace_autonomy_progression_outbox (progression_id, tick_id, \
                 tenant_id, project_id, workspace_id, root_task_id, actor_id, judge_agent_id, \
                 workspace_agent_binding_id, task_title, task_description, created_at_ms) VALUES \
                 ('progression-wrong-binding', 'tick-1', 'tenant-1', 'project-1', 'workspace-1', \
                 'root-1', 'actor-1', 'judge-1', 'binding-2', 'Work', 'Advance', 1)",
            ))
            .await;
        assert!(
            wrong_binding.is_err(),
            "cross-scope binding reference must fail closed"
        );

        db.execute(DbStatement::new(
            "INSERT INTO workspace_autonomy_progression_outbox (progression_id, tick_id, tenant_id, \
             project_id, workspace_id, root_task_id, actor_id, judge_agent_id, \
             workspace_agent_binding_id, task_title, task_description, created_at_ms) VALUES \
             ('progression-1', 'tick-1', 'tenant-1', 'project-1', 'workspace-1', 'root-1', \
             'actor-1', 'judge-1', 'binding-1', 'Work', 'Advance', 1)",
        ))
        .await?;
        let progression_rewrite = db
            .execute(DbStatement::new(
                "UPDATE workspace_autonomy_progression_outbox SET task_title = 'Rewritten' \
                 WHERE progression_id = 'progression-1'",
            ))
            .await;
        assert!(
            progression_rewrite.is_err(),
            "progression snapshot rewrite must fail closed"
        );

        apply_migration(&db, &DESKTOP_SCHEMA_MIGRATIONS[4]).await?;
        let wrong_audit = db
            .execute(DbStatement::new(
                "INSERT INTO workspace_autonomy_judgment_claims (claim_id, tenant_id, project_id, \
                 workspace_id, actor_id, idempotency_key, request_hash, expected_revision, \
                 lease_owner, lease_expires_at_ms, audit_id, created_at_ms, updated_at_ms) VALUES \
                 ('claim-wrong-audit', 'tenant-1', 'project-1', 'workspace-1', 'actor-1', \
                 'claim-key-wrong', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', \
                 0, 'worker-1', 100, 'audit-2', 1, 1)",
            ))
            .await;
        assert!(
            wrong_audit.is_err(),
            "cross-scope judgment audit reference must fail closed"
        );

        db.execute(DbStatement::new(
            "INSERT INTO workspace_autonomy_judgment_claims (claim_id, tenant_id, project_id, \
             workspace_id, actor_id, idempotency_key, request_hash, expected_revision, lease_owner, \
             lease_expires_at_ms, audit_id, created_at_ms, updated_at_ms) VALUES ('claim-1', \
             'tenant-1', 'project-1', 'workspace-1', 'actor-1', 'claim-key-1', \
             'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 0, 'worker-1', \
             100, 'audit-1', 1, 1)",
        ))
        .await?;
        let claim_rewrite = db
            .execute(DbStatement::new(
                "UPDATE workspace_autonomy_judgment_claims SET idempotency_key = 'rewritten' \
                 WHERE claim_id = 'claim-1'",
            ))
            .await;
        assert!(
            claim_rewrite.is_err(),
            "claim snapshot rewrite must fail closed"
        );

        db.execute(DbStatement::new(
            "INSERT INTO workspace_autonomy_bootstrap_outbox (bootstrap_id, tenant_id, project_id, \
             workspace_id, actor_id, objective_title, created_at_ms) VALUES ('bootstrap-1', \
             'tenant-1', 'project-1', 'workspace-1', 'actor-1', 'Bootstrap', 1)",
        ))
        .await?;
        let bootstrap_rewrite = db
            .execute(DbStatement::new(
                "UPDATE workspace_autonomy_bootstrap_outbox SET objective_title = 'Rewritten' \
                 WHERE bootstrap_id = 'bootstrap-1'",
            ))
            .await;
        assert!(
            bootstrap_rewrite.is_err(),
            "bootstrap snapshot rewrite must fail closed"
        );
        Ok(())
    }

    #[tokio::test]
    async fn version_five_rejects_backfill_without_valid_task_dispatch_root()
    -> Result<(), Box<dyn Error>> {
        let db = database_at_schema_version_four().await?;
        db.execute_batch(
            [
                "INSERT INTO workspace_profiles (workspace_id, tenant_id, project_id, group_id, \
                 name, created_by) VALUES ('workspace-1', 'tenant-1', 'project-1', 'group-1', \
                 'Workspace One', 'actor-1')",
                "INSERT INTO workspace_tasks (task_id, tenant_id, project_id, workspace_id, title, \
                 created_by, metadata_json) VALUES ('execution-invalid', 'tenant-1', 'project-1', \
                 'workspace-1', 'Invalid dispatch task', 'actor-1', \
                 '{\"task_role\":\"execution_task\"}')",
                "INSERT INTO workspace_task_dispatch_outbox (dispatch_id, tenant_id, project_id, \
                 workspace_id, task_id, user_id, agent_id, workspace_agent_binding_id, bot_uuid, \
                 group_id, conversation_id, delivery_request_id, task_title, status, last_error, \
                 created_at_ms) VALUES ('dispatch-invalid', 'tenant-1', 'project-1', 'workspace-1', \
                 'execution-invalid', 'actor-1', 'agent-1', 'binding-1', 'bot-1', 'group-1', \
                 'conversation-1', 'delivery-1', 'Invalid dispatch task', 'dead_letter', \
                 'invalid root metadata', 123)",
            ]
            .into_iter()
            .map(DbStatement::new)
            .collect(),
        )
        .await?;

        let migration = apply_migration(&db, &DESKTOP_SCHEMA_MIGRATIONS[4]).await;

        assert!(
            migration.is_err(),
            "v5 backfill must reject a task dispatch without a valid root task"
        );
        let ledger = db
            .query(DbStatement::new(
                "SELECT COUNT(*) AS count FROM workspace_sqlite_schema_migrations \
                 WHERE version = 5",
            ))
            .await?;
        assert_eq!(db_get_column::<i64>(&ledger[0], "count")?, 0);
        Ok(())
    }

    async fn database_at_schema_version_four() -> Result<LocalSqliteDbPlugin, Box<dyn Error>> {
        let db = LocalSqliteDbPlugin::new()?;
        db.execute(DbStatement::new("PRAGMA foreign_keys = ON"))
            .await?;
        bcs::migrations::run_sqlite_migrations(&db).await?;
        db.execute(DbStatement::new(
            "CREATE TABLE IF NOT EXISTS workspace_sqlite_schema_migrations (\
             version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum TEXT NOT NULL, \
             applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
        ))
        .await?;
        for migration in &DESKTOP_SCHEMA_MIGRATIONS[..4] {
            apply_migration(&db, migration).await?;
        }
        Ok(db)
    }

    async fn database_at_schema_version_six() -> Result<LocalSqliteDbPlugin, Box<dyn Error>> {
        let db = database_at_schema_version_four().await?;
        for migration in &DESKTOP_SCHEMA_MIGRATIONS[4..6] {
            apply_migration(&db, migration).await?;
        }
        Ok(db)
    }
}
