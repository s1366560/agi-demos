use super::*;

fn assert_postgres_parameters(statement: &DbStatement) {
    assert!(!statement.sql().contains('?'));
    for position in 1..=statement.params().len() {
        assert!(statement.sql().contains(&format!("${position}")));
    }
}

fn dispatch_write() -> WorkspaceTaskDispatchWrite {
    WorkspaceTaskDispatchWrite {
        dispatch_id: "task-dispatch-1".to_string(),
        scope: WorkspaceTaskScope {
            tenant_id: "tenant-1".to_string(),
            project_id: "project-1".to_string(),
            workspace_id: "workspace-1".to_string(),
        },
        task_id: "task-1".to_string(),
        attempt_id: Some("attempt-1".to_string()),
        plan_id: Some("plan-1".to_string()),
        plan_node_id: Some("node-1".to_string()),
        user_id: "user-1".to_string(),
        agent_id: "agent-1".to_string(),
        workspace_agent_binding_id: "binding-1".to_string(),
        conversation_id: "conversation-1".to_string(),
        delivery_request_id: "delivery-1".to_string(),
        created_at_ms: 1_000,
    }
}

fn dispatch_claim() -> WorkspaceTaskDispatchClaim {
    WorkspaceTaskDispatchClaim {
        dispatch_id: "task-dispatch-1".to_string(),
        tenant_id: "tenant-1".to_string(),
        project_id: "project-1".to_string(),
        workspace_id: "workspace-1".to_string(),
        task_id: "task-1".to_string(),
        attempt_id: Some("attempt-1".to_string()),
        plan_id: Some("plan-1".to_string()),
        plan_node_id: Some("node-1".to_string()),
        user_id: "user-1".to_string(),
        agent_id: "agent-1".to_string(),
        workspace_agent_binding_id: "binding-1".to_string(),
        bot_uuid: "bot-1".to_string(),
        group_id: "group-1".to_string(),
        conversation_id: "conversation-1".to_string(),
        delivery_request_id: "delivery-1".to_string(),
        task_title: "Execute work".to_string(),
        task_description: Some("Preserve the durable contract".to_string()),
        task_status: "todo".to_string(),
        attempt_count: 1,
        worker_id: "worker-1".to_string(),
        lease_expires_at_ms: 200,
        lease_generation: 1,
    }
}

#[test]
fn dispatch_insert_snapshots_scoped_task_binding_and_profile() {
    for flavor in [DbSqlFlavor::Postgres, DbSqlFlavor::Sqlite] {
        let statement = dispatch_write().insert_statement(flavor);
        assert!(statement.sql().contains("JOIN workspace_profiles"));
        assert!(statement.sql().contains("JOIN workspace_agent_bindings"));
        assert!(statement.sql().contains("task.created_by"));
        assert!(statement.sql().contains("binding.is_active = TRUE"));
        match flavor {
            DbSqlFlavor::Postgres => assert_postgres_parameters(&statement),
            DbSqlFlavor::Sqlite => {
                assert_eq!(
                    statement.sql().matches('?').count(),
                    statement.params().len()
                );
            }
            DbSqlFlavor::Mysql => unreachable!(),
        }
    }
}

#[test]
fn claim_uses_native_locking_and_returns_fencing_generation() {
    let postgres = claim_statement(DbSqlFlavor::Postgres, "worker-1", 100, 200, 10);
    assert!(postgres.sql().contains("FOR UPDATE SKIP LOCKED"));
    assert!(postgres.sql().contains("lease_generation"));
    assert!(postgres.sql().contains("task_status"));
    assert_postgres_parameters(&postgres);

    let sqlite = claim_statement(DbSqlFlavor::Sqlite, "worker-1", 100, 200, 10);
    assert!(sqlite.sql().contains("rowid IN (SELECT rowid"));
    assert!(!sqlite.sql().contains("SKIP LOCKED"));
    assert_eq!(sqlite.sql().matches('?').count(), sqlite.params().len());
}

#[test]
fn correlation_is_parameterized_and_includes_provider_scope() {
    let claim = dispatch_claim();
    let postgres = correlation_insert(DbSqlFlavor::Postgres, &claim);
    assert!(postgres.sql().contains("user_id"));
    assert!(postgres.sql().contains("bcs_group_id"));
    assert!(postgres.sql().contains("provider_bot_ref"));
    assert_postgres_parameters(&postgres);

    let sqlite = correlation_insert(DbSqlFlavor::Sqlite, &claim);
    assert_eq!(sqlite.sql().matches('?').count(), sqlite.params().len());
}

#[test]
fn completion_and_failure_are_fenced_by_generation() {
    let claim = dispatch_claim();
    for statement in [
        complete_statement(DbSqlFlavor::Postgres, &claim, 300),
        fail_statement(DbSqlFlavor::Postgres, &claim, 400, "provider_unavailable"),
    ] {
        assert!(statement.sql().contains("lease_owner"));
        assert!(statement.sql().contains("lease_expires_at_ms"));
        assert!(statement.sql().contains("lease_generation"));
        assert_postgres_parameters(&statement);
    }

    for flavor in [DbSqlFlavor::Postgres, DbSqlFlavor::Sqlite] {
        let correlation = correlation_running_statement(flavor, &claim, 300);
        for required in [
            "correlation_id",
            "tenant_id",
            "project_id",
            "workspace_id",
            "task_id",
            "attempt_id",
            "delivery_request_id",
            "provider_run_id",
            "provider_id",
            "provider_bot_ref",
            "dispatch.lease_generation",
        ] {
            assert!(correlation.sql().contains(required));
        }
        assert!(
            correlation
                .sql()
                .contains("status = 'pending' THEN 'running'")
        );
        match flavor {
            DbSqlFlavor::Postgres => assert_postgres_parameters(&correlation),
            DbSqlFlavor::Sqlite => {
                assert_eq!(
                    correlation.sql().matches('?').count(),
                    correlation.params().len()
                );
            }
            DbSqlFlavor::Mysql => unreachable!(),
        }
    }
}
