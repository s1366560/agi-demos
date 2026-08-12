use std::sync::Arc;

use bcs_db_api::DbPlugin;
use bcs_db_local::LocalSqliteDbPlugin;

use super::*;

const NOW: &str = "2026-08-11T00:00:02.000Z";
const LEASE_ONE: &str = "2026-08-11T00:00:32.000Z";
const LEASE_TWO: &str = "2026-08-11T00:01:02.000Z";

async fn seeded_db() -> Result<Arc<LocalSqliteDbPlugin>, Box<dyn std::error::Error>> {
    let db = Arc::new(LocalSqliteDbPlugin::new()?);
    for statement in [
        "CREATE TABLE workspace_profiles (tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, group_id TEXT NOT NULL, PRIMARY KEY(tenant_id, project_id, workspace_id))",
        "CREATE TABLE workspace_plan_nodes (tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, plan_id TEXT NOT NULL, node_id TEXT NOT NULL, workspace_task_id TEXT, current_attempt_id TEXT, assignee_agent_id TEXT, PRIMARY KEY(plan_id, node_id))",
        "CREATE TABLE workspace_outbox (outbox_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, aggregate_type TEXT NOT NULL, aggregate_id TEXT NOT NULL, event_type TEXT NOT NULL, stream_name TEXT NOT NULL, event_sequence INTEGER NOT NULL, payload_json TEXT NOT NULL, metadata_json TEXT NOT NULL, correlation_id TEXT, idempotency_key TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', attempt_count INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 10, lease_owner TEXT, lease_expires_at TEXT, last_error TEXT, next_attempt_at TEXT, dispatched_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)",
        "CREATE TABLE workspace_agent_runtime_correlations (correlation_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, user_id TEXT, task_id TEXT, attempt_id TEXT, plan_id TEXT, plan_node_id TEXT, conversation_id TEXT NOT NULL, bcs_group_id TEXT, delivery_request_id TEXT UNIQUE, provider_run_id TEXT UNIQUE, provider_id TEXT, provider_bot_ref TEXT, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)",
        "INSERT INTO workspace_profiles (tenant_id, project_id, workspace_id, group_id) VALUES ('tenant-1', 'project-1', 'workspace-1', 'group-1')",
        "INSERT INTO workspace_plan_nodes (tenant_id, project_id, workspace_id, plan_id, node_id, workspace_task_id, current_attempt_id, assignee_agent_id) VALUES ('tenant-1', 'project-1', 'workspace-1', 'plan-1', 'node-1', 'task-1', 'attempt-1', 'agent-1')",
        "INSERT INTO workspace_outbox (outbox_id, tenant_id, project_id, workspace_id, aggregate_type, aggregate_id, event_type, stream_name, event_sequence, payload_json, metadata_json, idempotency_key, status, attempt_count, max_attempts, created_at, updated_at) VALUES ('plan-outbox-1', 'tenant-1', 'project-1', 'workspace-1', 'workspace_plan', 'plan-1', 'workspace_pipeline_run_requested', 'workspace.events', 0, '{\"workspace_id\":\"workspace-1\",\"plan_id\":\"plan-1\",\"node_id\":\"node-1\",\"actor_id\":\"user-1\"}', '{}', 'plan-key-1', 'pending', 0, 2, '2026-08-11T00:00:00.000Z', '2026-08-11T00:00:00.000Z')",
        "INSERT INTO workspace_outbox (outbox_id, tenant_id, project_id, workspace_id, aggregate_type, aggregate_id, event_type, stream_name, event_sequence, payload_json, metadata_json, idempotency_key, status, attempt_count, max_attempts, created_at, updated_at) VALUES ('generic-outbox-1', 'tenant-1', 'project-1', 'workspace-1', 'workspace_task', 'task-1', 'workspace_task_updated', 'workspace.events', 1, '{}', '{}', 'generic-key-1', 'pending', 0, 10, '2026-08-11T00:00:01.000Z', '2026-08-11T00:00:01.000Z')",
    ] {
        db.execute(DbStatement::new(statement)).await?;
    }
    Ok(db)
}

fn completion(run_id: &str) -> WorkspacePlanDeliveryCompletion {
    WorkspacePlanDeliveryCompletion {
        correlation_id: "correlation-1".to_string(),
        conversation_id: "conversation-1".to_string(),
        provider_id: "memstack-agent-runtime".to_string(),
        provider_bot_ref: "agent-1".to_string(),
        provider_run_id: run_id.to_string(),
        accepted_at: NOW.to_string(),
    }
}

#[tokio::test]
async fn claim_is_atomic_and_limited_to_plan_runtime_events()
-> Result<(), Box<dyn std::error::Error>> {
    let db = seeded_db().await?;
    let store = WorkspacePlanDeliveryStore::new(db.as_ref(), DbSqlFlavor::Sqlite);

    let claims = store
        .claim_deliveries("worker-1", NOW, LEASE_ONE, 10)
        .await?;

    assert_eq!(claims.len(), 1);
    let claim = &claims[0];
    assert_eq!(claim.event_type, "workspace_pipeline_run_requested");
    assert_eq!(claim.plan_node_id.as_deref(), Some("node-1"));
    assert_eq!(claim.task_id.as_deref(), Some("task-1"));
    assert_eq!(claim.attempt_id.as_deref(), Some("attempt-1"));
    assert_eq!(claim.agent_id.as_deref(), Some("agent-1"));
    assert_eq!(claim.group_id, "group-1");
    assert_eq!(claim.attempt_count, 1);
    let rows = db
        .query(DbStatement::new(
            "SELECT status, lease_owner FROM workspace_outbox WHERE outbox_id = 'generic-outbox-1'",
        ))
        .await?;
    assert_eq!(rows[0].get_string("status")?.as_deref(), Some("pending"));
    assert_eq!(rows[0].get_string("lease_owner")?, None);
    Ok(())
}

#[tokio::test]
async fn expired_lease_is_reclaimed_and_stale_fence_cannot_complete()
-> Result<(), Box<dyn std::error::Error>> {
    let db = seeded_db().await?;
    let store = WorkspacePlanDeliveryStore::new(db.as_ref(), DbSqlFlavor::Sqlite);
    let first = store
        .claim_deliveries("worker-1", NOW, LEASE_ONE, 1)
        .await?
        .remove(0);
    let second = store
        .claim_deliveries("worker-2", LEASE_ONE, LEASE_TWO, 1)
        .await?
        .remove(0);

    assert_eq!(second.attempt_count, 2);
    assert!(matches!(
        store.complete_delivery(&first, &completion("run-1")).await,
        Err(WorkspacePlanDeliveryStoreError::LeaseLost)
    ));
    let rows = db
        .query(DbStatement::new(
            "SELECT status, lease_owner, lease_expires_at FROM workspace_outbox WHERE outbox_id = 'plan-outbox-1'",
        ))
        .await?;
    assert_eq!(
        rows[0].get_string("status")?.as_deref(),
        Some("plan_dispatching")
    );
    assert_eq!(
        rows[0].get_string("lease_owner")?.as_deref(),
        Some("worker-2")
    );
    assert_eq!(
        rows[0].get_string("lease_expires_at")?.as_deref(),
        Some(LEASE_TWO)
    );
    Ok(())
}

#[tokio::test]
async fn accepted_correlation_is_persisted_before_runtime_handoff_and_completion_is_one_shot()
-> Result<(), Box<dyn std::error::Error>> {
    let db = seeded_db().await?;
    let store = WorkspacePlanDeliveryStore::new(db.as_ref(), DbSqlFlavor::Sqlite);
    let claim = store
        .claim_deliveries("worker-1", NOW, LEASE_ONE, 1)
        .await?
        .remove(0);

    store
        .complete_delivery(&claim, &completion("run-1"))
        .await?;

    let rows = db
        .query(DbStatement::new(
            "SELECT status, lease_owner, correlation_id, json_extract(metadata_json, '$.plan_runtime_dispatch.provider_run_id') AS provider_run_id FROM workspace_outbox WHERE outbox_id = 'plan-outbox-1'",
        ))
        .await?;
    assert_eq!(
        rows[0].get_string("status")?.as_deref(),
        Some("runtime_dispatched")
    );
    assert_eq!(rows[0].get_string("lease_owner")?, None);
    assert_eq!(
        rows[0].get_string("correlation_id")?.as_deref(),
        Some("correlation-1")
    );
    assert_eq!(
        rows[0].get_string("provider_run_id")?.as_deref(),
        Some("run-1")
    );
    let correlations = db
        .query(DbStatement::new(
            "SELECT correlation_id, task_id, attempt_id, plan_node_id, provider_run_id, status FROM workspace_agent_runtime_correlations",
        ))
        .await?;
    assert_eq!(correlations.len(), 1);
    assert_eq!(
        correlations[0].get_string("task_id")?.as_deref(),
        Some("task-1")
    );
    assert_eq!(
        correlations[0].get_string("attempt_id")?.as_deref(),
        Some("attempt-1")
    );
    assert_eq!(
        correlations[0].get_string("plan_node_id")?.as_deref(),
        Some("node-1")
    );
    assert_eq!(
        correlations[0].get_string("status")?.as_deref(),
        Some("running")
    );
    assert!(matches!(
        store.complete_delivery(&claim, &completion("run-1")).await,
        Err(WorkspacePlanDeliveryStoreError::LeaseLost)
    ));
    assert_eq!(
        db.query(DbStatement::new(
            "SELECT correlation_id FROM workspace_agent_runtime_correlations"
        ))
        .await?
        .len(),
        1
    );
    Ok(())
}

#[tokio::test]
async fn failed_attempt_retries_then_dead_letters_at_maximum()
-> Result<(), Box<dyn std::error::Error>> {
    let db = seeded_db().await?;
    let store = WorkspacePlanDeliveryStore::new(db.as_ref(), DbSqlFlavor::Sqlite);
    let first = store
        .claim_deliveries("worker-1", NOW, LEASE_ONE, 1)
        .await?
        .remove(0);

    let first_failure = store
        .fail_delivery(
            &first,
            NOW,
            "2026-08-11T00:00:03.000Z",
            "workspace_plan_provider_rejected",
        )
        .await?;
    assert_eq!(first_failure.attempt_count, 1);
    assert!(!first_failure.dead_lettered);

    let second = store
        .claim_deliveries("worker-2", "2026-08-11T00:00:03.000Z", LEASE_TWO, 1)
        .await?
        .remove(0);
    let second_failure = store
        .fail_delivery(
            &second,
            "2026-08-11T00:00:03.000Z",
            "2026-08-11T00:00:05.000Z",
            "workspace_plan_provider_rejected",
        )
        .await?;
    assert_eq!(second_failure.attempt_count, 2);
    assert!(second_failure.dead_lettered);
    assert!(
        store
            .claim_deliveries(
                "worker-3",
                "2026-08-11T00:00:06.000Z",
                "2026-08-11T00:00:36.000Z",
                1,
            )
            .await?
            .is_empty()
    );
    let rows = db
        .query(DbStatement::new(
            "SELECT status, lease_owner, next_attempt_at, last_error FROM workspace_outbox WHERE outbox_id = 'plan-outbox-1'",
        ))
        .await?;
    assert_eq!(
        rows[0].get_string("status")?.as_deref(),
        Some("dead_letter")
    );
    assert_eq!(rows[0].get_string("lease_owner")?, None);
    assert_eq!(rows[0].get_string("next_attempt_at")?, None);
    assert_eq!(
        rows[0].get_string("last_error")?.as_deref(),
        Some("workspace_plan_provider_rejected")
    );
    Ok(())
}
