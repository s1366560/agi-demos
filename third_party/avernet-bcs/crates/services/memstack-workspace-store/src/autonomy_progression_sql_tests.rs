use super::*;

fn assert_postgres_parameters(statement: &DbStatement) {
    assert!(!statement.sql().contains('?'));
    for position in 1..=statement.params().len() {
        assert!(statement.sql().contains(&format!("${position}")));
    }
}

fn progression_claim() -> WorkspaceAutonomyProgressionClaim {
    WorkspaceAutonomyProgressionClaim {
        progression_id: "progression-1".to_string(),
        tick_id: "tick-1".to_string(),
        tenant_id: "tenant-1".to_string(),
        project_id: "project-1".to_string(),
        workspace_id: "workspace-1".to_string(),
        root_task_id: "root-1".to_string(),
        actor_id: "user-1".to_string(),
        judge_agent_id: "judge-1".to_string(),
        workspace_agent_binding_id: "binding-1".to_string(),
        task_title: "Continue the objective".to_string(),
        task_description: "Execute the Judge-selected next action".to_string(),
        attempt_count: 1,
        worker_id: "worker-1".to_string(),
        lease_expires_at_ms: 200,
        lease_generation: 1,
    }
}

#[test]
fn claim_uses_native_locking_and_returns_fencing_generation() {
    let postgres = claim_statement(DbSqlFlavor::Postgres, "worker-1", 100, 200, 10);
    assert!(postgres.sql().contains("FOR UPDATE SKIP LOCKED"));
    assert!(postgres.sql().contains("lease_generation"));
    assert_postgres_parameters(&postgres);

    let sqlite = claim_statement(DbSqlFlavor::Sqlite, "worker-1", 100, 200, 10);
    assert!(sqlite.sql().contains("rowid IN (SELECT rowid"));
    assert!(!sqlite.sql().contains("SKIP LOCKED"));
    assert_eq!(sqlite.sql().matches('?').count(), sqlite.params().len());
}

#[test]
fn completion_and_failure_are_fenced_by_generation() {
    let claim = progression_claim();
    for statement in [
        complete_statement(DbSqlFlavor::Postgres, &claim, "task-1", 300),
        fail_statement(
            DbSqlFlavor::Postgres,
            &claim,
            400,
            "structured_task_unavailable",
        ),
    ] {
        assert!(statement.sql().contains("lease_owner"));
        assert!(statement.sql().contains("lease_expires_at_ms"));
        assert!(statement.sql().contains("lease_generation"));
        assert_postgres_parameters(&statement);
    }
}

#[test]
fn exhausted_claims_are_dead_lettered_before_reclaim() {
    for flavor in [DbSqlFlavor::Postgres, DbSqlFlavor::Sqlite] {
        let statement = reap_exhausted_statement(flavor, 100);
        assert!(statement.sql().contains("attempt_count >= max_attempts"));
        assert!(statement.sql().contains("status = 'dead_letter'"));
    }
}
