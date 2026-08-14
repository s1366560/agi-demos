use std::error::Error;

use bcs_db_api::{DbPlugin, DbStatement, DbValue};
use bcs_db_local::LocalSqliteDbPlugin;
use memstack_workspace_core::desktop_schema::run_desktop_workspace_schema_migrations;

#[derive(Clone, Copy)]
struct ProgressionRow {
    progression_id: &'static str,
    tick_id: &'static str,
    tenant_id: &'static str,
    project_id: &'static str,
    workspace_id: &'static str,
    root_task_id: &'static str,
    status: &'static str,
    attempt_count: i64,
    max_attempts: i64,
    next_attempt_at_ms: i64,
    lease_owner: Option<&'static str>,
    lease_expires_at_ms: Option<i64>,
    lease_generation: i64,
    execution_task_id: Option<&'static str>,
    created_at_ms: i64,
    completed_at_ms: Option<i64>,
}

impl ProgressionRow {
    fn valid_pending() -> Self {
        Self {
            progression_id: "progression-1",
            tick_id: "tick-1",
            tenant_id: "tenant-1",
            project_id: "project-1",
            workspace_id: "workspace-1",
            root_task_id: "root-1",
            status: "pending",
            attempt_count: 0,
            max_attempts: 8,
            next_attempt_at_ms: 0,
            lease_owner: None,
            lease_expires_at_ms: None,
            lease_generation: 0,
            execution_task_id: None,
            created_at_ms: 1,
            completed_at_ms: None,
        }
    }

    fn statement(self) -> DbStatement {
        DbStatement::with_params(
            "INSERT INTO workspace_autonomy_progression_outbox (\
             progression_id, tick_id, tenant_id, project_id, workspace_id, root_task_id, \
             actor_id, judge_agent_id, workspace_agent_binding_id, task_title, task_description, \
             status, attempt_count, max_attempts, next_attempt_at_ms, lease_owner, \
             lease_expires_at_ms, lease_generation, execution_task_id, last_error, created_at_ms, \
             completed_at_ms) VALUES (?, ?, ?, ?, ?, ?, 'actor-1', 'judge-1', 'binding-1', \
             'Continue the goal', 'Create the next execution task', ?, ?, ?, ?, ?, ?, ?, ?, \
             NULL, ?, ?)",
            vec![
                DbValue::from(self.progression_id),
                DbValue::from(self.tick_id),
                DbValue::from(self.tenant_id),
                DbValue::from(self.project_id),
                DbValue::from(self.workspace_id),
                DbValue::from(self.root_task_id),
                DbValue::from(self.status),
                DbValue::from(self.attempt_count),
                DbValue::from(self.max_attempts),
                DbValue::from(self.next_attempt_at_ms),
                DbValue::from(self.lease_owner),
                optional_i64(self.lease_expires_at_ms),
                DbValue::from(self.lease_generation),
                DbValue::from(self.execution_task_id),
                DbValue::from(self.created_at_ms),
                optional_i64(self.completed_at_ms),
            ],
        )
    }
}

#[tokio::test]
async fn progression_outbox_accepts_valid_lifecycle_shapes() -> Result<(), Box<dyn Error>> {
    let db = seeded_progression_database().await?;

    let pending = ProgressionRow::valid_pending();
    db.execute(pending.statement()).await?;

    let processing = ProgressionRow {
        progression_id: "progression-2",
        tick_id: "tick-2",
        status: "processing",
        attempt_count: 1,
        lease_owner: Some("worker-1"),
        lease_expires_at_ms: Some(2),
        lease_generation: 1,
        ..ProgressionRow::valid_pending()
    };
    db.execute(processing.statement()).await?;

    let completed = ProgressionRow {
        progression_id: "progression-3",
        tick_id: "tick-3",
        status: "completed",
        attempt_count: 1,
        execution_task_id: Some("execution-1"),
        completed_at_ms: Some(3),
        ..ProgressionRow::valid_pending()
    };
    db.execute(completed.statement()).await?;

    Ok(())
}

#[tokio::test]
async fn progression_outbox_rejects_cross_workspace_root_task() -> Result<(), Box<dyn Error>> {
    let db = seeded_progression_database().await?;
    let row = ProgressionRow {
        root_task_id: "root-other",
        ..ProgressionRow::valid_pending()
    };

    assert_rejected(&db, row, "cross-workspace root task").await
}

#[tokio::test]
async fn progression_outbox_rejects_cross_workspace_execution_task() -> Result<(), Box<dyn Error>> {
    let db = seeded_progression_database().await?;
    let row = ProgressionRow {
        status: "completed",
        execution_task_id: Some("execution-other"),
        completed_at_ms: Some(2),
        ..ProgressionRow::valid_pending()
    };

    assert_rejected(&db, row, "cross-workspace execution task").await
}

#[tokio::test]
async fn progression_outbox_rejects_attempt_count_above_maximum() -> Result<(), Box<dyn Error>> {
    let db = seeded_progression_database().await?;
    let row = ProgressionRow {
        attempt_count: 9,
        max_attempts: 8,
        ..ProgressionRow::valid_pending()
    };

    assert_rejected(&db, row, "attempt count above maximum").await
}

#[tokio::test]
async fn progression_outbox_rejects_invalid_lease_shapes() -> Result<(), Box<dyn Error>> {
    let db = seeded_progression_database().await?;
    let processing_without_lease = ProgressionRow {
        status: "processing",
        ..ProgressionRow::valid_pending()
    };
    assert_rejected(
        &db,
        processing_without_lease,
        "processing row without lease",
    )
    .await?;

    let pending_with_lease = ProgressionRow {
        lease_owner: Some("worker-1"),
        lease_expires_at_ms: Some(2),
        ..ProgressionRow::valid_pending()
    };
    assert_rejected(&db, pending_with_lease, "non-processing row with lease").await
}

#[tokio::test]
async fn progression_outbox_rejects_invalid_completion_shapes() -> Result<(), Box<dyn Error>> {
    let db = seeded_progression_database().await?;
    let completed_without_execution = ProgressionRow {
        status: "completed",
        ..ProgressionRow::valid_pending()
    };
    assert_rejected(
        &db,
        completed_without_execution,
        "completed row without execution task and timestamp",
    )
    .await?;

    let pending_with_completion = ProgressionRow {
        completed_at_ms: Some(2),
        ..ProgressionRow::valid_pending()
    };
    assert_rejected(
        &db,
        pending_with_completion,
        "non-completed row with completion timestamp",
    )
    .await
}

#[tokio::test]
async fn progression_outbox_rejects_negative_timestamps_and_lease_generation()
-> Result<(), Box<dyn Error>> {
    let db = seeded_progression_database().await?;
    let invalid_rows = [
        (
            ProgressionRow {
                next_attempt_at_ms: -1,
                ..ProgressionRow::valid_pending()
            },
            "negative next-attempt timestamp",
        ),
        (
            ProgressionRow {
                created_at_ms: -1,
                ..ProgressionRow::valid_pending()
            },
            "negative creation timestamp",
        ),
        (
            ProgressionRow {
                status: "processing",
                lease_owner: Some("worker-1"),
                lease_expires_at_ms: Some(-1),
                ..ProgressionRow::valid_pending()
            },
            "negative lease-expiry timestamp",
        ),
        (
            ProgressionRow {
                status: "completed",
                execution_task_id: Some("execution-1"),
                completed_at_ms: Some(-1),
                ..ProgressionRow::valid_pending()
            },
            "negative completion timestamp",
        ),
        (
            ProgressionRow {
                lease_generation: -1,
                ..ProgressionRow::valid_pending()
            },
            "negative lease generation",
        ),
    ];

    for (row, invariant) in invalid_rows {
        assert_rejected(&db, row, invariant).await?;
    }
    Ok(())
}

#[tokio::test]
async fn progression_outbox_rejects_unknown_status() -> Result<(), Box<dyn Error>> {
    let db = seeded_progression_database().await?;
    let row = ProgressionRow {
        status: "paused",
        ..ProgressionRow::valid_pending()
    };

    assert_rejected(&db, row, "unknown status").await
}

async fn seeded_progression_database() -> Result<LocalSqliteDbPlugin, Box<dyn Error>> {
    let db = LocalSqliteDbPlugin::new()?;
    db.execute(DbStatement::new("PRAGMA foreign_keys = ON"))
        .await?;
    bcs::migrations::run_sqlite_migrations(&db).await?;
    run_desktop_workspace_schema_migrations(&db).await?;

    db.execute_batch(
        [
            "INSERT INTO workspace_profiles (workspace_id, tenant_id, project_id, group_id, \
             name, created_by) VALUES ('workspace-1', 'tenant-1', 'project-1', 'group-1', \
             'Workspace One', 'actor-1')",
            "INSERT INTO workspace_profiles (workspace_id, tenant_id, project_id, group_id, \
             name, created_by) VALUES ('workspace-2', 'tenant-1', 'project-1', 'group-2', \
             'Workspace Two', 'actor-1')",
            "INSERT INTO workspace_agent_bindings (binding_id, tenant_id, project_id, \
             workspace_id, agent_id, bot_uuid, participant_actor_id) VALUES ('binding-1', \
             'tenant-1', 'project-1', 'workspace-1', 'judge-1', 'bot-1', 'judge-actor-1')",
            "INSERT INTO workspace_tasks (task_id, tenant_id, project_id, workspace_id, title, \
             created_by) VALUES ('root-1', 'tenant-1', 'project-1', 'workspace-1', 'Root', \
             'actor-1')",
            "INSERT INTO workspace_tasks (task_id, tenant_id, project_id, workspace_id, title, \
             created_by) VALUES ('execution-1', 'tenant-1', 'project-1', 'workspace-1', \
             'Execution', 'actor-1')",
            "INSERT INTO workspace_tasks (task_id, tenant_id, project_id, workspace_id, title, \
             created_by) VALUES ('root-other', 'tenant-1', 'project-1', 'workspace-2', \
             'Other Root', 'actor-1')",
            "INSERT INTO workspace_tasks (task_id, tenant_id, project_id, workspace_id, title, \
             created_by) VALUES ('execution-other', 'tenant-1', 'project-1', 'workspace-2', \
             'Other Execution', 'actor-1')",
            "INSERT INTO workspace_autonomy_ticks (tick_id, tenant_id, project_id, workspace_id, \
             root_task_id, actor_id, verdict, reason) VALUES ('tick-1', 'tenant-1', 'project-1', \
             'workspace-1', 'root-1', 'actor-1', 'continue', 'triggered')",
            "INSERT INTO workspace_autonomy_ticks (tick_id, tenant_id, project_id, workspace_id, \
             root_task_id, actor_id, verdict, reason) VALUES ('tick-2', 'tenant-1', 'project-1', \
             'workspace-1', 'root-1', 'actor-1', 'continue', 'triggered')",
            "INSERT INTO workspace_autonomy_ticks (tick_id, tenant_id, project_id, workspace_id, \
             root_task_id, actor_id, verdict, reason) VALUES ('tick-3', 'tenant-1', 'project-1', \
             'workspace-1', 'root-1', 'actor-1', 'continue', 'triggered')",
        ]
        .into_iter()
        .map(DbStatement::new)
        .collect(),
    )
    .await?;

    Ok(db)
}

async fn assert_rejected(
    db: &dyn DbPlugin,
    row: ProgressionRow,
    invariant: &str,
) -> Result<(), Box<dyn Error>> {
    let result = db.execute(row.statement()).await;
    assert!(result.is_err(), "schema accepted {invariant}");
    Ok(())
}

fn optional_i64(value: Option<i64>) -> DbValue {
    value.map(DbValue::from).unwrap_or(DbValue::Null)
}
