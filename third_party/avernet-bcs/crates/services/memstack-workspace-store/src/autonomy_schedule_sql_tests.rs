use super::*;

fn assert_postgres_parameters(statement: &DbStatement) {
    assert!(!statement.sql().contains('?'));
    for position in 1..=statement.params().len() {
        assert!(statement.sql().contains(&format!("${position}")));
    }
}

#[test]
fn schedule_scan_is_structural_and_dialect_aware() {
    let postgres = schedule_statement(DbSqlFlavor::Postgres, "2026-08-14T00:00:00Z", 25);
    assert!(postgres.sql().contains("->> 'collaboration_mode'"));
    assert!(postgres.sql().contains("->> 'task_role'"));
    assert_postgres_parameters(&postgres);

    let sqlite = schedule_statement(DbSqlFlavor::Sqlite, "2026-08-14T00:00:00Z", 25);
    assert!(sqlite.sql().contains("json_extract"));
    assert_eq!(sqlite.sql().matches('?').count(), sqlite.params().len());
}

#[test]
fn schedule_scan_requires_binding_and_excludes_in_flight_work() {
    let statement = schedule_statement(DbSqlFlavor::Sqlite, "2026-08-14T00:00:00Z", 25);
    assert!(statement.sql().contains("workspace_agent_bindings"));
    assert!(
        statement
            .sql()
            .contains("workspace_autonomy_progression_outbox")
    );
    assert!(statement.sql().contains("'execution_task'"));
    assert!(statement.sql().contains("workspace_autonomy_ticks"));
    assert!(statement.sql().contains("'owner', 'admin', 'editor'"));
}
