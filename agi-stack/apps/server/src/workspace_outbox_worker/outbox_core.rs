use super::*;

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct WorkspacePlanOutboxWorkerConfig {
    pub worker_id: String,
    pub batch_size: i64,
    pub lease_seconds: i64,
    pub poll_interval_millis: u64,
    pub autostart: bool,
    pub production_ready: bool,
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
            production_ready: bool_env(WORKSPACE_PLAN_OUTBOX_PRODUCTION_READY_ENV, false),
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
            production_ready: false,
        }
    }
}

#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub(crate) struct WorkspacePlanOutboxRunReport {
    pub claimed: usize,
    pub completed: usize,
    pub failed: usize,
    pub released: usize,
    pub parked: usize,
    pub missing_handler: usize,
    pub skipped: usize,
}

pub(crate) struct WorkspacePlanOutboxWorkerRuntime {
    join: Option<JoinHandle<()>>,
}

impl WorkspacePlanOutboxWorkerRuntime {
    #[cfg(test)]
    pub(super) async fn shutdown(mut self) {
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
    Release {
        reason: Option<String>,
    },
    Park {
        status: String,
        metadata_patch: Value,
    },
    ParkWithPayload {
        status: String,
        metadata_patch: Value,
        payload_patch: Value,
    },
}

#[async_trait]
pub(crate) trait WorkspacePlanOutboxHandler: Send + Sync {
    async fn handle(
        &self,
        item: WorkspacePlanOutboxRecord,
    ) -> CoreResult<WorkspacePlanOutboxHandlerOutcome>;
}

#[async_trait]
pub(crate) trait WorkspacePipelineStageRunner: Send + Sync {
    async fn run_stage(
        &self,
        project_id: &str,
        contract: &PipelineContractFoundation,
        stage: &PipelineStageSpec,
    ) -> PipelineStageResult;
}

pub(super) fn merge_metadata_patch(target: &mut Map<String, Value>, patch: &Map<String, Value>) {
    for (key, value) in patch {
        target.insert(key.clone(), value.clone());
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
        if !self.config.production_ready {
            eprintln!(
                "[agistack] workspace plan outbox worker: autostart requested but production readiness gate is disabled (set {WORKSPACE_PLAN_OUTBOX_PRODUCTION_READY_ENV}=true after full handler parity); not consuming queue"
            );
            return None;
        }
        let missing_handlers = missing_required_handler_event_types(&self.handlers);
        if !missing_handlers.is_empty() {
            eprintln!(
                "[agistack] workspace plan outbox worker: autostart requested but handlers are incomplete (missing: {}); not consuming queue",
                missing_handlers.join(", ")
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
            Ok(WorkspacePlanOutboxHandlerOutcome::Park {
                status,
                metadata_patch,
            }) => {
                if self
                    .store
                    .park_processing(
                        &item.id,
                        &status,
                        &metadata_patch,
                        Some(&self.config.worker_id),
                        Utc::now(),
                    )
                    .await?
                {
                    report.parked += 1;
                } else {
                    report.skipped += 1;
                }
            }
            Ok(WorkspacePlanOutboxHandlerOutcome::ParkWithPayload {
                status,
                metadata_patch,
                payload_patch,
            }) => {
                if self
                    .store
                    .park_processing_with_payload_patch(
                        &item.id,
                        &status,
                        &metadata_patch,
                        &payload_patch,
                        Some(&self.config.worker_id),
                        Utc::now(),
                    )
                    .await?
                {
                    report.parked += 1;
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

pub(super) fn positive_i64_env(name: &str, default: i64) -> i64 {
    std::env::var(name)
        .ok()
        .and_then(|raw| raw.trim().parse::<i64>().ok())
        .filter(|value| *value > 0)
        .unwrap_or(default)
}

pub(super) fn i64_env(name: &str, default: i64) -> i64 {
    std::env::var(name)
        .ok()
        .and_then(|raw| raw.trim().parse::<i64>().ok())
        .unwrap_or(default)
}

pub(super) fn positive_millis_env(name: &str, default_millis: u64) -> u64 {
    std::env::var(name)
        .ok()
        .and_then(|raw| raw.trim().parse::<f64>().ok())
        .filter(|value| value.is_finite() && *value > 0.0)
        .map(|seconds| (seconds * 1000.0).ceil().max(1.0) as u64)
        .unwrap_or(default_millis)
}

pub(super) fn bool_env(name: &str, default: bool) -> bool {
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

pub(super) fn required_handler_event_types() -> [&'static str; 5] {
    [
        SUPERVISOR_TICK_EVENT,
        WORKER_LAUNCH_EVENT,
        HANDOFF_RESUME_EVENT,
        ATTEMPT_RETRY_EVENT,
        PIPELINE_RUN_REQUESTED_EVENT,
    ]
}

pub(super) fn missing_required_handler_event_types(
    handlers: &WorkspacePlanOutboxHandlers,
) -> Vec<String> {
    required_handler_event_types()
        .into_iter()
        .filter(|event_type| !handlers.contains_key(*event_type))
        .map(ToOwned::to_owned)
        .collect()
}

pub(super) fn object_or_empty(value: Value) -> Map<String, Value> {
    match value {
        Value::Object(map) => map,
        _ => Map::new(),
    }
}

pub(super) fn string_from_map(map: &Map<String, Value>, key: &str) -> Option<String> {
    map.get(key)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToOwned::to_owned)
}

pub(super) fn string_from_value_object(value: &Value, key: &str) -> Option<String> {
    value.as_object().and_then(|map| string_from_map(map, key))
}
