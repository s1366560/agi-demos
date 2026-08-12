use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::Duration;

use anyhow::Result;
use async_trait::async_trait;
use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement};
use bcs_db_local::LocalSqliteDbPlugin;
use memstack_workspace_core::outbox::{
    WorkspaceEventPublisher, WorkspaceOutboxConfig, WorkspaceOutboxDispatcher, WorkspaceOutboxEvent,
};
use memstack_workspace_core::plan_delivery_worker::{
    WorkspacePlanDeliveryWorker, WorkspacePlanDeliveryWorkerConfig,
};
use memstack_workspace_service_api::{
    WorkspacePlanDispatchPort, WorkspacePlanDispatchPortError, WorkspacePlanDispatchReceipt,
    WorkspacePlanDispatchRequest,
};
use tokio::sync::Notify;

struct BlockingPlanDispatcher {
    claimed: Notify,
    release: Notify,
}

#[async_trait]
impl WorkspacePlanDispatchPort for BlockingPlanDispatcher {
    async fn dispatch(
        &self,
        request: &WorkspacePlanDispatchRequest,
    ) -> Result<WorkspacePlanDispatchReceipt, WorkspacePlanDispatchPortError> {
        self.claimed.notify_one();
        self.release.notified().await;
        WorkspacePlanDispatchReceipt::new(
            "memstack-agent-runtime".to_string(),
            "agent-1".to_string(),
            format!("provider-run:{}", request.outbox_id()),
        )
        .map_err(|_| WorkspacePlanDispatchPortError::Unavailable)
    }
}

struct CountingPublisher {
    published: Arc<AtomicUsize>,
}

#[async_trait]
impl WorkspaceEventPublisher for CountingPublisher {
    async fn publish(&self, _event: &WorkspaceOutboxEvent) -> Result<String> {
        self.published.fetch_add(1, Ordering::SeqCst);
        Ok("1700000000000-1".to_string())
    }
}

#[tokio::test]
async fn plan_and_publication_workers_never_own_the_same_outbox_lease() -> Result<()> {
    let db = seeded_db().await?;
    let plan_dispatcher = Arc::new(BlockingPlanDispatcher {
        claimed: Notify::new(),
        release: Notify::new(),
    });
    let plan_worker = Arc::new(WorkspacePlanDeliveryWorker::new(
        db.clone(),
        DbSqlFlavor::Sqlite,
        plan_dispatcher.clone(),
        WorkspacePlanDeliveryWorkerConfig {
            worker_id: "plan-worker".to_string(),
            batch_size: 1,
            lease_duration: Duration::from_secs(30),
            poll_interval: Duration::from_millis(10),
            retry_base: Duration::from_secs(1),
            retry_max: Duration::from_secs(8),
        },
    )?);
    let published = Arc::new(AtomicUsize::new(0));
    let outbox_worker = WorkspaceOutboxDispatcher::new_with_sql_flavor(
        db.clone(),
        CountingPublisher {
            published: published.clone(),
        },
        WorkspaceOutboxConfig {
            lease_owner: "publication-worker".to_string(),
            batch_size: 1,
            ..WorkspaceOutboxConfig::default()
        },
        DbSqlFlavor::Sqlite,
    )?;

    let running_plan_worker = plan_worker.clone();
    let plan_task = tokio::spawn(async move { running_plan_worker.dispatch_once().await });
    plan_dispatcher.claimed.notified().await;

    let while_plan_owned = outbox_worker.dispatch_once().await?;

    assert_eq!(while_plan_owned.claimed, 0);
    assert_eq!(published.load(Ordering::SeqCst), 0);
    assert_outbox_state(db.as_ref(), "plan_dispatching", 1, 0).await?;

    plan_dispatcher.release.notify_one();
    let plan_outcome = plan_task.await??;
    assert_eq!(plan_outcome.completed, 1);
    assert_outbox_state(db.as_ref(), "runtime_dispatched", 1, 0).await?;

    let after_runtime_handoff = outbox_worker.dispatch_once().await?;

    assert_eq!(after_runtime_handoff.claimed, 1);
    assert_eq!(after_runtime_handoff.dispatched, 1);
    assert_eq!(published.load(Ordering::SeqCst), 1);
    assert_outbox_state(db.as_ref(), "dispatched", 1, 1).await?;
    Ok(())
}

async fn assert_outbox_state(
    db: &dyn DbPlugin,
    expected_status: &str,
    expected_plan_attempts: i64,
    expected_publication_attempts: i64,
) -> Result<()> {
    let rows = db
        .query(DbStatement::new(
            "SELECT status, attempt_count, publication_attempt_count FROM workspace_outbox WHERE outbox_id = 'plan-outbox-1'",
        ))
        .await?;
    let row = &rows[0];
    assert_eq!(row.get_string("status")?.as_deref(), Some(expected_status));
    assert_eq!(row.get_i64("attempt_count")?, Some(expected_plan_attempts));
    assert_eq!(
        row.get_i64("publication_attempt_count")?,
        Some(expected_publication_attempts)
    );
    Ok(())
}

async fn seeded_db() -> Result<Arc<LocalSqliteDbPlugin>> {
    let db = Arc::new(LocalSqliteDbPlugin::new()?);
    for statement in [
        "CREATE TABLE workspace_profiles (tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, group_id TEXT NOT NULL, PRIMARY KEY(tenant_id, project_id, workspace_id))",
        "CREATE TABLE workspace_plan_nodes (tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, plan_id TEXT NOT NULL, node_id TEXT NOT NULL, workspace_task_id TEXT, current_attempt_id TEXT, assignee_agent_id TEXT, PRIMARY KEY(plan_id, node_id))",
        "CREATE TABLE workspace_outbox (outbox_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, aggregate_type TEXT NOT NULL, aggregate_id TEXT NOT NULL, event_type TEXT NOT NULL, stream_name TEXT NOT NULL, event_sequence INTEGER NOT NULL, payload_json TEXT NOT NULL, metadata_json TEXT NOT NULL, correlation_id TEXT, idempotency_key TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', attempt_count INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 10, publication_attempt_count INTEGER NOT NULL DEFAULT 0, publication_max_attempts INTEGER NOT NULL DEFAULT 10, lease_owner TEXT, lease_expires_at TEXT, last_error TEXT, next_attempt_at TEXT, dispatched_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)",
        "CREATE TABLE workspace_context_outbox (outbox_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, event_type TEXT NOT NULL, stream_name TEXT NOT NULL, event_sequence INTEGER NOT NULL, payload_json TEXT NOT NULL, metadata_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', attempt_count INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 10, lease_owner TEXT, lease_expires_at TEXT, last_error TEXT, next_attempt_at TEXT, dispatched_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)",
        "CREATE TABLE workspace_agent_runtime_correlations (correlation_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, user_id TEXT, task_id TEXT, attempt_id TEXT, plan_id TEXT, plan_node_id TEXT, conversation_id TEXT NOT NULL, bcs_group_id TEXT, delivery_request_id TEXT UNIQUE, provider_run_id TEXT UNIQUE, provider_id TEXT, provider_bot_ref TEXT, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)",
        "INSERT INTO workspace_profiles (tenant_id, project_id, workspace_id, group_id) VALUES ('tenant-1', 'project-1', 'workspace-1', 'group-1')",
        "INSERT INTO workspace_plan_nodes (tenant_id, project_id, workspace_id, plan_id, node_id, workspace_task_id, current_attempt_id, assignee_agent_id) VALUES ('tenant-1', 'project-1', 'workspace-1', 'plan-1', 'node-1', 'task-1', 'attempt-1', 'agent-1')",
        "INSERT INTO workspace_outbox (outbox_id, tenant_id, project_id, workspace_id, aggregate_type, aggregate_id, event_type, stream_name, event_sequence, payload_json, metadata_json, idempotency_key, status, attempt_count, max_attempts, publication_attempt_count, publication_max_attempts, created_at, updated_at) VALUES ('plan-outbox-1', 'tenant-1', 'project-1', 'workspace-1', 'workspace_plan', 'plan-1', 'workspace_pipeline_run_requested', 'workspace.events', 0, '{\"workspace_id\":\"workspace-1\",\"plan_id\":\"plan-1\",\"node_id\":\"node-1\",\"actor_id\":\"user-1\"}', '{}', 'plan-key-1', 'pending', 0, 3, 0, 3, '1970-01-01T00:00:00.000Z', '1970-01-01T00:00:00.000Z')",
    ] {
        db.execute(DbStatement::new(statement)).await?;
    }
    Ok(db)
}
