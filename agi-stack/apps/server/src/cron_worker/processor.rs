//! Typed outcome projection for claimed cron operations.

use super::*;

impl CronOperationWorker {
    pub(super) async fn process_operation(
        &self,
        operation: &CronOperationRecord,
        report: &mut CronWorkerDrainReport,
    ) -> CoreResult<()> {
        let Some(lease_token) = valid_claim_lease(operation, &self.config.worker_id) else {
            report.lost_lease += 1;
            return Ok(());
        };
        let Some(handler) = self.handler(operation.kind) else {
            // Coverage was checked before claim. If it changes unexpectedly, do
            // not write an untyped failure; let the lease expire and be fenced.
            report.handler_errors += 1;
            return Ok(());
        };

        let outcome = match handler.handle(operation).await {
            Ok(outcome) => outcome,
            Err(_) => {
                // Infrastructure errors are not classified from their text.
                // Leaving the operation leased makes the repository's typed
                // lease-expiry/retry policy the only recovery path.
                report.handler_errors += 1;
                return Ok(());
            }
        };

        match (operation.kind, outcome) {
            (
                CronOperationKind::ExecuteRun,
                CronOperationHandlerOutcome::Accepted { dispatch_json },
            ) => {
                let status = self
                    .store
                    .mark_waiting_runtime(
                        &self.scope,
                        &operation.id,
                        &self.config.worker_id,
                        lease_token,
                        &dispatch_json,
                        self.clock.now(),
                    )
                    .await?;
                match status {
                    Some(CronOperationStatus::WaitingRuntime) => report.waiting_runtime += 1,
                    Some(CronOperationStatus::Completed) => report.completed += 1,
                    None => report.lost_lease += 1,
                    Some(other) => {
                        return Err(CoreError::Storage(format!(
                            "cron operation dispatch returned invalid status: {}",
                            other.as_str()
                        )))
                    }
                }
            }
            (
                CronOperationKind::ReconcileSchedule,
                CronOperationHandlerOutcome::Complete { result_json },
            ) => {
                let completed = self
                    .store
                    .complete(
                        &self.scope,
                        &operation.id,
                        &self.config.worker_id,
                        lease_token,
                        &result_json,
                        self.clock.now(),
                    )
                    .await?;
                if completed {
                    report.completed += 1;
                } else {
                    report.lost_lease += 1;
                }
            }
            (_, CronOperationHandlerOutcome::RetryOrDeadLetter(failure)) => {
                let status = self
                    .store
                    .fail(
                        &self.scope,
                        &operation.id,
                        &self.config.worker_id,
                        lease_token,
                        &failure,
                        self.clock.now(),
                    )
                    .await?;
                match status {
                    Some(CronOperationStatus::Failed) => report.retry_scheduled += 1,
                    Some(CronOperationStatus::DeadLetter) => report.dead_lettered += 1,
                    None => report.lost_lease += 1,
                    Some(other) => {
                        return Err(CoreError::Storage(format!(
                            "cron operation fail returned invalid status: {}",
                            other.as_str()
                        )))
                    }
                }
            }
            (kind, invalid_outcome) => {
                let outcome = match invalid_outcome {
                    CronOperationHandlerOutcome::Accepted { .. } => "accepted",
                    CronOperationHandlerOutcome::Complete { .. } => "complete",
                    CronOperationHandlerOutcome::RetryOrDeadLetter(_) => unreachable!(),
                };
                return Err(CoreError::Storage(format!(
                    "cron operation handler returned {outcome} for incompatible kind {}",
                    kind.as_str()
                )));
            }
        }
        Ok(())
    }
}
