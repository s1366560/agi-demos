//! Durable Agent execution behind accepted cron operations.
//!
//! Operation dispatch and Agent execution intentionally use separate leases:
//! dispatch is short-lived, while the runtime lease spans ReAct checkpoints and
//! HITL suspension. Startup remains fail-closed until schedule reconciliation,
//! scoped tool authority, and encrypted HITL resume are all composed.

#![allow(dead_code)]

use std::sync::Arc;
use std::time::{Duration, Instant};

use agistack_adapters_postgres::{
    AutomationRunContext, AutomationRunLease, AutomationRuntimeRepositoryError,
    AutomationRuntimeScope, AutomationTerminalOutcome, AutomationTerminalProjection,
    CronOperationErrorCode, CronOperationKind, CronOperationRecord, NewHitlRequestRecord,
    PgCronAutomationRuntimeRepository, PgHitlRequestRepository,
};
use agistack_core::agent::{HitlKind, HitlRequest, ReActEngine, ReActObserver, SessionStatus};
use agistack_core::ports::{CoreError, CoreResult};
use async_trait::async_trait;
use chrono::{DateTime, Utc};
use serde_json::json;
use tokio::time::{interval, sleep};
use uuid::Uuid;

use crate::cron_tool_authority::AutomationToolHostFactory;
use crate::cron_worker::{
    CronOperationHandler, CronOperationHandlerFailure, CronOperationHandlerOutcome, CronWorkerClock,
};

#[async_trait]
pub(crate) trait AutomationDispatchStore: Send + Sync {
    async fn prepare_dispatch(
        &self,
        operation: &CronOperationRecord,
        fresh_conversation_id: &str,
        now: DateTime<Utc>,
    ) -> Result<AutomationRunContext, AutomationRuntimeRepositoryError>;
}

#[async_trait]
impl AutomationDispatchStore for PgCronAutomationRuntimeRepository {
    async fn prepare_dispatch(
        &self,
        operation: &CronOperationRecord,
        fresh_conversation_id: &str,
        now: DateTime<Utc>,
    ) -> Result<AutomationRunContext, AutomationRuntimeRepositoryError> {
        PgCronAutomationRuntimeRepository::prepare_dispatch(
            self,
            operation,
            fresh_conversation_id,
            now,
        )
        .await
    }
}

pub(crate) trait ConversationIdFactory: Send + Sync {
    fn fresh_id(&self) -> String;
}

#[derive(Debug, Default)]
pub(crate) struct UuidConversationIdFactory;

impl ConversationIdFactory for UuidConversationIdFactory {
    fn fresh_id(&self) -> String {
        Uuid::new_v4().to_string()
    }
}

pub(crate) struct ExecuteRunDispatchHandler {
    store: Arc<dyn AutomationDispatchStore>,
    clock: Arc<dyn CronWorkerClock>,
    ids: Arc<dyn ConversationIdFactory>,
}

impl ExecuteRunDispatchHandler {
    pub(crate) fn new(
        store: Arc<dyn AutomationDispatchStore>,
        clock: Arc<dyn CronWorkerClock>,
        ids: Arc<dyn ConversationIdFactory>,
    ) -> Self {
        Self { store, clock, ids }
    }
}

#[async_trait]
impl CronOperationHandler for ExecuteRunDispatchHandler {
    fn kind(&self) -> CronOperationKind {
        CronOperationKind::ExecuteRun
    }

    async fn handle(
        &self,
        operation: &CronOperationRecord,
    ) -> CoreResult<CronOperationHandlerOutcome> {
        let context = match self
            .store
            .prepare_dispatch(operation, &self.ids.fresh_id(), self.clock.now())
            .await
        {
            Ok(context) => context,
            Err(AutomationRuntimeRepositoryError::LeaseLost) => {
                return Err(CoreError::Storage(
                    "cron dispatch lease was lost before acceptance".to_string(),
                ));
            }
            Err(AutomationRuntimeRepositoryError::Storage(error)) => {
                return Err(CoreError::Storage(error));
            }
            Err(error) => return Ok(dispatch_failure(error)),
        };
        Ok(CronOperationHandlerOutcome::Accepted {
            dispatch_json: json!({
                "runtime_execution_id": context.runtime_execution_id,
                "conversation_id": context.conversation_id,
                "runtime_status": context.status.as_str(),
            }),
        })
    }
}

fn dispatch_failure(error: AutomationRuntimeRepositoryError) -> CronOperationHandlerOutcome {
    let code = match error {
        AutomationRuntimeRepositoryError::StaleRevision => CronOperationErrorCode::StaleRevision,
        AutomationRuntimeRepositoryError::NotFound
        | AutomationRuntimeRepositoryError::MissingActor
        | AutomationRuntimeRepositoryError::InvalidPayload
        | AutomationRuntimeRepositoryError::InvalidConversation
        | AutomationRuntimeRepositoryError::InvalidRunState
        | AutomationRuntimeRepositoryError::TerminalConflict => {
            CronOperationErrorCode::InvalidOperation
        }
        AutomationRuntimeRepositoryError::LeaseLost
        | AutomationRuntimeRepositoryError::Storage(_) => CronOperationErrorCode::LeaseExpired,
    };
    CronOperationHandlerOutcome::RetryOrDeadLetter(CronOperationHandlerFailure {
        code,
        redacted_text: "automation dispatch validation failed".to_string(),
        retry_after_seconds: 5,
    })
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum AutomationExecutionBoundary {
    Finished,
    AwaitingHuman,
    Failed,
    Interrupted,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct AutomationExecutionResult {
    pub(crate) boundary: AutomationExecutionBoundary,
    pub(crate) event_count: u64,
    pub(crate) execution_time_ms: u64,
}

#[async_trait]
pub(crate) trait AutomationRunExecutor: Send + Sync {
    async fn execute(&self, lease: &AutomationRunLease) -> CoreResult<AutomationExecutionResult>;
}

#[async_trait]
pub(crate) trait AutomationHitlStore: Send + Sync {
    async fn insert_pending(&self, request: &NewHitlRequestRecord) -> CoreResult<bool>;
}

#[async_trait]
impl AutomationHitlStore for PgHitlRequestRepository {
    async fn insert_pending(&self, request: &NewHitlRequestRecord) -> CoreResult<bool> {
        PgHitlRequestRepository::insert_pending(self, request).await
    }
}

pub(crate) struct ReActAutomationRunExecutor {
    engine: Arc<ReActEngine>,
    hitl: Option<Arc<dyn AutomationHitlStore>>,
    tool_hosts: Option<Arc<dyn AutomationToolHostFactory>>,
}

impl ReActAutomationRunExecutor {
    pub(crate) fn new(engine: Arc<ReActEngine>) -> Self {
        Self {
            engine,
            hitl: None,
            tool_hosts: None,
        }
    }

    pub(crate) fn with_hitl_store(mut self, hitl: Arc<dyn AutomationHitlStore>) -> Self {
        self.hitl = Some(hitl);
        self
    }

    pub(crate) fn with_tool_host_factory(
        mut self,
        tool_hosts: Arc<dyn AutomationToolHostFactory>,
    ) -> Self {
        self.tool_hosts = Some(tool_hosts);
        self
    }
}

#[async_trait]
impl AutomationRunExecutor for ReActAutomationRunExecutor {
    async fn execute(&self, lease: &AutomationRunLease) -> CoreResult<AutomationExecutionResult> {
        let started = Instant::now();
        let tools = self
            .tool_hosts
            .as_ref()
            .ok_or_else(|| {
                CoreError::Tool("automation tool authority is not configured".to_string())
            })?
            .for_run(lease)?;
        let engine = self.engine.as_ref().clone().with_tool_host(tools);
        let observer = Arc::new(AutomationHitlObserver {
            store: self.hitl.clone(),
            tenant_id: lease.context.tenant_id.clone(),
            project_id: lease.context.project_id.clone(),
            conversation_id: lease.context.conversation_id.clone(),
            run_id: lease.context.run_id.clone(),
            actor_user_id: lease.context.actor_user_id.clone(),
            expires_at: lease.deadline_at,
        });
        let state = engine
            .run_observed(
                &lease.context.runtime_execution_id,
                &lease.context.payload.goal(),
                Some(&lease.context.project_id),
                observer,
            )
            .await?;
        let boundary = match state.status {
            SessionStatus::Finished => AutomationExecutionBoundary::Finished,
            SessionStatus::AwaitingInput => AutomationExecutionBoundary::AwaitingHuman,
            SessionStatus::Failed => AutomationExecutionBoundary::Failed,
            _ => AutomationExecutionBoundary::Interrupted,
        };
        Ok(AutomationExecutionResult {
            boundary,
            event_count: u64::try_from(state.transcript.len()).unwrap_or(u64::MAX),
            execution_time_ms: u64::try_from(started.elapsed().as_millis()).unwrap_or(u64::MAX),
        })
    }
}

struct AutomationHitlObserver {
    store: Option<Arc<dyn AutomationHitlStore>>,
    tenant_id: String,
    project_id: String,
    conversation_id: String,
    run_id: String,
    actor_user_id: String,
    expires_at: DateTime<Utc>,
}

#[async_trait]
impl ReActObserver for AutomationHitlObserver {
    async fn on_human_request(
        &self,
        session_id: &str,
        _round: u64,
        request: &HitlRequest,
    ) -> CoreResult<()> {
        let request_type = match request.kind {
            HitlKind::Clarification => "clarification",
            HitlKind::Decision => "decision",
            HitlKind::Permission => "permission",
            HitlKind::EnvVar => {
                return Err(CoreError::Tool(
                    "automation env-var HITL requires sealed response support".to_string(),
                ));
            }
        };
        let store = self.store.as_ref().ok_or_else(|| {
            CoreError::Storage("automation HITL persistence is unavailable".to_string())
        })?;
        let request_context = serde_json::to_value(request)
            .map_err(|error| CoreError::Storage(format!("encode automation HITL: {error}")))?;
        let pending = NewHitlRequestRecord {
            id: request.id.clone(),
            request_type: request_type.to_string(),
            conversation_id: self.conversation_id.clone(),
            message_id: Some(self.run_id.clone()),
            tenant_id: self.tenant_id.clone(),
            project_id: self.project_id.clone(),
            user_id: Some(self.actor_user_id.clone()),
            question: request.prompt.clone(),
            options: None,
            context: Some(request_context),
            request_metadata: Some(json!({
                "agent_mode": "default",
                "hitl_type": request_type,
                "automation_run_id": self.run_id,
                "runtime_execution_id": self.run_id,
                "checkpoint_session_id": session_id,
            })),
            expires_at: self.expires_at,
        };
        let _inserted = store.insert_pending(&pending).await?;
        Ok(())
    }
}

#[async_trait]
pub(crate) trait AutomationRuntimeStore: Send + Sync {
    async fn claim_due(
        &self,
        scope: &AutomationRuntimeScope,
        limit: i64,
        lease_owner: &str,
        lease_seconds: i64,
        now: DateTime<Utc>,
    ) -> Result<Vec<AutomationRunLease>, AutomationRuntimeRepositoryError>;

    async fn renew(
        &self,
        lease: &AutomationRunLease,
        lease_seconds: i64,
        now: DateTime<Utc>,
    ) -> CoreResult<bool>;

    async fn mark_waiting_human(
        &self,
        lease: &AutomationRunLease,
        observed_at: DateTime<Utc>,
    ) -> Result<bool, AutomationRuntimeRepositoryError>;

    async fn project_terminal(
        &self,
        lease: &AutomationRunLease,
        result: AutomationExecutionResult,
        outcome: AutomationTerminalOutcome,
        error_code: Option<&str>,
        observed_at: DateTime<Utc>,
    ) -> Result<AutomationTerminalProjection, AutomationRuntimeRepositoryError>;

    async fn recover_expired(
        &self,
        scope: &AutomationRuntimeScope,
        limit: i64,
        now: DateTime<Utc>,
    ) -> Result<usize, AutomationRuntimeRepositoryError>;
}

#[async_trait]
impl AutomationRuntimeStore for PgCronAutomationRuntimeRepository {
    async fn claim_due(
        &self,
        scope: &AutomationRuntimeScope,
        limit: i64,
        lease_owner: &str,
        lease_seconds: i64,
        now: DateTime<Utc>,
    ) -> Result<Vec<AutomationRunLease>, AutomationRuntimeRepositoryError> {
        PgCronAutomationRuntimeRepository::claim_due(
            self,
            scope,
            limit,
            lease_owner,
            lease_seconds,
            now,
        )
        .await
    }

    async fn renew(
        &self,
        lease: &AutomationRunLease,
        lease_seconds: i64,
        now: DateTime<Utc>,
    ) -> CoreResult<bool> {
        PgCronAutomationRuntimeRepository::renew(self, lease, lease_seconds, now).await
    }

    async fn mark_waiting_human(
        &self,
        lease: &AutomationRunLease,
        observed_at: DateTime<Utc>,
    ) -> Result<bool, AutomationRuntimeRepositoryError> {
        PgCronAutomationRuntimeRepository::mark_waiting_human(self, lease, observed_at).await
    }

    async fn project_terminal(
        &self,
        lease: &AutomationRunLease,
        result: AutomationExecutionResult,
        outcome: AutomationTerminalOutcome,
        error_code: Option<&str>,
        observed_at: DateTime<Utc>,
    ) -> Result<AutomationTerminalProjection, AutomationRuntimeRepositoryError> {
        PgCronAutomationRuntimeRepository::project_terminal(
            self,
            lease,
            outcome,
            error_code,
            result.event_count,
            result.execution_time_ms,
            observed_at,
        )
        .await
    }

    async fn recover_expired(
        &self,
        scope: &AutomationRuntimeScope,
        limit: i64,
        now: DateTime<Utc>,
    ) -> Result<usize, AutomationRuntimeRepositoryError> {
        PgCronAutomationRuntimeRepository::recover_expired(self, scope, limit, now).await
    }
}

#[derive(Debug, Clone)]
pub(crate) struct AutomationRuntimeWorkerConfig {
    pub(crate) worker_id: String,
    pub(crate) batch_size: i64,
    pub(crate) lease_seconds: i64,
    pub(crate) heartbeat_interval: Duration,
}

impl Default for AutomationRuntimeWorkerConfig {
    fn default() -> Self {
        Self {
            worker_id: "agistack-cron-runtime-disabled".to_string(),
            batch_size: 1,
            lease_seconds: 60,
            heartbeat_interval: Duration::from_secs(15),
        }
    }
}

#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub(crate) struct AutomationRuntimeDrainReport {
    pub(crate) recovered_timeouts: usize,
    pub(crate) claimed: usize,
    pub(crate) succeeded: usize,
    pub(crate) waiting_human: usize,
    pub(crate) failed: usize,
    pub(crate) interrupted: usize,
    pub(crate) timed_out: usize,
    pub(crate) lost_lease: usize,
}

pub(crate) struct CronAutomationRuntimeWorker {
    store: Arc<dyn AutomationRuntimeStore>,
    executor: Arc<dyn AutomationRunExecutor>,
    config: AutomationRuntimeWorkerConfig,
}

impl CronAutomationRuntimeWorker {
    pub(crate) fn new(
        store: Arc<dyn AutomationRuntimeStore>,
        executor: Arc<dyn AutomationRunExecutor>,
        config: AutomationRuntimeWorkerConfig,
    ) -> Self {
        Self {
            store,
            executor,
            config,
        }
    }

    pub(crate) async fn drain_once(
        &self,
        scope: &AutomationRuntimeScope,
        now: DateTime<Utc>,
    ) -> Result<AutomationRuntimeDrainReport, AutomationRuntimeRepositoryError> {
        let recovered_timeouts = self
            .store
            .recover_expired(scope, self.config.batch_size, now)
            .await?;
        let leases = self
            .store
            .claim_due(
                scope,
                self.config.batch_size,
                &self.config.worker_id,
                self.config.lease_seconds,
                now,
            )
            .await?;
        let mut report = AutomationRuntimeDrainReport {
            recovered_timeouts,
            claimed: leases.len(),
            ..Default::default()
        };
        for lease in leases {
            self.drive_lease(&lease, now, &mut report).await?;
        }
        Ok(report)
    }

    async fn drive_lease(
        &self,
        lease: &AutomationRunLease,
        claimed_at: DateTime<Utc>,
        report: &mut AutomationRuntimeDrainReport,
    ) -> Result<(), AutomationRuntimeRepositoryError> {
        if lease.deadline_at <= claimed_at {
            let result = AutomationExecutionResult {
                boundary: AutomationExecutionBoundary::Interrupted,
                event_count: 0,
                execution_time_ms: 0,
            };
            self.project(
                result,
                lease,
                AutomationTerminalOutcome::Timeout,
                claimed_at,
            )
            .await?;
            report.timed_out += 1;
            return Ok(());
        }

        let execution = self.executor.execute(lease);
        tokio::pin!(execution);
        let remaining = (lease.deadline_at - claimed_at)
            .to_std()
            .unwrap_or(Duration::ZERO);
        let deadline = sleep(remaining);
        tokio::pin!(deadline);
        let heartbeat_duration = self.config.heartbeat_interval.max(Duration::from_millis(1));
        let mut heartbeat = interval(heartbeat_duration);
        heartbeat.tick().await;

        let result = loop {
            tokio::select! {
                result = &mut execution => break Some(result),
                _ = &mut deadline => break None,
                _ = heartbeat.tick() => {
                    let renewed = self.store
                        .renew(lease, self.config.lease_seconds, Utc::now())
                        .await
                        .map_err(|error| AutomationRuntimeRepositoryError::Storage(error.to_string()))?;
                    if !renewed {
                        report.lost_lease += 1;
                        return Ok(());
                    }
                }
            }
        };

        let observed_at = Utc::now();
        let Some(result) = result else {
            let timeout_result = AutomationExecutionResult {
                boundary: AutomationExecutionBoundary::Interrupted,
                event_count: 0,
                execution_time_ms: u64::try_from(remaining.as_millis()).unwrap_or(u64::MAX),
            };
            self.project(
                timeout_result,
                lease,
                AutomationTerminalOutcome::Timeout,
                observed_at,
            )
            .await?;
            report.timed_out += 1;
            return Ok(());
        };

        let result = match result {
            Ok(result) => result,
            Err(_) => AutomationExecutionResult {
                boundary: AutomationExecutionBoundary::Failed,
                event_count: 0,
                execution_time_ms: 0,
            },
        };
        match result.boundary {
            AutomationExecutionBoundary::Finished => {
                self.project(
                    result,
                    lease,
                    AutomationTerminalOutcome::Success,
                    observed_at,
                )
                .await?;
                report.succeeded += 1;
            }
            AutomationExecutionBoundary::AwaitingHuman => {
                if self.store.mark_waiting_human(lease, observed_at).await? {
                    report.waiting_human += 1;
                } else {
                    report.lost_lease += 1;
                }
            }
            AutomationExecutionBoundary::Failed => {
                self.project(
                    result,
                    lease,
                    AutomationTerminalOutcome::Failed,
                    observed_at,
                )
                .await?;
                report.failed += 1;
            }
            AutomationExecutionBoundary::Interrupted => {
                self.project(
                    result,
                    lease,
                    AutomationTerminalOutcome::Failed,
                    observed_at,
                )
                .await?;
                report.interrupted += 1;
            }
        }
        Ok(())
    }

    async fn project(
        &self,
        result: AutomationExecutionResult,
        lease: &AutomationRunLease,
        outcome: AutomationTerminalOutcome,
        observed_at: DateTime<Utc>,
    ) -> Result<(), AutomationRuntimeRepositoryError> {
        let error_code = match outcome {
            AutomationTerminalOutcome::Success => None,
            AutomationTerminalOutcome::Timeout => Some("execution_timed_out"),
            AutomationTerminalOutcome::Cancelled => Some("cancelled"),
            AutomationTerminalOutcome::Failed => Some("execution_failed"),
        };
        let projection = self
            .store
            .project_terminal(lease, result, outcome, error_code, observed_at)
            .await?;
        if !projection.matched {
            return Err(AutomationRuntimeRepositoryError::LeaseLost);
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests;
