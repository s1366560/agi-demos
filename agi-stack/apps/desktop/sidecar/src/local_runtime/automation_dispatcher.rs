use std::time::Duration;

use chrono::{DateTime, Utc};
use rusqlite::{params, OptionalExtension, TransactionBehavior};
use serde::Serialize;
use serde_json::{json, Value};
use uuid::Uuid;

#[cfg(test)]
use super::automation_dispatcher_schema::recover_connection;
use super::automation_dispatcher_schema::recover_transaction;
pub(super) use super::{
    automation_dispatcher_schema::initialize_schema,
    automation_schedule_dispatcher::dispatch_due_schedules,
};
use super::{
    automation_ledger_support::{
        deadline_at, invalid_record, read_job, replay_receipt, required_string, required_u64,
        storage,
    },
    session_store::DesktopSessionStore,
};

const EXECUTION_UNAVAILABLE_REASON: &str = "local_automation_execution_runtime_unavailable";

pub(super) trait AutomationClock: Send + Sync {
    fn now(&self) -> DateTime<Utc>;
}

pub(super) struct SystemAutomationClock;

impl AutomationClock for SystemAutomationClock {
    fn now(&self) -> DateTime<Utc> {
        Utc::now()
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum AutomationRunStatus {
    Queued,
    Running,
    WaitingHuman,
    Success,
    Failed,
    Timeout,
    Cancelled,
}

// These transitions are the tested fencing seam for a future bounded worker. Production keeps
// execution disabled until a real Agent runtime authority owns that worker.
#[cfg_attr(not(test), allow(dead_code))]
impl AutomationRunStatus {
    fn as_str(self) -> &'static str {
        match self {
            Self::Queued => "queued",
            Self::Running => "running",
            Self::WaitingHuman => "waiting_human",
            Self::Success => "success",
            Self::Failed => "failed",
            Self::Timeout => "timeout",
            Self::Cancelled => "cancelled",
        }
    }

    fn is_terminal(self) -> bool {
        matches!(
            self,
            Self::Success | Self::Failed | Self::Timeout | Self::Cancelled
        )
    }
}

#[derive(Clone, Copy)]
pub(super) struct ManualRunCommand<'a> {
    pub(super) user_id: &'a str,
    pub(super) project_id: &'a str,
    pub(super) job_id: &'a str,
    pub(super) expected_revision: u64,
    pub(super) idempotency_key: &'a str,
    pub(super) request_hash: &'a str,
    pub(super) conversation_id: Option<&'a str>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub(super) struct AutomationRunReceipt {
    pub(super) receipt_id: String,
    pub(super) run_id: String,
    pub(super) job_id: String,
    pub(super) status: AutomationRunStatus,
    pub(super) duplicate: bool,
}

#[derive(Clone, Debug, PartialEq, Eq)]
#[cfg_attr(not(test), allow(dead_code))]
pub(super) struct AutomationOperationClaim {
    pub(super) operation_id: String,
    pub(super) run_id: String,
    pub(super) tenant_id: String,
    pub(super) project_id: String,
    pub(super) job_id: String,
    pub(super) actor_user_id: String,
    pub(super) runtime_execution_id: String,
    pub(super) conversation_id: Option<String>,
    pub(super) job_snapshot: Value,
    pub(super) attempts: u64,
    pub(super) max_retries: u64,
    pub(super) deadline_at: DateTime<Utc>,
    pub(super) worker_id: String,
    pub(super) lease_token: String,
    pub(super) fence_token: u64,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(super) struct AutomationExecutionRecord {
    pub(super) error_code: Option<String>,
    pub(super) result_summary: Option<Value>,
    pub(super) event_count: u64,
    pub(super) execution_time_ms: u64,
    pub(super) conversation_id: Option<String>,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub(super) struct AutomationScheduleDispatchSummary {
    pub(super) due: usize,
    pub(super) enqueued: usize,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub(super) struct AutomationStartupRecovery {
    pub(super) expired_operations: usize,
    pub(super) requeued_runs: usize,
}

#[derive(Debug, PartialEq, Eq)]
pub(super) enum AutomationLedgerError {
    NotFound,
    RevisionConflict {
        expected: u64,
        actual: u64,
    },
    IdempotencyConflict,
    #[cfg_attr(not(test), allow(dead_code))]
    LeaseLost,
    InvalidRecord(String),
    Storage(String),
}

pub(super) fn enqueue_manual_run(
    store: &DesktopSessionStore,
    command: ManualRunCommand<'_>,
    clock: &dyn AutomationClock,
) -> Result<AutomationRunReceipt, AutomationLedgerError> {
    let mut connection = store.connection().map_err(AutomationLedgerError::Storage)?;
    let transaction = connection
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(storage)?;
    if let Some(receipt) = replay_receipt(&transaction, command)? {
        return Ok(receipt);
    }
    let job = read_job(&transaction, command.project_id, command.job_id)?
        .ok_or(AutomationLedgerError::NotFound)?;
    let actual_revision = required_u64(&job, "revision")?;
    if actual_revision != command.expected_revision {
        return Err(AutomationLedgerError::RevisionConflict {
            expected: command.expected_revision,
            actual: actual_revision,
        });
    }
    let schedule_revision = job.get("schedule_revision").and_then(Value::as_u64);
    let tenant_id = required_string(&job, "tenant_id")?;
    let actor_user_id = command.user_id;
    let timeout_seconds = job
        .get("timeout_seconds")
        .and_then(Value::as_u64)
        .unwrap_or(300);
    let max_retries = job
        .get("max_retries")
        .and_then(Value::as_u64)
        .unwrap_or_default();
    let job_snapshot = serde_json::to_string(&job).map_err(invalid_record)?;
    let now = clock.now();
    let now_text = now.to_rfc3339();
    let receipt_id = Uuid::new_v4().to_string();
    let run_id = Uuid::new_v4().to_string();
    let runtime_execution_id = format!("local-automation-execution-{run_id}");
    let operation_id = Uuid::new_v4().to_string();
    let occurrence_key = format!("manual:{}", command.idempotency_key);
    let deadline_at_ms = deadline_at(now, timeout_seconds)?.timestamp_millis();
    transaction
        .execute(
            "INSERT INTO desktop_automation_runs (
               id, receipt_id, project_id, job_id, job_revision, schedule_revision,
               trigger_type, status, tenant_id, actor_user_id, conversation_id, scheduled_for,
               runtime_execution_id, job_snapshot_json, timeout_seconds, max_retries,
               deadline_at_ms, accepted_at, updated_at
             ) VALUES (
               ?1, ?2, ?3, ?4, ?5, ?6, 'manual', 'queued', ?7, ?8, ?9, ?10,
               ?11, ?12, ?13, ?14, ?15, ?16, ?16
             )",
            params![
                run_id,
                receipt_id,
                command.project_id,
                command.job_id,
                actual_revision,
                schedule_revision,
                tenant_id,
                actor_user_id,
                command.conversation_id,
                now_text,
                runtime_execution_id,
                job_snapshot,
                timeout_seconds,
                max_retries,
                deadline_at_ms,
                now_text,
            ],
        )
        .map_err(storage)?;
    transaction
        .execute(
            "INSERT INTO desktop_automation_operations (
               id, project_id, job_id, run_id, operation_kind, occurrence_key,
               status, available_at_ms, created_at, updated_at
             ) VALUES (?1, ?2, ?3, ?4, 'execute_run', ?5, 'queued', ?6, ?7, ?7)",
            params![
                operation_id,
                command.project_id,
                command.job_id,
                run_id,
                occurrence_key,
                now.timestamp_millis(),
                now_text,
            ],
        )
        .map_err(storage)?;
    transaction
        .execute(
            "INSERT INTO desktop_automation_run_receipts (
               user_id, project_id, job_id, idempotency_key, request_hash,
               receipt_id, run_id, status, created_at
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, 'queued', ?8)",
            params![
                command.user_id,
                command.project_id,
                command.job_id,
                command.idempotency_key,
                command.request_hash,
                receipt_id,
                run_id,
                now_text,
            ],
        )
        .map_err(storage)?;
    transaction.commit().map_err(storage)?;
    Ok(AutomationRunReceipt {
        receipt_id,
        run_id,
        job_id: command.job_id.to_string(),
        status: AutomationRunStatus::Queued,
        duplicate: false,
    })
}

pub(super) fn lookup_manual_run_receipt(
    store: &DesktopSessionStore,
    command: ManualRunCommand<'_>,
) -> Result<Option<AutomationRunReceipt>, AutomationLedgerError> {
    let connection = store.connection().map_err(AutomationLedgerError::Storage)?;
    let transaction = connection.unchecked_transaction().map_err(storage)?;
    let receipt = replay_receipt(&transaction, command)?;
    transaction.commit().map_err(storage)?;
    Ok(receipt)
}

pub(super) fn list_runs(
    store: &DesktopSessionStore,
    project_id: &str,
    job_id: &str,
    limit: i64,
    offset: i64,
) -> Result<(Vec<Value>, i64), AutomationLedgerError> {
    let connection = store.connection().map_err(AutomationLedgerError::Storage)?;
    let total = connection
        .query_row(
            "SELECT COUNT(*) FROM desktop_automation_runs
             WHERE project_id = ?1 AND job_id = ?2",
            params![project_id, job_id],
            |row| row.get(0),
        )
        .map_err(storage)?;
    let mut statement = connection
        .prepare(
            "SELECT id, status, trigger_type, accepted_at, started_at, finished_at,
                    error_code, conversation_id, result_summary_json, event_count,
                    execution_time_ms
             FROM desktop_automation_runs
             WHERE project_id = ?1 AND job_id = ?2
             ORDER BY accepted_at DESC, id ASC LIMIT ?3 OFFSET ?4",
        )
        .map_err(storage)?;
    let rows = statement
        .query_map(params![project_id, job_id, limit, offset], |row| {
            let encoded_summary = row.get::<_, Option<String>>(8)?;
            let result_summary = encoded_summary
                .as_deref()
                .and_then(|value| serde_json::from_str::<Value>(value).ok())
                .unwrap_or_else(|| {
                    json!({
                        "authority": "local_durable_ledger",
                        "execution_availability": "degraded",
                        "reason_code": EXECUTION_UNAVAILABLE_REASON,
                    })
                });
            Ok(json!({
                "id": row.get::<_, String>(0)?,
                "job_id": job_id,
                "project_id": project_id,
                "status": row.get::<_, String>(1)?,
                "trigger_type": row.get::<_, String>(2)?,
                "started_at": row.get::<_, Option<String>>(4)?
                    .unwrap_or(row.get::<_, String>(3)?),
                "finished_at": row.get::<_, Option<String>>(5)?,
                "duration_ms": row.get::<_, Option<u64>>(10)?,
                "error_message": row.get::<_, Option<String>>(6)?,
                "result_summary": result_summary,
                "event_count": row.get::<_, Option<u64>>(9)?,
                "conversation_id": row.get::<_, Option<String>>(7)?,
            }))
        })
        .map_err(storage)?;
    let mut items = Vec::new();
    for row in rows {
        items.push(row.map_err(storage)?);
    }
    Ok((items, total))
}

#[cfg(test)]
pub(super) fn recover_startup_state(
    store: &DesktopSessionStore,
    clock: &dyn AutomationClock,
) -> Result<AutomationStartupRecovery, AutomationLedgerError> {
    let connection = store.connection().map_err(AutomationLedgerError::Storage)?;
    recover_connection(&connection, clock)
}

#[cfg_attr(not(test), allow(dead_code))]
pub(super) fn claim_next_operation(
    store: &DesktopSessionStore,
    worker_id: &str,
    lease_duration: Duration,
    clock: &dyn AutomationClock,
) -> Result<Option<AutomationOperationClaim>, AutomationLedgerError> {
    if worker_id.trim().is_empty() || lease_duration.is_zero() {
        return Err(AutomationLedgerError::InvalidRecord(
            "worker id and lease duration are required".into(),
        ));
    }
    let mut connection = store.connection().map_err(AutomationLedgerError::Storage)?;
    let transaction = connection
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(storage)?;
    let now = clock.now();
    recover_transaction(&transaction, now)?;
    let candidate = transaction
        .query_row(
            "SELECT operation.id, operation.run_id, operation.fence_token,
                    run.tenant_id, operation.project_id, operation.job_id,
                    run.actor_user_id, run.runtime_execution_id, run.conversation_id,
                    run.job_snapshot_json, operation.attempts, run.max_retries,
                    run.deadline_at_ms
             FROM desktop_automation_operations AS operation
             INNER JOIN desktop_automation_runs AS run ON run.id = operation.run_id
             WHERE operation.status = 'queued' AND operation.available_at_ms <= ?1
               AND run.status = 'queued'
             ORDER BY operation.available_at_ms ASC, operation.created_at ASC,
                      operation.id ASC
             LIMIT 1",
            [now.timestamp_millis()],
            |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, u64>(2)?,
                    row.get::<_, String>(3)?,
                    row.get::<_, String>(4)?,
                    row.get::<_, String>(5)?,
                    row.get::<_, String>(6)?,
                    row.get::<_, String>(7)?,
                    row.get::<_, Option<String>>(8)?,
                    row.get::<_, String>(9)?,
                    row.get::<_, u64>(10)?,
                    row.get::<_, u64>(11)?,
                    row.get::<_, i64>(12)?,
                ))
            },
        )
        .optional()
        .map_err(storage)?;
    let Some((
        operation_id,
        run_id,
        prior_fence,
        tenant_id,
        project_id,
        job_id,
        actor_user_id,
        runtime_execution_id,
        conversation_id,
        job_snapshot_json,
        prior_attempts,
        max_retries,
        deadline_at_ms,
    )) = candidate
    else {
        transaction.commit().map_err(storage)?;
        return Ok(None);
    };
    let job_snapshot = serde_json::from_str(&job_snapshot_json).map_err(invalid_record)?;
    let deadline_at = DateTime::from_timestamp_millis(deadline_at_ms).ok_or_else(|| {
        AutomationLedgerError::InvalidRecord("automation run deadline is invalid".into())
    })?;
    let fence_token = prior_fence.saturating_add(1);
    let lease_token = Uuid::new_v4().to_string();
    let lease_millis = i64::try_from(lease_duration.as_millis())
        .map_err(|_| AutomationLedgerError::InvalidRecord("lease duration is too large".into()))?;
    let lease_expires_at_ms = now
        .timestamp_millis()
        .checked_add(lease_millis)
        .ok_or_else(|| AutomationLedgerError::InvalidRecord("lease expiry overflow".into()))?;
    let now_text = now.to_rfc3339();
    let claimed = transaction
        .execute(
            "UPDATE desktop_automation_operations
             SET status = 'running', lease_owner = ?1, lease_token = ?2,
                 lease_expires_at_ms = ?3, fence_token = ?4,
                 attempts = attempts + 1, updated_at = ?5
             WHERE id = ?6 AND status = 'queued' AND fence_token = ?7",
            params![
                worker_id,
                lease_token,
                lease_expires_at_ms,
                fence_token,
                now_text,
                operation_id,
                prior_fence,
            ],
        )
        .map_err(storage)?;
    if claimed != 1 {
        return Err(AutomationLedgerError::LeaseLost);
    }
    transaction
        .execute(
            "UPDATE desktop_automation_runs
             SET status = 'running', started_at = COALESCE(started_at, ?1),
                 error_code = NULL, updated_at = ?1
             WHERE id = ?2 AND status = 'queued'",
            params![now_text, run_id],
        )
        .map_err(storage)?;
    transaction.commit().map_err(storage)?;
    Ok(Some(AutomationOperationClaim {
        operation_id,
        run_id,
        tenant_id,
        project_id,
        job_id,
        actor_user_id,
        runtime_execution_id,
        conversation_id,
        job_snapshot,
        attempts: prior_attempts.saturating_add(1),
        max_retries,
        deadline_at,
        worker_id: worker_id.to_string(),
        lease_token,
        fence_token,
    }))
}

#[cfg_attr(not(test), allow(dead_code))]
pub(super) fn renew_operation_lease(
    store: &DesktopSessionStore,
    claim: &AutomationOperationClaim,
    lease_duration: Duration,
    clock: &dyn AutomationClock,
) -> Result<bool, AutomationLedgerError> {
    if lease_duration.is_zero() {
        return Err(AutomationLedgerError::InvalidRecord(
            "lease duration is required".into(),
        ));
    }
    let lease_millis = i64::try_from(lease_duration.as_millis())
        .map_err(|_| AutomationLedgerError::InvalidRecord("lease duration is too large".into()))?;
    let now = clock.now();
    let lease_expires_at_ms = now
        .timestamp_millis()
        .checked_add(lease_millis)
        .ok_or_else(|| AutomationLedgerError::InvalidRecord("lease expiry overflow".into()))?;
    store
        .connection()
        .map_err(AutomationLedgerError::Storage)?
        .execute(
            "UPDATE desktop_automation_operations
             SET lease_expires_at_ms = ?1, updated_at = ?2
             WHERE id = ?3 AND run_id = ?4 AND status = 'running'
               AND lease_owner = ?5 AND lease_token = ?6 AND fence_token = ?7",
            params![
                lease_expires_at_ms,
                now.to_rfc3339(),
                claim.operation_id,
                claim.run_id,
                claim.worker_id,
                claim.lease_token,
                claim.fence_token,
            ],
        )
        .map(|updated| updated == 1)
        .map_err(storage)
}

#[cfg_attr(not(test), allow(dead_code))]
pub(super) fn settle_operation(
    store: &DesktopSessionStore,
    claim: &AutomationOperationClaim,
    status: AutomationRunStatus,
    error_code: Option<&str>,
    clock: &dyn AutomationClock,
) -> Result<(), AutomationLedgerError> {
    settle_operation_with_result(
        store,
        claim,
        status,
        AutomationExecutionRecord {
            error_code: error_code.map(ToString::to_string),
            result_summary: None,
            event_count: 0,
            execution_time_ms: 0,
            conversation_id: claim.conversation_id.clone(),
        },
        clock,
    )
}

pub(super) fn settle_operation_with_result(
    store: &DesktopSessionStore,
    claim: &AutomationOperationClaim,
    status: AutomationRunStatus,
    execution: AutomationExecutionRecord,
    clock: &dyn AutomationClock,
) -> Result<(), AutomationLedgerError> {
    if matches!(
        status,
        AutomationRunStatus::Queued | AutomationRunStatus::Running
    ) {
        return Err(AutomationLedgerError::InvalidRecord(
            "claimed operation must settle to waiting_human or a terminal status".into(),
        ));
    }
    let mut connection = store.connection().map_err(AutomationLedgerError::Storage)?;
    let transaction = connection
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(storage)?;
    let now_text = clock.now().to_rfc3339();
    let result_summary_json = execution
        .result_summary
        .as_ref()
        .map(serde_json::to_string)
        .transpose()
        .map_err(invalid_record)?;
    let settled = transaction
        .execute(
            "UPDATE desktop_automation_operations
             SET status = ?1, lease_owner = NULL, lease_token = NULL,
                 lease_expires_at_ms = NULL, last_error_code = ?2, updated_at = ?3
             WHERE id = ?4 AND run_id = ?5 AND status = 'running'
               AND lease_owner = ?6 AND lease_token = ?7 AND fence_token = ?8",
            params![
                status.as_str(),
                execution.error_code,
                now_text,
                claim.operation_id,
                claim.run_id,
                claim.worker_id,
                claim.lease_token,
                claim.fence_token,
            ],
        )
        .map_err(storage)?;
    if settled != 1 {
        return Err(AutomationLedgerError::LeaseLost);
    }
    let finished_at = status.is_terminal().then_some(now_text.as_str());
    transaction
        .execute(
            "UPDATE desktop_automation_runs
             SET status = ?1, error_code = ?2, finished_at = ?3,
                 result_summary_json = ?4, event_count = ?5, execution_time_ms = ?6,
                 conversation_id = COALESCE(?7, conversation_id), updated_at = ?8
             WHERE id = ?9",
            params![
                status.as_str(),
                execution.error_code,
                finished_at,
                result_summary_json,
                execution.event_count,
                execution.execution_time_ms,
                execution.conversation_id,
                now_text,
                claim.run_id,
            ],
        )
        .map_err(storage)?;
    transaction
        .execute(
            "UPDATE desktop_automation_run_receipts SET status = ?1 WHERE run_id = ?2",
            params![status.as_str(), claim.run_id],
        )
        .map_err(storage)?;
    transaction.commit().map_err(storage)
}

pub(super) fn retry_operation(
    store: &DesktopSessionStore,
    claim: &AutomationOperationClaim,
    error_code: &str,
    retry_delay: Duration,
    clock: &dyn AutomationClock,
) -> Result<bool, AutomationLedgerError> {
    if error_code.trim().is_empty() {
        return Err(AutomationLedgerError::InvalidRecord(
            "retry error code is required".into(),
        ));
    }
    if claim.attempts > claim.max_retries {
        return Ok(false);
    }
    let delay_millis = i64::try_from(retry_delay.as_millis())
        .map_err(|_| AutomationLedgerError::InvalidRecord("retry delay is too large".into()))?;
    let now = clock.now();
    let available_at_ms = now
        .timestamp_millis()
        .checked_add(delay_millis)
        .ok_or_else(|| AutomationLedgerError::InvalidRecord("retry time overflow".into()))?;
    if available_at_ms >= claim.deadline_at.timestamp_millis() {
        return Ok(false);
    }
    let mut connection = store.connection().map_err(AutomationLedgerError::Storage)?;
    let transaction = connection
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(storage)?;
    let now_text = now.to_rfc3339();
    let requeued = transaction
        .execute(
            "UPDATE desktop_automation_operations
             SET status = 'queued', available_at_ms = ?1,
                 lease_owner = NULL, lease_token = NULL, lease_expires_at_ms = NULL,
                 last_error_code = ?2, updated_at = ?3
             WHERE id = ?4 AND run_id = ?5 AND status = 'running'
               AND lease_owner = ?6 AND lease_token = ?7 AND fence_token = ?8",
            params![
                available_at_ms,
                error_code,
                now_text,
                claim.operation_id,
                claim.run_id,
                claim.worker_id,
                claim.lease_token,
                claim.fence_token,
            ],
        )
        .map_err(storage)?;
    if requeued != 1 {
        return Err(AutomationLedgerError::LeaseLost);
    }
    transaction
        .execute(
            "UPDATE desktop_automation_runs
             SET status = 'queued', error_code = ?1, finished_at = NULL, updated_at = ?2
             WHERE id = ?3 AND status = 'running'",
            params![error_code, now_text, claim.run_id],
        )
        .map_err(storage)?;
    transaction
        .execute(
            "UPDATE desktop_automation_run_receipts SET status = 'queued' WHERE run_id = ?1",
            [&claim.run_id],
        )
        .map_err(storage)?;
    transaction.commit().map_err(storage)?;
    Ok(true)
}
