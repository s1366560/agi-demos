use std::sync::Arc;
use std::time::Duration;

use anyhow::Result;
use async_trait::async_trait;
use bcs_db_api::{DbPlugin, DbStatement};
use bcs_db_local::LocalSqliteDbPlugin;
use memstack_workspace_service_api::{
    WorkspacePlanDispatchPort, WorkspacePlanDispatchPortError, WorkspacePlanDispatchReceipt,
    WorkspacePlanDispatchRequest,
};
use tokio::sync::Mutex;

#[allow(dead_code)]
#[path = "../src/plan_delivery_worker.rs"]
mod plan_delivery_worker;

use plan_delivery_worker::{WorkspacePlanDeliveryWorker, WorkspacePlanDeliveryWorkerConfig};

struct RecordingDispatcher {
    requests: Mutex<Vec<WorkspacePlanDispatchRequest>>,
    error: Option<WorkspacePlanDispatchPortError>,
}

impl RecordingDispatcher {
    fn accepted() -> Self {
        Self {
            requests: Mutex::new(Vec::new()),
            error: None,
        }
    }

    fn rejected() -> Self {
        Self {
            requests: Mutex::new(Vec::new()),
            error: Some(WorkspacePlanDispatchPortError::Rejected),
        }
    }
}

#[async_trait]
impl WorkspacePlanDispatchPort for RecordingDispatcher {
    async fn dispatch(
        &self,
        request: &WorkspacePlanDispatchRequest,
    ) -> Result<WorkspacePlanDispatchReceipt, WorkspacePlanDispatchPortError> {
        self.requests.lock().await.push(request.clone());
        if let Some(error) = self.error {
            return Err(error);
        }
        WorkspacePlanDispatchReceipt::new(
            "memstack-agent-runtime".to_string(),
            request
                .agent_id()
                .unwrap_or("workspace-supervisor")
                .to_string(),
            format!("provider-run:{}", request.outbox_id()),
        )
        .map_err(|_| WorkspacePlanDispatchPortError::Unavailable)
    }
}

fn worker_config() -> WorkspacePlanDeliveryWorkerConfig {
    WorkspacePlanDeliveryWorkerConfig {
        worker_id: "plan-worker-1".to_string(),
        batch_size: 10,
        lease_duration: Duration::from_secs(30),
        poll_interval: Duration::from_millis(10),
        retry_base: Duration::from_secs(1),
        retry_max: Duration::from_secs(8),
    }
}

async fn seeded_db(max_attempts: u32) -> Result<Arc<LocalSqliteDbPlugin>> {
    let db = Arc::new(LocalSqliteDbPlugin::new()?);
    for statement in [
        "CREATE TABLE workspace_profiles (tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, group_id TEXT NOT NULL, PRIMARY KEY(tenant_id, project_id, workspace_id))".to_string(),
        "CREATE TABLE workspace_plan_nodes (tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, plan_id TEXT NOT NULL, node_id TEXT NOT NULL, workspace_task_id TEXT, current_attempt_id TEXT, assignee_agent_id TEXT, PRIMARY KEY(plan_id, node_id))".to_string(),
        "CREATE TABLE workspace_outbox (outbox_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, aggregate_type TEXT NOT NULL, aggregate_id TEXT NOT NULL, event_type TEXT NOT NULL, stream_name TEXT NOT NULL, event_sequence INTEGER NOT NULL, payload_json TEXT NOT NULL, metadata_json TEXT NOT NULL, correlation_id TEXT, idempotency_key TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', attempt_count INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 10, lease_owner TEXT, lease_expires_at TEXT, last_error TEXT, next_attempt_at TEXT, dispatched_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)".to_string(),
        "CREATE TABLE workspace_agent_runtime_correlations (correlation_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, user_id TEXT, task_id TEXT, attempt_id TEXT, plan_id TEXT, plan_node_id TEXT, conversation_id TEXT NOT NULL, bcs_group_id TEXT, delivery_request_id TEXT UNIQUE, provider_run_id TEXT UNIQUE, provider_id TEXT, provider_bot_ref TEXT, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)".to_string(),
        "INSERT INTO workspace_profiles (tenant_id, project_id, workspace_id, group_id) VALUES ('tenant-1', 'project-1', 'workspace-1', 'group-1')".to_string(),
        "INSERT INTO workspace_plan_nodes (tenant_id, project_id, workspace_id, plan_id, node_id, workspace_task_id, current_attempt_id, assignee_agent_id) VALUES ('tenant-1', 'project-1', 'workspace-1', 'plan-1', 'node-1', 'task-1', 'attempt-1', 'agent-1')".to_string(),
        format!("INSERT INTO workspace_outbox (outbox_id, tenant_id, project_id, workspace_id, aggregate_type, aggregate_id, event_type, stream_name, event_sequence, payload_json, metadata_json, idempotency_key, status, attempt_count, max_attempts, created_at, updated_at) VALUES ('plan-outbox-1', 'tenant-1', 'project-1', 'workspace-1', 'workspace_plan', 'plan-1', 'workspace_pipeline_run_requested', 'workspace.events', 0, '{{\"workspace_id\":\"workspace-1\",\"plan_id\":\"plan-1\",\"node_id\":\"node-1\",\"actor_id\":\"user-1\"}}', '{{}}', 'plan-key-1', 'pending', 0, {max_attempts}, '1970-01-01T00:00:00.000Z', '1970-01-01T00:00:00.000Z')"),
    ] {
        db.execute(DbStatement::new(statement)).await?;
    }
    Ok(db)
}

#[test]
fn config_is_bounded() {
    let mut config = worker_config();
    assert!(config.validate().is_ok());
    config.worker_id = " ".to_string();
    assert!(config.validate().is_err());
    config = worker_config();
    config.batch_size = 101;
    assert!(config.validate().is_err());
    config = worker_config();
    config.retry_base = Duration::from_secs(9);
    assert!(config.validate().is_err());
}

#[tokio::test]
async fn accepted_dispatch_persists_runtime_correlation_before_handoff() -> Result<()> {
    let db = seeded_db(3).await?;
    let dispatcher = Arc::new(RecordingDispatcher::accepted());
    let worker = WorkspacePlanDeliveryWorker::new(
        db.clone(),
        bcs_db_api::DbSqlFlavor::Sqlite,
        dispatcher.clone(),
        worker_config(),
    )?;

    let outcome = worker.dispatch_once_at(2_000).await?;

    assert_eq!(outcome.claimed, 1);
    assert_eq!(outcome.completed, 1);
    let requests = dispatcher.requests.lock().await;
    assert_eq!(requests.len(), 1);
    assert_eq!(requests[0].tenant_id(), "tenant-1");
    assert_eq!(requests[0].project_id(), "project-1");
    assert_eq!(requests[0].workspace_id(), "workspace-1");
    assert_eq!(requests[0].plan_id(), "plan-1");
    assert_eq!(requests[0].plan_node_id(), Some("node-1"));
    assert_eq!(requests[0].task_id(), Some("task-1"));
    assert_eq!(requests[0].attempt_id(), Some("attempt-1"));
    assert_eq!(requests[0].agent_id(), Some("agent-1"));
    assert_eq!(requests[0].action().as_str(), "run_pipeline");
    drop(requests);
    let rows = db
        .query(DbStatement::new(
            "SELECT status, lease_owner FROM workspace_outbox WHERE outbox_id = 'plan-outbox-1'",
        ))
        .await?;
    assert_eq!(
        rows[0].get_string("status")?.as_deref(),
        Some("runtime_dispatched")
    );
    assert_eq!(rows[0].get_string("lease_owner")?, None);
    let correlations = db
        .query(DbStatement::new(
            "SELECT task_id, plan_id, plan_node_id, conversation_id, provider_run_id, status FROM workspace_agent_runtime_correlations",
        ))
        .await?;
    assert_eq!(correlations.len(), 1);
    assert_eq!(
        correlations[0].get_string("provider_run_id")?.as_deref(),
        Some("provider-run:plan-outbox-1")
    );
    assert_eq!(
        correlations[0].get_string("status")?.as_deref(),
        Some("running")
    );
    Ok(())
}

#[tokio::test]
async fn rejected_dispatch_persists_only_stable_error_and_schedules_retry() -> Result<()> {
    let db = seeded_db(3).await?;
    let dispatcher = Arc::new(RecordingDispatcher::rejected());
    let worker = WorkspacePlanDeliveryWorker::new(
        db.clone(),
        bcs_db_api::DbSqlFlavor::Sqlite,
        dispatcher,
        worker_config(),
    )?;

    let outcome = worker.dispatch_once_at(2_000).await?;

    assert_eq!(outcome.claimed, 1);
    assert_eq!(outcome.retry_scheduled, 1);
    let rows = db
        .query(DbStatement::new(
            "SELECT status, next_attempt_at, last_error FROM workspace_outbox WHERE outbox_id = 'plan-outbox-1'",
        ))
        .await?;
    assert_eq!(rows[0].get_string("status")?.as_deref(), Some("failed"));
    assert_eq!(
        rows[0].get_string("next_attempt_at")?.as_deref(),
        Some("1970-01-01T00:00:03.000Z")
    );
    assert_eq!(
        rows[0].get_string("last_error")?.as_deref(),
        Some("workspace_plan_provider_rejected")
    );
    assert!(
        db.query(DbStatement::new(
            "SELECT correlation_id FROM workspace_agent_runtime_correlations"
        ))
        .await?
        .is_empty()
    );
    Ok(())
}

#[tokio::test]
async fn rejected_final_attempt_dead_letters_without_another_side_effect() -> Result<()> {
    let db = seeded_db(1).await?;
    let dispatcher = Arc::new(RecordingDispatcher::rejected());
    let worker = WorkspacePlanDeliveryWorker::new(
        db.clone(),
        bcs_db_api::DbSqlFlavor::Sqlite,
        dispatcher.clone(),
        worker_config(),
    )?;

    let outcome = worker.dispatch_once_at(2_000).await?;

    assert_eq!(outcome.dead_lettered, 1);
    assert_eq!(worker.dispatch_once_at(4_000).await?.claimed, 0);
    assert_eq!(dispatcher.requests.lock().await.len(), 1);
    let rows = db
        .query(DbStatement::new(
            "SELECT status, next_attempt_at FROM workspace_outbox WHERE outbox_id = 'plan-outbox-1'",
        ))
        .await?;
    assert_eq!(
        rows[0].get_string("status")?.as_deref(),
        Some("dead_letter")
    );
    assert_eq!(rows[0].get_string("next_attempt_at")?, None);
    Ok(())
}
