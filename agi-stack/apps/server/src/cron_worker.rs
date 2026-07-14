//! Fail-closed core for draining durable cron operations.
//!
//! This module is intentionally not wired into [`crate::AppState`], startup,
//! routes, or capability reporting. It has no spawn loop and reads no environment
//! variables. Even a direct [`CronOperationWorker::drain_once`] call must pass
//! the autostart, production-readiness, and handler-readiness gates before the
//! store can claim work. An exact, current scheduler ownership lease is also
//! required and is rechecked atomically by the PostgreSQL claim.

#![allow(dead_code)]

use std::sync::Arc;

use agistack_adapters_postgres::{
    CronOperationErrorCode, CronOperationKind, CronOperationRecord, CronOperationStatus,
    CronSchedulerLease,
};
use agistack_core::ports::{CoreError, CoreResult};
use async_trait::async_trait;
use chrono::{DateTime, Utc};
use serde_json::Value;

use crate::cron_scheduler_ownership::CronSchedulerOwnershipStore;

mod pg_store;
mod processor;

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct CronWorkerScope {
    pub(crate) tenant_id: String,
    pub(crate) project_id: String,
}

/// Explicit gates for the dormant worker foundation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct CronWorkerConfig {
    pub(crate) worker_id: String,
    pub(crate) batch_size: i64,
    pub(crate) lease_seconds: i64,
    pub(crate) autostart: bool,
    pub(crate) production_ready: bool,
    pub(crate) handlers_ready: bool,
}

impl Default for CronWorkerConfig {
    fn default() -> Self {
        Self {
            worker_id: "agistack-cron-worker-disabled".to_string(),
            batch_size: 1,
            lease_seconds: 60,
            autostart: false,
            production_ready: false,
            handlers_ready: false,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum CronWorkerGate {
    Open,
    AutostartDisabled,
    ProductionNotReady,
    HandlersNotReady,
    SchedulerAuthorityNotCurrent,
}

#[derive(Debug, Clone, PartialEq)]
pub(crate) struct CronOperationHandlerFailure {
    pub(crate) code: CronOperationErrorCode,
    pub(crate) redacted_text: String,
    pub(crate) retry_after_seconds: i64,
}

/// Handler output is typed; worker policy never classifies free-form text.
#[derive(Debug, Clone, PartialEq)]
pub(crate) enum CronOperationHandlerOutcome {
    Accepted { dispatch_json: Value },
    Complete { result_json: Value },
    RetryOrDeadLetter(CronOperationHandlerFailure),
}

#[async_trait]
pub(crate) trait CronOperationHandler: Send + Sync {
    fn kind(&self) -> CronOperationKind;

    async fn handle(
        &self,
        operation: &CronOperationRecord,
    ) -> CoreResult<CronOperationHandlerOutcome>;
}

#[async_trait]
pub(crate) trait CronOperationStore: Send + Sync {
    async fn claim_due(
        &self,
        scope: &CronWorkerScope,
        authority: &CronSchedulerLease,
        limit: i64,
        lease_owner: &str,
        lease_seconds: i64,
        now: DateTime<Utc>,
    ) -> CoreResult<Vec<CronOperationRecord>>;

    async fn complete(
        &self,
        scope: &CronWorkerScope,
        operation_id: &str,
        lease_owner: &str,
        lease_token: &str,
        result_json: &Value,
        now: DateTime<Utc>,
    ) -> CoreResult<bool>;

    async fn mark_waiting_runtime(
        &self,
        scope: &CronWorkerScope,
        operation_id: &str,
        lease_owner: &str,
        lease_token: &str,
        dispatch_json: &Value,
        now: DateTime<Utc>,
    ) -> CoreResult<Option<CronOperationStatus>>;

    async fn fail(
        &self,
        scope: &CronWorkerScope,
        operation_id: &str,
        lease_owner: &str,
        lease_token: &str,
        failure: &CronOperationHandlerFailure,
        now: DateTime<Utc>,
    ) -> CoreResult<Option<CronOperationStatus>>;
}

pub(crate) trait CronWorkerClock: Send + Sync {
    fn now(&self) -> DateTime<Utc>;
}

#[derive(Debug, Default)]
pub(crate) struct UtcCronWorkerClock;

impl CronWorkerClock for UtcCronWorkerClock {
    fn now(&self) -> DateTime<Utc> {
        Utc::now()
    }
}

#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub(crate) struct CronWorkerDrainReport {
    pub(crate) gate: Option<CronWorkerGate>,
    pub(crate) claimed: usize,
    pub(crate) waiting_runtime: usize,
    pub(crate) completed: usize,
    pub(crate) retry_scheduled: usize,
    pub(crate) dead_lettered: usize,
    pub(crate) lost_lease: usize,
    pub(crate) handler_errors: usize,
}

pub(crate) struct CronOperationWorker {
    store: Arc<dyn CronOperationStore>,
    ownership: Arc<dyn CronSchedulerOwnershipStore>,
    clock: Arc<dyn CronWorkerClock>,
    scope: CronWorkerScope,
    config: CronWorkerConfig,
    handlers: Vec<Arc<dyn CronOperationHandler>>,
}

impl CronOperationWorker {
    pub(crate) fn new(
        store: Arc<dyn CronOperationStore>,
        ownership: Arc<dyn CronSchedulerOwnershipStore>,
        clock: Arc<dyn CronWorkerClock>,
        scope: CronWorkerScope,
        config: CronWorkerConfig,
        handlers: Vec<Arc<dyn CronOperationHandler>>,
    ) -> Self {
        Self {
            store,
            ownership,
            clock,
            scope,
            config,
            handlers,
        }
    }

    pub(crate) fn gate(&self) -> CronWorkerGate {
        if !self.config.autostart {
            return CronWorkerGate::AutostartDisabled;
        }
        if !self.config.production_ready {
            return CronWorkerGate::ProductionNotReady;
        }
        if !self.config.handlers_ready || !self.has_required_handlers() {
            return CronWorkerGate::HandlersNotReady;
        }
        CronWorkerGate::Open
    }

    /// Drain one bounded batch. A closed gate returns without touching the store.
    pub(crate) async fn drain_once(
        &self,
        authority: &CronSchedulerLease,
    ) -> CoreResult<CronWorkerDrainReport> {
        let gate = self.gate();
        if gate != CronWorkerGate::Open {
            return Ok(CronWorkerDrainReport {
                gate: Some(gate),
                ..Default::default()
            });
        }

        let observed_at = self.clock.now();
        let authority_is_current = authority.is_structurally_valid()
            && authority.lease_expires_at > observed_at
            && self
                .ownership
                .is_current(authority, observed_at)
                .await
                .map_err(|_| {
                    CoreError::Storage("cron scheduler ownership check failed".to_string())
                })?;
        if !authority_is_current {
            return Ok(CronWorkerDrainReport {
                gate: Some(CronWorkerGate::SchedulerAuthorityNotCurrent),
                ..Default::default()
            });
        }

        let claimed = self
            .store
            .claim_due(
                &self.scope,
                authority,
                self.config.batch_size.max(1),
                &self.config.worker_id,
                self.config.lease_seconds.max(1),
                observed_at,
            )
            .await?;
        let mut report = CronWorkerDrainReport {
            claimed: claimed.len(),
            ..Default::default()
        };
        for operation in claimed {
            self.process_operation(&operation, &mut report).await?;
        }
        Ok(report)
    }

    fn has_required_handlers(&self) -> bool {
        [
            CronOperationKind::ReconcileSchedule,
            CronOperationKind::ExecuteRun,
        ]
        .into_iter()
        .all(|kind| self.handler(kind).is_some())
    }

    fn handler(&self, kind: CronOperationKind) -> Option<&Arc<dyn CronOperationHandler>> {
        self.handlers.iter().find(|handler| handler.kind() == kind)
    }
}

fn valid_claim_lease<'a>(operation: &'a CronOperationRecord, worker_id: &str) -> Option<&'a str> {
    if operation.lease_owner.as_deref() != Some(worker_id) {
        return None;
    }
    operation
        .lease_token
        .as_deref()
        .filter(|token| !token.is_empty())
}

#[cfg(test)]
mod tests {
    use std::sync::Mutex;

    use agistack_adapters_postgres::CronSchedulerOwnerError;
    use serde_json::json;

    use super::*;

    #[derive(Debug)]
    struct FixedClock(DateTime<Utc>);

    impl CronWorkerClock for FixedClock {
        fn now(&self) -> DateTime<Utc> {
            self.0
        }
    }

    #[derive(Debug)]
    struct FakeOwnership {
        current: bool,
        checks: Mutex<usize>,
    }

    #[async_trait]
    impl CronSchedulerOwnershipStore for FakeOwnership {
        async fn is_current(
            &self,
            _lease: &CronSchedulerLease,
            _now: DateTime<Utc>,
        ) -> Result<bool, CronSchedulerOwnerError> {
            *self.checks.lock().expect("ownership checks lock") += 1;
            Ok(self.current)
        }
    }

    #[derive(Debug, Default)]
    struct FakeStoreState {
        claims: usize,
        claimed: Vec<CronOperationRecord>,
        complete_calls: usize,
        complete_result: bool,
        waiting_runtime_calls: usize,
        waiting_runtime_result: Option<CronOperationStatus>,
        fail_calls: usize,
        fail_result: Option<CronOperationStatus>,
        last_failure_code: Option<CronOperationErrorCode>,
    }

    #[derive(Debug, Default)]
    struct FakeStore {
        state: Mutex<FakeStoreState>,
    }

    impl FakeStore {
        fn with_claimed(operation: CronOperationRecord) -> Arc<Self> {
            Arc::new(Self {
                state: Mutex::new(FakeStoreState {
                    claimed: vec![operation],
                    complete_result: true,
                    waiting_runtime_result: Some(CronOperationStatus::WaitingRuntime),
                    ..Default::default()
                }),
            })
        }

        fn snapshot(&self) -> FakeStoreState {
            let state = self.state.lock().expect("fake store lock");
            FakeStoreState {
                claims: state.claims,
                complete_calls: state.complete_calls,
                complete_result: state.complete_result,
                waiting_runtime_calls: state.waiting_runtime_calls,
                waiting_runtime_result: state.waiting_runtime_result,
                fail_calls: state.fail_calls,
                fail_result: state.fail_result,
                last_failure_code: state.last_failure_code,
                ..Default::default()
            }
        }
    }

    #[async_trait]
    impl CronOperationStore for FakeStore {
        async fn claim_due(
            &self,
            _scope: &CronWorkerScope,
            _authority: &CronSchedulerLease,
            _limit: i64,
            _lease_owner: &str,
            _lease_seconds: i64,
            _now: DateTime<Utc>,
        ) -> CoreResult<Vec<CronOperationRecord>> {
            let mut state = self.state.lock().expect("fake store lock");
            state.claims += 1;
            Ok(std::mem::take(&mut state.claimed))
        }

        async fn complete(
            &self,
            _scope: &CronWorkerScope,
            _operation_id: &str,
            _lease_owner: &str,
            _lease_token: &str,
            _result_json: &Value,
            _now: DateTime<Utc>,
        ) -> CoreResult<bool> {
            let mut state = self.state.lock().expect("fake store lock");
            state.complete_calls += 1;
            Ok(state.complete_result)
        }

        async fn mark_waiting_runtime(
            &self,
            _scope: &CronWorkerScope,
            _operation_id: &str,
            _lease_owner: &str,
            _lease_token: &str,
            _dispatch_json: &Value,
            _now: DateTime<Utc>,
        ) -> CoreResult<Option<CronOperationStatus>> {
            let mut state = self.state.lock().expect("fake store lock");
            state.waiting_runtime_calls += 1;
            Ok(state.waiting_runtime_result)
        }

        async fn fail(
            &self,
            _scope: &CronWorkerScope,
            _operation_id: &str,
            _lease_owner: &str,
            _lease_token: &str,
            failure: &CronOperationHandlerFailure,
            _now: DateTime<Utc>,
        ) -> CoreResult<Option<CronOperationStatus>> {
            let mut state = self.state.lock().expect("fake store lock");
            state.fail_calls += 1;
            state.last_failure_code = Some(failure.code);
            Ok(state.fail_result)
        }
    }

    #[derive(Debug)]
    struct FakeHandler {
        kind: CronOperationKind,
        outcome: CronOperationHandlerOutcome,
        calls: Mutex<usize>,
    }

    #[async_trait]
    impl CronOperationHandler for FakeHandler {
        fn kind(&self) -> CronOperationKind {
            self.kind
        }

        async fn handle(
            &self,
            _operation: &CronOperationRecord,
        ) -> CoreResult<CronOperationHandlerOutcome> {
            *self.calls.lock().expect("fake handler lock") += 1;
            Ok(self.outcome.clone())
        }
    }

    fn now() -> DateTime<Utc> {
        DateTime::parse_from_rfc3339("2026-07-14T10:00:00Z")
            .expect("fixed time")
            .with_timezone(&Utc)
    }

    fn authority() -> CronSchedulerLease {
        CronSchedulerLease {
            scope_id: "global".to_string(),
            owner_id: "scheduler-1".to_string(),
            owner_epoch: 1,
            lease_token: "global:1:test".to_string(),
            lease_expires_at: now() + chrono::Duration::seconds(60),
            acquired_at: now() - chrono::Duration::seconds(1),
        }
    }

    fn operation(kind: CronOperationKind) -> CronOperationRecord {
        CronOperationRecord {
            id: "operation-1".to_string(),
            tenant_id: "tenant-1".to_string(),
            project_id: "project-1".to_string(),
            job_id: "job-1".to_string(),
            job_revision: 1,
            schedule_revision: Some(1),
            kind,
            run_id: Some("run-1".to_string()),
            trigger_type: Some("manual".to_string()),
            scheduled_for: None,
            input_json: json!({}),
            status: CronOperationStatus::Processing,
            attempt_count: 1,
            max_attempts: 3,
            next_attempt_at: None,
            lease_owner: Some("worker-1".to_string()),
            lease_token: Some("lease-1".to_string()),
            lease_expires_at: Some(now()),
            actor_user_id: Some("user-1".to_string()),
            actor_api_key_id: None,
            request_receipt_id: None,
            last_error_code: None,
            last_error_redacted: None,
            result_json: json!({}),
            created_at: now(),
            updated_at: now(),
            started_at: Some(now()),
            completed_at: None,
        }
    }

    fn handler(kind: CronOperationKind, outcome: CronOperationHandlerOutcome) -> Arc<FakeHandler> {
        Arc::new(FakeHandler {
            kind,
            outcome,
            calls: Mutex::new(0),
        })
    }

    fn ready_config() -> CronWorkerConfig {
        CronWorkerConfig {
            worker_id: "worker-1".to_string(),
            batch_size: 10,
            lease_seconds: 60,
            autostart: true,
            production_ready: true,
            handlers_ready: true,
        }
    }

    fn worker(
        store: Arc<FakeStore>,
        config: CronWorkerConfig,
        execute_handler: Arc<dyn CronOperationHandler>,
    ) -> CronOperationWorker {
        worker_with_ownership(
            store,
            Arc::new(FakeOwnership {
                current: true,
                checks: Mutex::new(0),
            }),
            config,
            execute_handler,
        )
    }

    fn worker_with_ownership(
        store: Arc<FakeStore>,
        ownership: Arc<dyn CronSchedulerOwnershipStore>,
        config: CronWorkerConfig,
        execute_handler: Arc<dyn CronOperationHandler>,
    ) -> CronOperationWorker {
        let reconcile_handler = handler(
            CronOperationKind::ReconcileSchedule,
            CronOperationHandlerOutcome::Complete {
                result_json: json!({"reconciled": true}),
            },
        );
        CronOperationWorker::new(
            store,
            ownership,
            Arc::new(FixedClock(now())),
            CronWorkerScope {
                tenant_id: "tenant-1".to_string(),
                project_id: "project-1".to_string(),
            },
            config,
            vec![reconcile_handler, execute_handler],
        )
    }

    #[tokio::test]
    async fn triple_gate_blocks_claim_until_every_readiness_flag_is_open() {
        let execute_handler = handler(
            CronOperationKind::ExecuteRun,
            CronOperationHandlerOutcome::Accepted {
                dispatch_json: json!({}),
            },
        );
        let cases = [
            (
                CronWorkerConfig::default(),
                CronWorkerGate::AutostartDisabled,
            ),
            (
                CronWorkerConfig {
                    autostart: true,
                    ..Default::default()
                },
                CronWorkerGate::ProductionNotReady,
            ),
            (
                CronWorkerConfig {
                    autostart: true,
                    production_ready: true,
                    ..Default::default()
                },
                CronWorkerGate::HandlersNotReady,
            ),
        ];

        for (config, expected_gate) in cases {
            let store = Arc::new(FakeStore::default());
            let report = worker(store.clone(), config, execute_handler.clone())
                .drain_once(&authority())
                .await
                .expect("closed gate is not an error");
            assert_eq!(report.gate, Some(expected_gate));
            assert_eq!(store.snapshot().claims, 0);
        }
    }

    #[tokio::test]
    async fn stale_scheduler_authority_blocks_operation_claim() {
        let store = Arc::new(FakeStore::default());
        let ownership = Arc::new(FakeOwnership {
            current: false,
            checks: Mutex::new(0),
        });
        let execute_handler = handler(
            CronOperationKind::ExecuteRun,
            CronOperationHandlerOutcome::Accepted {
                dispatch_json: json!({}),
            },
        );

        let report = worker_with_ownership(
            store.clone(),
            ownership.clone(),
            ready_config(),
            execute_handler,
        )
        .drain_once(&authority())
        .await
        .expect("stale authority closes the worker gate");

        assert_eq!(
            report.gate,
            Some(CronWorkerGate::SchedulerAuthorityNotCurrent)
        );
        assert_eq!(store.snapshot().claims, 0);
        assert_eq!(*ownership.checks.lock().expect("ownership checks lock"), 1);
    }

    #[tokio::test]
    async fn accepted_execute_run_waits_for_runtime_under_the_claimed_lease() {
        let store = FakeStore::with_claimed(operation(CronOperationKind::ExecuteRun));
        let execute_handler = handler(
            CronOperationKind::ExecuteRun,
            CronOperationHandlerOutcome::Accepted {
                dispatch_json: json!({"message_id": "run-1"}),
            },
        );

        let report = worker(store.clone(), ready_config(), execute_handler)
            .drain_once(&authority())
            .await
            .expect("drain succeeds");

        assert_eq!(report.claimed, 1);
        assert_eq!(report.waiting_runtime, 1);
        assert_eq!(report.completed, 0);
        assert_eq!(report.lost_lease, 0);
        assert_eq!(store.snapshot().waiting_runtime_calls, 1);
        assert_eq!(store.snapshot().complete_calls, 0);
    }

    #[tokio::test]
    async fn reconcile_schedule_may_complete_under_the_claimed_lease() {
        let store = FakeStore::with_claimed(operation(CronOperationKind::ReconcileSchedule));
        let execute_handler = handler(
            CronOperationKind::ExecuteRun,
            CronOperationHandlerOutcome::Accepted {
                dispatch_json: json!({}),
            },
        );

        let report = worker(store.clone(), ready_config(), execute_handler)
            .drain_once(&authority())
            .await
            .expect("drain succeeds");

        assert_eq!(report.completed, 1);
        assert_eq!(report.waiting_runtime, 0);
        assert_eq!(store.snapshot().complete_calls, 1);
        assert_eq!(store.snapshot().waiting_runtime_calls, 0);
    }

    #[tokio::test]
    async fn typed_failure_delegates_retry_or_dead_letter_to_the_store() {
        for (status, retries, dead_letters) in [
            (CronOperationStatus::Failed, 1, 0),
            (CronOperationStatus::DeadLetter, 0, 1),
        ] {
            let store = FakeStore::with_claimed(operation(CronOperationKind::ExecuteRun));
            store.state.lock().expect("fake store lock").fail_result = Some(status);
            let execute_handler = handler(
                CronOperationKind::ExecuteRun,
                CronOperationHandlerOutcome::RetryOrDeadLetter(CronOperationHandlerFailure {
                    code: CronOperationErrorCode::ExecutionTimedOut,
                    redacted_text: "execution timed out".to_string(),
                    retry_after_seconds: 30,
                }),
            );

            let report = worker(store.clone(), ready_config(), execute_handler)
                .drain_once(&authority())
                .await
                .expect("drain succeeds");

            assert_eq!(report.retry_scheduled, retries);
            assert_eq!(report.dead_lettered, dead_letters);
            assert_eq!(store.snapshot().fail_calls, 1);
            assert_eq!(
                store.snapshot().last_failure_code,
                Some(CronOperationErrorCode::ExecutionTimedOut)
            );
        }
    }

    #[tokio::test]
    async fn wrong_claim_owner_never_calls_handler_or_terminal_store_methods() {
        let mut claimed = operation(CronOperationKind::ExecuteRun);
        claimed.lease_owner = Some("other-worker".to_string());
        let store = FakeStore::with_claimed(claimed);
        let execute_handler = handler(
            CronOperationKind::ExecuteRun,
            CronOperationHandlerOutcome::Accepted {
                dispatch_json: json!({}),
            },
        );

        let report = worker(store.clone(), ready_config(), execute_handler.clone())
            .drain_once(&authority())
            .await
            .expect("drain succeeds");

        assert_eq!(report.lost_lease, 1);
        assert_eq!(*execute_handler.calls.lock().expect("handler lock"), 0);
        assert_eq!(store.snapshot().complete_calls, 0);
        assert_eq!(store.snapshot().fail_calls, 0);
    }

    #[tokio::test]
    async fn lost_lease_after_dispatch_acceptance_is_reported_without_completion() {
        let store = FakeStore::with_claimed(operation(CronOperationKind::ExecuteRun));
        store
            .state
            .lock()
            .expect("fake store lock")
            .waiting_runtime_result = None;
        let execute_handler = handler(
            CronOperationKind::ExecuteRun,
            CronOperationHandlerOutcome::Accepted {
                dispatch_json: json!({}),
            },
        );

        let report = worker(store.clone(), ready_config(), execute_handler)
            .drain_once(&authority())
            .await
            .expect("drain succeeds");

        assert_eq!(report.completed, 0);
        assert_eq!(report.waiting_runtime, 0);
        assert_eq!(report.lost_lease, 1);
        assert_eq!(store.snapshot().waiting_runtime_calls, 1);
        assert_eq!(store.snapshot().complete_calls, 0);
        assert_eq!(store.snapshot().fail_calls, 0);
    }

    #[tokio::test]
    async fn execute_run_completion_outcome_is_rejected_as_non_terminal_dispatch() {
        let store = FakeStore::with_claimed(operation(CronOperationKind::ExecuteRun));
        let execute_handler = handler(
            CronOperationKind::ExecuteRun,
            CronOperationHandlerOutcome::Complete {
                result_json: json!({"answer": "premature"}),
            },
        );

        let error = worker(store.clone(), ready_config(), execute_handler)
            .drain_once(&authority())
            .await
            .expect_err("dispatch acceptance cannot complete an execute operation");

        assert!(error.to_string().contains("incompatible kind execute_run"));
        assert_eq!(store.snapshot().waiting_runtime_calls, 0);
        assert_eq!(store.snapshot().complete_calls, 0);
        assert_eq!(store.snapshot().fail_calls, 0);
    }

    #[tokio::test]
    async fn terminal_run_observed_during_dispatch_ack_completes_without_waiting() {
        let store = FakeStore::with_claimed(operation(CronOperationKind::ExecuteRun));
        store
            .state
            .lock()
            .expect("fake store lock")
            .waiting_runtime_result = Some(CronOperationStatus::Completed);
        let execute_handler = handler(
            CronOperationKind::ExecuteRun,
            CronOperationHandlerOutcome::Accepted {
                dispatch_json: json!({"message_id": "run-1"}),
            },
        );

        let report = worker(store.clone(), ready_config(), execute_handler)
            .drain_once(&authority())
            .await
            .expect("drain succeeds");

        assert_eq!(report.completed, 1);
        assert_eq!(report.waiting_runtime, 0);
        assert_eq!(report.lost_lease, 0);
        assert_eq!(store.snapshot().waiting_runtime_calls, 1);
        assert_eq!(store.snapshot().complete_calls, 0);
    }
}
