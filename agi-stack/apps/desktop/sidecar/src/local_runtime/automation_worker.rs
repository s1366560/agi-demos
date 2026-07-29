use std::{
    sync::{Arc, Mutex},
    time::Duration,
};

use async_trait::async_trait;
use serde_json::{json, Value};
use tokio::{
    sync::watch,
    task::JoinHandle,
    time::{interval, sleep},
};

use super::{
    automation_dispatcher::{
        claim_next_operation, dispatch_due_schedules, renew_operation_lease, retry_operation,
        settle_operation_with_result, AutomationClock, AutomationExecutionRecord,
        AutomationLedgerError, AutomationOperationClaim, AutomationRunStatus,
    },
    automation_hitl::{
        reconcile_waiting_human, resume_answered_wait, validate_waiting_outcome,
        AutomationHitlAuthority, AutomationHitlResumeOutcome,
    },
    session_store::DesktopSessionStore,
};

#[derive(Clone, Debug, PartialEq, Eq)]
pub(super) struct AutomationWorkerExecution {
    pub(super) result_summary: Value,
    pub(super) event_count: u64,
    pub(super) execution_time_ms: u64,
    pub(super) conversation_id: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(super) struct AutomationWorkerWait {
    pub(super) request_id: String,
    pub(super) result_summary: Value,
    pub(super) event_count: u64,
    pub(super) execution_time_ms: u64,
    pub(super) conversation_id: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(super) enum AutomationExecutorOutcome {
    Completed(AutomationWorkerExecution),
    WaitingHuman(AutomationWorkerWait),
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(super) struct AutomationExecutorError {
    pub(super) code: String,
    pub(super) retryable: bool,
}

impl AutomationExecutorError {
    pub(super) fn retryable(code: impl Into<String>) -> Self {
        Self {
            code: code.into(),
            retryable: true,
        }
    }

    pub(super) fn permanent(code: impl Into<String>) -> Self {
        Self {
            code: code.into(),
            retryable: false,
        }
    }
}

#[async_trait]
pub(super) trait AutomationExecutor: Send + Sync {
    async fn execute(
        &self,
        claim: &AutomationOperationClaim,
    ) -> Result<AutomationExecutorOutcome, AutomationExecutorError>;

    async fn recover_answered_hitl(
        &self,
        _authority: &AutomationHitlAuthority,
    ) -> Result<(), AutomationExecutorError> {
        Err(AutomationExecutorError::permanent(
            "local_automation_hitl_recovery_unsupported",
        ))
    }
}

#[derive(Clone, Debug)]
pub(super) struct AutomationWorkerConfig {
    pub(super) worker_id: String,
    pub(super) batch_size: usize,
    pub(super) lease_duration: Duration,
    pub(super) heartbeat_interval: Duration,
    pub(super) poll_interval: Duration,
    pub(super) retry_backoff: Duration,
    pub(super) shutdown_grace: Duration,
}

impl AutomationWorkerConfig {
    pub(super) fn local_default() -> Self {
        Self {
            worker_id: format!("local-automation-worker-{}", uuid::Uuid::new_v4()),
            batch_size: 4,
            lease_duration: Duration::from_secs(60),
            heartbeat_interval: Duration::from_secs(15),
            poll_interval: Duration::from_secs(1),
            retry_backoff: Duration::from_secs(5),
            shutdown_grace: Duration::from_secs(5),
        }
    }

    fn validate(&self) -> Result<(), AutomationWorkerError> {
        if self.worker_id.trim().is_empty()
            || self.batch_size == 0
            || self.batch_size > 64
            || self.lease_duration.is_zero()
            || self.heartbeat_interval.is_zero()
            || self.heartbeat_interval >= self.lease_duration
            || self.poll_interval.is_zero()
            || self.shutdown_grace.is_zero()
            || self.shutdown_grace > Duration::from_secs(30)
        {
            return Err(AutomationWorkerError::InvalidConfiguration);
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub(super) struct AutomationWorkerDrainReport {
    pub(super) scheduled: usize,
    pub(super) claimed: usize,
    pub(super) hitl_requeued: usize,
    pub(super) hitl_expired: usize,
    pub(super) waiting_human: usize,
    pub(super) succeeded: usize,
    pub(super) failed: usize,
    pub(super) timed_out: usize,
    pub(super) requeued: usize,
    pub(super) lost_lease: usize,
}

#[derive(Debug)]
pub(super) enum AutomationWorkerError {
    InvalidConfiguration,
    Ledger(AutomationLedgerError),
}

impl std::fmt::Display for AutomationWorkerError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InvalidConfiguration => formatter.write_str("invalid automation worker config"),
            Self::Ledger(error) => write!(formatter, "automation ledger error: {error:?}"),
        }
    }
}

impl From<AutomationLedgerError> for AutomationWorkerError {
    fn from(value: AutomationLedgerError) -> Self {
        Self::Ledger(value)
    }
}

pub(super) struct AutomationWorker {
    store: DesktopSessionStore,
    executor: Arc<dyn AutomationExecutor>,
    clock: Arc<dyn AutomationClock>,
    config: AutomationWorkerConfig,
}

impl AutomationWorker {
    pub(super) fn new(
        store: DesktopSessionStore,
        executor: Arc<dyn AutomationExecutor>,
        clock: Arc<dyn AutomationClock>,
        config: AutomationWorkerConfig,
    ) -> Result<Self, AutomationWorkerError> {
        config.validate()?;
        Ok(Self {
            store,
            executor,
            clock,
            config,
        })
    }

    pub(super) async fn drain_once(
        &self,
    ) -> Result<AutomationWorkerDrainReport, AutomationWorkerError> {
        let mut hitl_reconciliation = reconcile_waiting_human(&self.store, self.clock.as_ref())?;
        let mut hitl_requeued = 0;
        for authority in hitl_reconciliation.answered {
            self.executor
                .recover_answered_hitl(&authority)
                .await
                .map_err(|error| {
                    AutomationWorkerError::Ledger(AutomationLedgerError::InvalidRecord(error.code))
                })?;
            match resume_answered_wait(&self.store, &authority.request_id, self.clock.now())? {
                AutomationHitlResumeOutcome::Requeued => hitl_requeued += 1,
                AutomationHitlResumeOutcome::Expired => hitl_reconciliation.expired += 1,
                AutomationHitlResumeOutcome::AlreadyResumed => {}
            }
        }
        let scheduled =
            dispatch_due_schedules(&self.store, self.clock.as_ref(), self.config.batch_size)?;
        let mut report = AutomationWorkerDrainReport {
            scheduled: scheduled.enqueued,
            hitl_requeued,
            hitl_expired: hitl_reconciliation.expired,
            ..Default::default()
        };
        for _ in 0..self.config.batch_size {
            let Some(claim) = claim_next_operation(
                &self.store,
                &self.config.worker_id,
                self.config.lease_duration,
                self.clock.as_ref(),
            )?
            else {
                break;
            };
            report.claimed += 1;
            self.drive_claim(&claim, &mut report).await?;
        }
        Ok(report)
    }

    async fn drive_claim(
        &self,
        claim: &AutomationOperationClaim,
        report: &mut AutomationWorkerDrainReport,
    ) -> Result<(), AutomationWorkerError> {
        let remaining = (claim.deadline_at - self.clock.now())
            .to_std()
            .unwrap_or(Duration::ZERO);
        if remaining.is_zero() {
            self.settle_failure(claim, AutomationRunStatus::Timeout, "automation_timed_out")?;
            report.timed_out += 1;
            return Ok(());
        }

        let execution = self.executor.execute(claim);
        tokio::pin!(execution);
        let deadline = sleep(remaining);
        tokio::pin!(deadline);
        let mut heartbeat = interval(self.config.heartbeat_interval);
        heartbeat.tick().await;
        let outcome = loop {
            tokio::select! {
                result = &mut execution => break Some(result),
                _ = &mut deadline => break None,
                _ = heartbeat.tick() => {
                    if !renew_operation_lease(
                        &self.store,
                        claim,
                        self.config.lease_duration,
                        self.clock.as_ref(),
                    )? {
                        report.lost_lease += 1;
                        return Ok(());
                    }
                }
            }
        };

        match outcome {
            Some(Ok(AutomationExecutorOutcome::Completed(execution))) => {
                settle_operation_with_result(
                    &self.store,
                    claim,
                    AutomationRunStatus::Success,
                    AutomationExecutionRecord {
                        error_code: None,
                        result_summary: Some(execution.result_summary),
                        event_count: execution.event_count,
                        execution_time_ms: execution.execution_time_ms,
                        conversation_id: Some(execution.conversation_id),
                    },
                    self.clock.as_ref(),
                )?;
                report.succeeded += 1;
            }
            Some(Ok(AutomationExecutorOutcome::WaitingHuman(wait))) => {
                validate_waiting_outcome(
                    &self.store,
                    claim,
                    &wait.conversation_id,
                    &wait.request_id,
                )?;
                settle_operation_with_result(
                    &self.store,
                    claim,
                    AutomationRunStatus::WaitingHuman,
                    AutomationExecutionRecord {
                        error_code: None,
                        result_summary: Some(wait.result_summary),
                        event_count: wait.event_count,
                        execution_time_ms: wait.execution_time_ms,
                        conversation_id: Some(wait.conversation_id),
                    },
                    self.clock.as_ref(),
                )?;
                report.waiting_human += 1;
            }
            Some(Err(error)) if error.retryable => {
                if retry_operation(
                    &self.store,
                    claim,
                    &error.code,
                    self.config.retry_backoff,
                    self.clock.as_ref(),
                )? {
                    report.requeued += 1;
                } else {
                    self.settle_failure(claim, AutomationRunStatus::Failed, &error.code)?;
                    report.failed += 1;
                }
            }
            Some(Err(error)) => {
                self.settle_failure(claim, AutomationRunStatus::Failed, &error.code)?;
                report.failed += 1;
            }
            None => {
                self.settle_failure(claim, AutomationRunStatus::Timeout, "automation_timed_out")?;
                report.timed_out += 1;
            }
        }
        Ok(())
    }

    fn settle_failure(
        &self,
        claim: &AutomationOperationClaim,
        status: AutomationRunStatus,
        error_code: &str,
    ) -> Result<(), AutomationLedgerError> {
        settle_operation_with_result(
            &self.store,
            claim,
            status,
            AutomationExecutionRecord {
                error_code: Some(error_code.to_string()),
                result_summary: Some(json!({
                    "authority": "local_automation_worker",
                    "error_code": error_code,
                })),
                event_count: 0,
                execution_time_ms: 0,
                conversation_id: claim.conversation_id.clone(),
            },
            self.clock.as_ref(),
        )
    }

    async fn run(self, mut shutdown: watch::Receiver<bool>) {
        loop {
            if *shutdown.borrow() {
                return;
            }
            if let Err(error) = self.drain_once().await {
                tracing::warn!(error = ?error, "local automation worker drain failed");
            }
            tokio::select! {
                _ = sleep(self.config.poll_interval) => {}
                changed = shutdown.changed() => {
                    if changed.is_err() || *shutdown.borrow() {
                        return;
                    }
                }
            }
        }
    }
}

pub(super) struct AutomationWorkerHandle {
    shutdown: watch::Sender<bool>,
    task: Mutex<Option<JoinHandle<()>>>,
    shutdown_grace: Duration,
}

impl AutomationWorkerHandle {
    pub(super) fn spawn(worker: AutomationWorker) -> Self {
        let (shutdown, receiver) = watch::channel(false);
        let shutdown_grace = worker.config.shutdown_grace;
        Self {
            shutdown,
            task: Mutex::new(Some(tokio::spawn(worker.run(receiver)))),
            shutdown_grace,
        }
    }

    pub(super) fn is_running(&self) -> bool {
        self.task
            .lock()
            .expect("automation worker task")
            .as_ref()
            .is_some_and(|task| !task.is_finished())
    }

    pub(super) async fn shutdown(&self) {
        let _ = self.shutdown.send(true);
        let task = self.task.lock().expect("automation worker task").take();
        if let Some(mut task) = task {
            if tokio::time::timeout(self.shutdown_grace, &mut task)
                .await
                .is_err()
            {
                task.abort();
                let _ = task.await;
            }
        }
    }
}
