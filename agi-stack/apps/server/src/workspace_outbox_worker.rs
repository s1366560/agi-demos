//! Server-only Workspace Plan outbox worker foundation.
//!
//! The portable core stays out of this module: it owns no Tokio, SQLx, or
//! Postgres contracts. This file is the strangler-side host shell that can claim
//! Python-shaped `workspace_plan_outbox` rows and dispatch them to event
//! handlers once each P6 runtime slice is migrated.

use std::collections::HashMap;
use std::sync::Arc;

use agistack_adapters_postgres::{PgWorkspaceRepository, WorkspacePlanOutboxRecord};
use agistack_core::ports::CoreResult;
use async_trait::async_trait;
use chrono::{DateTime, Utc};
use tokio::task::JoinHandle;
use tokio::time::{sleep, Duration};

pub(crate) type SharedWorkspacePlanOutboxWorker = Arc<WorkspacePlanOutboxWorker>;
pub(crate) type WorkspacePlanOutboxHandlers = HashMap<String, Arc<dyn WorkspacePlanOutboxHandler>>;

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct WorkspacePlanOutboxWorkerConfig {
    pub worker_id: String,
    pub batch_size: i64,
    pub lease_seconds: i64,
    pub poll_interval_millis: u64,
    pub autostart: bool,
}

impl WorkspacePlanOutboxWorkerConfig {
    pub(crate) fn from_env() -> Self {
        let rust_autostart = bool_env("AGISTACK_WORKSPACE_PLAN_OUTBOX_AUTOSTART", false);
        let python_worker_enabled = bool_env("WORKSPACE_PLAN_OUTBOX_ENABLED", true);
        Self {
            worker_id: std::env::var("WORKSPACE_PLAN_OUTBOX_WORKER_ID")
                .ok()
                .filter(|value| !value.trim().is_empty())
                .unwrap_or_else(|| "agistack-rust-workspace-plan-outbox".to_string()),
            batch_size: positive_i64_env("WORKSPACE_PLAN_OUTBOX_BATCH_SIZE", 10),
            lease_seconds: positive_i64_env("WORKSPACE_PLAN_OUTBOX_LEASE_SECONDS", 60),
            poll_interval_millis: positive_millis_env("WORKSPACE_PLAN_OUTBOX_POLL_SECONDS", 2000),
            autostart: rust_autostart && python_worker_enabled,
        }
    }
}

impl Default for WorkspacePlanOutboxWorkerConfig {
    fn default() -> Self {
        Self {
            worker_id: "agistack-rust-workspace-plan-outbox".to_string(),
            batch_size: 10,
            lease_seconds: 60,
            poll_interval_millis: 2000,
            autostart: false,
        }
    }
}

#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub(crate) struct WorkspacePlanOutboxRunReport {
    pub claimed: usize,
    pub completed: usize,
    pub failed: usize,
    pub released: usize,
    pub missing_handler: usize,
    pub skipped: usize,
}

pub(crate) struct WorkspacePlanOutboxWorkerRuntime {
    join: Option<JoinHandle<()>>,
}

impl WorkspacePlanOutboxWorkerRuntime {
    #[cfg(test)]
    async fn shutdown(mut self) {
        if let Some(join) = self.join.take() {
            join.abort();
            let _ = join.await;
        }
    }
}

impl Drop for WorkspacePlanOutboxWorkerRuntime {
    fn drop(&mut self) {
        if let Some(join) = &self.join {
            join.abort();
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
#[allow(dead_code)]
pub(crate) enum WorkspacePlanOutboxHandlerOutcome {
    Complete,
    Release { reason: Option<String> },
}

#[async_trait]
pub(crate) trait WorkspacePlanOutboxHandler: Send + Sync {
    async fn handle(
        &self,
        item: WorkspacePlanOutboxRecord,
    ) -> CoreResult<WorkspacePlanOutboxHandlerOutcome>;
}

#[async_trait]
pub(crate) trait WorkspacePlanOutboxStore: Send + Sync {
    async fn claim_due(
        &self,
        limit: i64,
        lease_owner: &str,
        lease_seconds: i64,
        now: DateTime<Utc>,
    ) -> CoreResult<Vec<WorkspacePlanOutboxRecord>>;

    async fn mark_completed(
        &self,
        outbox_id: &str,
        lease_owner: Option<&str>,
        now: DateTime<Utc>,
    ) -> CoreResult<bool>;

    async fn mark_failed(
        &self,
        outbox_id: &str,
        error_message: &str,
        lease_owner: Option<&str>,
        now: DateTime<Utc>,
    ) -> CoreResult<bool>;

    async fn release_processing(
        &self,
        outbox_id: &str,
        error_message: Option<&str>,
        lease_owner: Option<&str>,
        now: DateTime<Utc>,
    ) -> CoreResult<bool>;
}

pub(crate) struct PgWorkspacePlanOutboxStore {
    repo: PgWorkspaceRepository,
}

impl PgWorkspacePlanOutboxStore {
    pub(crate) fn new(repo: PgWorkspaceRepository) -> Self {
        Self { repo }
    }
}

#[async_trait]
impl WorkspacePlanOutboxStore for PgWorkspacePlanOutboxStore {
    async fn claim_due(
        &self,
        limit: i64,
        lease_owner: &str,
        lease_seconds: i64,
        now: DateTime<Utc>,
    ) -> CoreResult<Vec<WorkspacePlanOutboxRecord>> {
        self.repo
            .claim_due_plan_outbox(limit, lease_owner, lease_seconds, now)
            .await
    }

    async fn mark_completed(
        &self,
        outbox_id: &str,
        lease_owner: Option<&str>,
        now: DateTime<Utc>,
    ) -> CoreResult<bool> {
        self.repo
            .mark_plan_outbox_completed(outbox_id, lease_owner, now)
            .await
    }

    async fn mark_failed(
        &self,
        outbox_id: &str,
        error_message: &str,
        lease_owner: Option<&str>,
        now: DateTime<Utc>,
    ) -> CoreResult<bool> {
        self.repo
            .mark_plan_outbox_failed(outbox_id, error_message, lease_owner, now)
            .await
    }

    async fn release_processing(
        &self,
        outbox_id: &str,
        error_message: Option<&str>,
        lease_owner: Option<&str>,
        now: DateTime<Utc>,
    ) -> CoreResult<bool> {
        self.repo
            .release_plan_outbox_processing(outbox_id, error_message, lease_owner, now)
            .await
    }
}

pub(crate) struct WorkspacePlanOutboxWorker {
    store: Arc<dyn WorkspacePlanOutboxStore>,
    config: WorkspacePlanOutboxWorkerConfig,
    handlers: WorkspacePlanOutboxHandlers,
}

impl WorkspacePlanOutboxWorker {
    pub(crate) fn new(
        store: Arc<dyn WorkspacePlanOutboxStore>,
        config: WorkspacePlanOutboxWorkerConfig,
        handlers: WorkspacePlanOutboxHandlers,
    ) -> Self {
        Self {
            store,
            config,
            handlers,
        }
    }

    pub(crate) fn handler_count(&self) -> usize {
        self.handlers.len()
    }

    pub(crate) fn spawn_if_enabled(self: Arc<Self>) -> Option<WorkspacePlanOutboxWorkerRuntime> {
        if !self.config.autostart {
            return None;
        }
        if self.handlers.is_empty() {
            eprintln!(
                "[agistack] workspace plan outbox worker: autostart requested but no handlers are registered; not consuming queue"
            );
            return None;
        }
        let worker = Arc::clone(&self);
        let join = tokio::spawn(async move {
            worker.run_loop().await;
        });
        Some(WorkspacePlanOutboxWorkerRuntime { join: Some(join) })
    }

    pub(crate) async fn run_once(&self) -> CoreResult<WorkspacePlanOutboxRunReport> {
        let now = Utc::now();
        let claimed = self
            .store
            .claim_due(
                self.config.batch_size,
                &self.config.worker_id,
                self.config.lease_seconds,
                now,
            )
            .await?;
        let mut report = WorkspacePlanOutboxRunReport {
            claimed: claimed.len(),
            ..Default::default()
        };
        for item in claimed {
            self.process_item(item, &mut report).await?;
        }
        Ok(report)
    }

    async fn run_loop(self: Arc<Self>) {
        loop {
            if let Err(err) = self.run_once().await {
                eprintln!("[agistack] workspace plan outbox worker poll failed: {err}");
            }
            sleep(Duration::from_millis(
                self.config.poll_interval_millis.max(1),
            ))
            .await;
        }
    }

    async fn process_item(
        &self,
        item: WorkspacePlanOutboxRecord,
        report: &mut WorkspacePlanOutboxRunReport,
    ) -> CoreResult<()> {
        let Some(handler) = self.handlers.get(&item.event_type) else {
            let marked = self
                .store
                .mark_failed(
                    &item.id,
                    &format!("no handler for event_type={}", item.event_type),
                    Some(&self.config.worker_id),
                    Utc::now(),
                )
                .await?;
            if marked {
                report.failed += 1;
                report.missing_handler += 1;
            } else {
                report.skipped += 1;
            }
            return Ok(());
        };

        match handler.handle(item.clone()).await {
            Ok(WorkspacePlanOutboxHandlerOutcome::Complete) => {
                if self
                    .store
                    .mark_completed(&item.id, Some(&self.config.worker_id), Utc::now())
                    .await?
                {
                    report.completed += 1;
                } else {
                    report.skipped += 1;
                }
            }
            Ok(WorkspacePlanOutboxHandlerOutcome::Release { reason }) => {
                if self
                    .store
                    .release_processing(
                        &item.id,
                        reason.as_deref(),
                        Some(&self.config.worker_id),
                        Utc::now(),
                    )
                    .await?
                {
                    report.released += 1;
                } else {
                    report.skipped += 1;
                }
            }
            Err(err) => {
                if self
                    .store
                    .mark_failed(
                        &item.id,
                        &err.to_string(),
                        Some(&self.config.worker_id),
                        Utc::now(),
                    )
                    .await?
                {
                    report.failed += 1;
                } else {
                    report.skipped += 1;
                }
            }
        }
        Ok(())
    }
}

fn positive_i64_env(name: &str, default: i64) -> i64 {
    std::env::var(name)
        .ok()
        .and_then(|raw| raw.trim().parse::<i64>().ok())
        .filter(|value| *value > 0)
        .unwrap_or(default)
}

fn positive_millis_env(name: &str, default_millis: u64) -> u64 {
    std::env::var(name)
        .ok()
        .and_then(|raw| raw.trim().parse::<f64>().ok())
        .filter(|value| value.is_finite() && *value > 0.0)
        .map(|seconds| (seconds * 1000.0).ceil().max(1.0) as u64)
        .unwrap_or(default_millis)
}

fn bool_env(name: &str, default: bool) -> bool {
    std::env::var(name)
        .ok()
        .map(|raw| {
            matches!(
                raw.trim().to_ascii_lowercase().as_str(),
                "1" | "true" | "yes" | "on"
            )
        })
        .unwrap_or(default)
}

#[cfg(test)]
mod tests {
    use std::sync::Mutex;

    use agistack_core::ports::CoreError;
    use chrono::{Duration, TimeZone};
    use serde_json::json;

    use super::*;

    #[derive(Default)]
    struct FakeWorkspacePlanOutboxStore {
        items: Mutex<HashMap<String, WorkspacePlanOutboxRecord>>,
    }

    impl FakeWorkspacePlanOutboxStore {
        fn insert(&self, item: WorkspacePlanOutboxRecord) {
            self.items.lock().unwrap().insert(item.id.clone(), item);
        }

        fn get(&self, id: &str) -> WorkspacePlanOutboxRecord {
            self.items.lock().unwrap().get(id).unwrap().clone()
        }
    }

    #[async_trait]
    impl WorkspacePlanOutboxStore for FakeWorkspacePlanOutboxStore {
        async fn claim_due(
            &self,
            limit: i64,
            lease_owner: &str,
            lease_seconds: i64,
            now: DateTime<Utc>,
        ) -> CoreResult<Vec<WorkspacePlanOutboxRecord>> {
            let mut items = self.items.lock().unwrap();
            let mut due = items
                .values()
                .filter(|item| {
                    item.attempt_count < item.max_attempts
                        && ((matches!(item.status.as_str(), "pending" | "failed")
                            && item.next_attempt_at.map(|due| due <= now).unwrap_or(true))
                            || (item.status == "processing"
                                && item
                                    .lease_expires_at
                                    .map(|expires_at| expires_at <= now)
                                    .unwrap_or(false)))
                })
                .map(|item| item.id.clone())
                .collect::<Vec<_>>();
            due.sort();
            due.truncate(limit.max(0) as usize);

            let mut claimed = Vec::new();
            for id in due {
                let item = items.get_mut(&id).unwrap();
                item.status = "processing".to_string();
                item.attempt_count += 1;
                item.lease_owner = Some(lease_owner.to_string());
                item.lease_expires_at = Some(now + Duration::seconds(lease_seconds.max(1)));
                item.next_attempt_at = None;
                item.last_error = None;
                item.updated_at = Some(now);
                claimed.push(item.clone());
            }
            Ok(claimed)
        }

        async fn mark_completed(
            &self,
            outbox_id: &str,
            lease_owner: Option<&str>,
            now: DateTime<Utc>,
        ) -> CoreResult<bool> {
            let mut items = self.items.lock().unwrap();
            let Some(item) = items.get_mut(outbox_id) else {
                return Ok(false);
            };
            if item.status != "processing" || item.lease_owner.as_deref() != lease_owner {
                return Ok(false);
            }
            item.status = "completed".to_string();
            item.lease_owner = None;
            item.lease_expires_at = None;
            item.last_error = None;
            item.next_attempt_at = None;
            item.processed_at = Some(now);
            item.updated_at = Some(now);
            Ok(true)
        }

        async fn mark_failed(
            &self,
            outbox_id: &str,
            error_message: &str,
            lease_owner: Option<&str>,
            now: DateTime<Utc>,
        ) -> CoreResult<bool> {
            let mut items = self.items.lock().unwrap();
            let Some(item) = items.get_mut(outbox_id) else {
                return Ok(false);
            };
            if item.status != "processing" || item.lease_owner.as_deref() != lease_owner {
                return Ok(false);
            }
            item.status = if item.attempt_count >= item.max_attempts {
                "dead_letter".to_string()
            } else {
                "failed".to_string()
            };
            item.lease_owner = None;
            item.lease_expires_at = None;
            item.last_error = Some(error_message.to_string());
            item.next_attempt_at = Some(now + Duration::seconds(2));
            item.updated_at = Some(now);
            Ok(true)
        }

        async fn release_processing(
            &self,
            outbox_id: &str,
            error_message: Option<&str>,
            lease_owner: Option<&str>,
            now: DateTime<Utc>,
        ) -> CoreResult<bool> {
            let mut items = self.items.lock().unwrap();
            let Some(item) = items.get_mut(outbox_id) else {
                return Ok(false);
            };
            if item.status != "processing" || item.lease_owner.as_deref() != lease_owner {
                return Ok(false);
            }
            item.status = "pending".to_string();
            item.lease_owner = None;
            item.lease_expires_at = None;
            item.last_error = error_message.map(str::to_string);
            item.next_attempt_at = None;
            item.attempt_count = (item.attempt_count - 1).max(0);
            item.updated_at = Some(now);
            Ok(true)
        }
    }

    #[derive(Clone)]
    enum HandlerBehavior {
        Complete,
        Release,
        Fail,
    }

    struct StaticHandler {
        behavior: HandlerBehavior,
    }

    #[async_trait]
    impl WorkspacePlanOutboxHandler for StaticHandler {
        async fn handle(
            &self,
            _item: WorkspacePlanOutboxRecord,
        ) -> CoreResult<WorkspacePlanOutboxHandlerOutcome> {
            match self.behavior {
                HandlerBehavior::Complete => Ok(WorkspacePlanOutboxHandlerOutcome::Complete),
                HandlerBehavior::Release => Ok(WorkspacePlanOutboxHandlerOutcome::Release {
                    reason: Some("shutdown".to_string()),
                }),
                HandlerBehavior::Fail => Err(CoreError::Storage("handler boom".to_string())),
            }
        }
    }

    fn worker(
        store: Arc<FakeWorkspacePlanOutboxStore>,
        handlers: WorkspacePlanOutboxHandlers,
    ) -> WorkspacePlanOutboxWorker {
        WorkspacePlanOutboxWorker::new(
            store,
            WorkspacePlanOutboxWorkerConfig {
                worker_id: "worker-test".to_string(),
                batch_size: 10,
                lease_seconds: 60,
                poll_interval_millis: 5,
                autostart: false,
            },
            handlers,
        )
    }

    fn handler(behavior: HandlerBehavior) -> Arc<dyn WorkspacePlanOutboxHandler> {
        Arc::new(StaticHandler { behavior })
    }

    fn outbox(id: &str, event_type: &str) -> WorkspacePlanOutboxRecord {
        WorkspacePlanOutboxRecord {
            id: id.to_string(),
            plan_id: Some("plan-test".to_string()),
            workspace_id: "workspace-test".to_string(),
            event_type: event_type.to_string(),
            payload_json: json!({"id": id}),
            status: "pending".to_string(),
            attempt_count: 0,
            max_attempts: 3,
            lease_owner: None,
            lease_expires_at: None,
            last_error: None,
            next_attempt_at: None,
            processed_at: None,
            metadata_json: json!({}),
            created_at: Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap(),
            updated_at: None,
        }
    }

    #[tokio::test]
    async fn workspace_outbox_worker_marks_registered_handler_completed() {
        let store = Arc::new(FakeWorkspacePlanOutboxStore::default());
        store.insert(outbox("job-complete", "known"));
        let worker = worker(
            Arc::clone(&store),
            HashMap::from([("known".to_string(), handler(HandlerBehavior::Complete))]),
        );

        let report = worker.run_once().await.unwrap();

        assert_eq!(
            report,
            WorkspacePlanOutboxRunReport {
                claimed: 1,
                completed: 1,
                ..Default::default()
            }
        );
        let item = store.get("job-complete");
        assert_eq!(item.status, "completed");
        assert!(item.processed_at.is_some());
        assert_eq!(item.attempt_count, 1);
    }

    #[tokio::test]
    async fn workspace_outbox_worker_fails_missing_handler_without_dropping_job() {
        let store = Arc::new(FakeWorkspacePlanOutboxStore::default());
        store.insert(outbox("job-missing", "unknown"));
        let worker = worker(Arc::clone(&store), HashMap::new());

        let report = worker.run_once().await.unwrap();

        assert_eq!(
            report,
            WorkspacePlanOutboxRunReport {
                claimed: 1,
                failed: 1,
                missing_handler: 1,
                ..Default::default()
            }
        );
        let item = store.get("job-missing");
        assert_eq!(item.status, "failed");
        assert_eq!(
            item.last_error.as_deref(),
            Some("no handler for event_type=unknown")
        );
        assert_eq!(item.attempt_count, 1);
    }

    #[tokio::test]
    async fn workspace_outbox_worker_release_outcome_returns_attempt_budget() {
        let store = Arc::new(FakeWorkspacePlanOutboxStore::default());
        store.insert(outbox("job-release", "known"));
        let worker = worker(
            Arc::clone(&store),
            HashMap::from([("known".to_string(), handler(HandlerBehavior::Release))]),
        );

        let report = worker.run_once().await.unwrap();

        assert_eq!(
            report,
            WorkspacePlanOutboxRunReport {
                claimed: 1,
                released: 1,
                ..Default::default()
            }
        );
        let item = store.get("job-release");
        assert_eq!(item.status, "pending");
        assert_eq!(item.last_error.as_deref(), Some("shutdown"));
        assert_eq!(item.attempt_count, 0);
    }

    #[tokio::test]
    async fn workspace_outbox_worker_failed_handler_marks_retryable_failure() {
        let store = Arc::new(FakeWorkspacePlanOutboxStore::default());
        store.insert(outbox("job-fail", "known"));
        let worker = worker(
            Arc::clone(&store),
            HashMap::from([("known".to_string(), handler(HandlerBehavior::Fail))]),
        );

        let report = worker.run_once().await.unwrap();

        assert_eq!(
            report,
            WorkspacePlanOutboxRunReport {
                claimed: 1,
                failed: 1,
                ..Default::default()
            }
        );
        let item = store.get("job-fail");
        assert_eq!(item.status, "failed");
        assert_eq!(
            item.last_error.as_deref(),
            Some("storage error: handler boom")
        );
        assert_eq!(item.attempt_count, 1);
    }

    #[tokio::test]
    async fn workspace_outbox_loop_refuses_autostart_without_handlers() {
        let store = Arc::new(FakeWorkspacePlanOutboxStore::default());
        store.insert(outbox("job-safe", "unknown"));
        let worker = Arc::new(WorkspacePlanOutboxWorker::new(
            Arc::clone(&store) as Arc<dyn WorkspacePlanOutboxStore>,
            WorkspacePlanOutboxWorkerConfig {
                autostart: true,
                ..WorkspacePlanOutboxWorkerConfig::default()
            },
            HashMap::new(),
        ));

        let runtime = worker.spawn_if_enabled();

        assert!(runtime.is_none());
        let item = store.get("job-safe");
        assert_eq!(item.status, "pending");
        assert_eq!(item.attempt_count, 0);
    }

    #[tokio::test]
    async fn workspace_outbox_loop_polls_until_stopped_when_handlers_exist() {
        let store = Arc::new(FakeWorkspacePlanOutboxStore::default());
        store.insert(outbox("job-loop", "known"));
        let worker = Arc::new(WorkspacePlanOutboxWorker::new(
            Arc::clone(&store) as Arc<dyn WorkspacePlanOutboxStore>,
            WorkspacePlanOutboxWorkerConfig {
                worker_id: "worker-test".to_string(),
                batch_size: 10,
                lease_seconds: 60,
                poll_interval_millis: 5,
                autostart: true,
            },
            HashMap::from([("known".to_string(), handler(HandlerBehavior::Complete))]),
        ));
        let runtime = worker.spawn_if_enabled().expect("runtime should start");

        for _ in 0..20 {
            if store.get("job-loop").status == "completed" {
                runtime.shutdown().await;
                let item = store.get("job-loop");
                assert_eq!(item.status, "completed");
                assert_eq!(item.attempt_count, 1);
                return;
            }
            sleep(tokio::time::Duration::from_millis(5)).await;
        }
        runtime.shutdown().await;
        panic!("worker loop did not complete the job");
    }
}
