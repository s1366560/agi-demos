use super::*;

fn assert_postgres_parameters(statement: &DbStatement) {
    assert!(!statement.sql().contains('?'));
    for position in 1..=statement.params().len() {
        assert!(statement.sql().contains(&format!("${position}")));
    }
}

#[test]
fn postgres_claim_uses_skip_locked_and_native_parameters() {
    let statement = claim_statement(DbSqlFlavor::Postgres, "worker-1", 100, 200, 10);

    assert!(statement.sql().contains("FOR UPDATE SKIP LOCKED"));
    assert!(statement.sql().contains("RETURNING tenant_id"));
    assert!(statement.sql().contains("bcs_message_id"));
    assert_postgres_parameters(&statement);
}

#[test]
fn sqlite_claim_uses_rowid_and_native_parameters() {
    let statement = claim_statement(DbSqlFlavor::Sqlite, "worker-1", 100, 200, 10);

    assert!(statement.sql().contains("rowid IN (SELECT rowid"));
    assert!(!statement.sql().contains("SKIP LOCKED"));
    assert_eq!(
        statement.sql().matches('?').count(),
        statement.params().len()
    );
}

#[test]
fn exhausted_reaper_is_parameterized_for_both_dialects() {
    let postgres = reap_exhausted_statement(DbSqlFlavor::Postgres, 100);
    assert!(postgres.sql().contains("status = 'dead_letter'"));
    assert_postgres_parameters(&postgres);

    let sqlite = reap_exhausted_statement(DbSqlFlavor::Sqlite, 100);
    assert_eq!(sqlite.sql().matches('?').count(), sqlite.params().len());
}

#[test]
fn runtime_envelope_query_scopes_message_and_correlation() {
    let postgres = delivery_message_envelope_select(
        DbSqlFlavor::Postgres,
        "tenant-1",
        "project-1",
        "workspace-1",
        "message-1",
        "group-1",
    );

    assert!(postgres.sql().contains("correlation.tenant_id"));
    assert!(postgres.sql().contains("correlation.project_id"));
    assert!(
        postgres
            .sql()
            .contains("correlation.bcs_session_id = message.session_id")
    );
    assert!(postgres.sql().contains("message.workspace_id"));
    assert!(postgres.sql().contains("message.group_id"));
    assert!(postgres.sql().contains("message.session_id"));
    assert!(postgres.sql().contains("correlation.correlation_id"));
    assert_postgres_parameters(&postgres);
}
