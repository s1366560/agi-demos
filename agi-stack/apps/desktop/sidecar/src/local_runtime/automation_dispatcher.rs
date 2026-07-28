use std::time::Duration;

use chrono::{DateTime, Utc};
use rusqlite::{params, Connection, OptionalExtension, Transaction, TransactionBehavior};
use serde::Serialize;
use serde_json::{json, Value};
use uuid::Uuid;

use super::session_store::DesktopSessionStore;

const EXECUTION_UNAVAILABLE_REASON: &str = "local_automation_execution_runtime_unavailable";
const SCHEDULE_UNAVAILABLE_REASON: &str = "local_automation_schedule_runtime_unavailable";
const SCHEDULE_DISABLED_REASON: &str = "local_automation_schedule_disabled";
const RESTART_RECOVERY_REASON: &str = "local_automation_restart_recovered";

pub(super) trait AutomationClock {
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
    pub(super) worker_id: String,
    pub(super) lease_token: String,
    pub(super) fence_token: u64,
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

pub(super) fn initialize_schema(connection: &Connection) -> Result<(), String> {
    connection
        .execute_batch(
            "CREATE TABLE IF NOT EXISTS desktop_automation_schedule_state (
               job_id TEXT PRIMARY KEY,
               project_id TEXT NOT NULL,
               schedule_revision INTEGER NOT NULL,
               enabled INTEGER NOT NULL,
               next_fire_at TEXT,
               last_occurrence_key TEXT,
               availability TEXT NOT NULL,
               reason_code TEXT,
               updated_at TEXT NOT NULL
             );
             CREATE TABLE IF NOT EXISTS desktop_automation_runs (
               id TEXT PRIMARY KEY,
               receipt_id TEXT NOT NULL UNIQUE,
               project_id TEXT NOT NULL,
               job_id TEXT NOT NULL,
               job_revision INTEGER NOT NULL,
               schedule_revision INTEGER,
               trigger_type TEXT NOT NULL,
               status TEXT NOT NULL,
               conversation_id TEXT,
               scheduled_for TEXT,
               runtime_execution_id TEXT,
               error_code TEXT,
               accepted_at TEXT NOT NULL,
               started_at TEXT,
               finished_at TEXT,
               updated_at TEXT NOT NULL
             );
             CREATE TABLE IF NOT EXISTS desktop_automation_operations (
               id TEXT PRIMARY KEY,
               project_id TEXT NOT NULL,
               job_id TEXT NOT NULL,
               run_id TEXT NOT NULL UNIQUE,
               operation_kind TEXT NOT NULL,
               occurrence_key TEXT NOT NULL,
               status TEXT NOT NULL,
               available_at_ms INTEGER NOT NULL,
               lease_owner TEXT,
               lease_token TEXT,
               lease_expires_at_ms INTEGER,
               fence_token INTEGER NOT NULL DEFAULT 0,
               attempts INTEGER NOT NULL DEFAULT 0,
               last_error_code TEXT,
               created_at TEXT NOT NULL,
               updated_at TEXT NOT NULL,
               UNIQUE(job_id, operation_kind, occurrence_key)
             );
             CREATE TABLE IF NOT EXISTS desktop_automation_run_receipts (
               user_id TEXT NOT NULL,
               project_id TEXT NOT NULL,
               job_id TEXT NOT NULL,
               idempotency_key TEXT NOT NULL,
               request_hash TEXT NOT NULL,
               receipt_id TEXT NOT NULL,
               run_id TEXT NOT NULL,
               status TEXT NOT NULL,
               created_at TEXT NOT NULL,
               PRIMARY KEY(user_id, project_id, job_id, idempotency_key)
             );
             CREATE INDEX IF NOT EXISTS idx_desktop_automation_runs_job
               ON desktop_automation_runs(project_id, job_id, accepted_at DESC);
             CREATE INDEX IF NOT EXISTS idx_desktop_automation_operations_claim
               ON desktop_automation_operations(status, available_at_ms, created_at);
             CREATE INDEX IF NOT EXISTS idx_desktop_automation_receipts_scope
               ON desktop_automation_run_receipts(user_id, project_id, job_id, created_at);
             CREATE TRIGGER IF NOT EXISTS desktop_automation_schedule_after_insert
             AFTER INSERT ON desktop_automation_jobs
             BEGIN
               INSERT INTO desktop_automation_schedule_state (
                 job_id, project_id, schedule_revision, enabled, next_fire_at,
                 last_occurrence_key, availability, reason_code, updated_at
               ) VALUES (
                 NEW.id,
                 NEW.project_id,
                 COALESCE(CAST(json_extract(NEW.value_json, '$.schedule_revision') AS INTEGER), 1),
                 NEW.enabled,
                 NULL,
                 NULL,
                 CASE WHEN NEW.enabled = 1 THEN 'degraded' ELSE 'not_applicable' END,
                 CASE
                   WHEN NEW.enabled = 1
                     THEN 'local_automation_schedule_runtime_unavailable'
                   ELSE 'local_automation_schedule_disabled'
                 END,
                 COALESCE(json_extract(NEW.value_json, '$.updated_at'), NEW.created_at)
               )
               ON CONFLICT(job_id) DO UPDATE SET
                 project_id = excluded.project_id,
                 schedule_revision = excluded.schedule_revision,
                 enabled = excluded.enabled,
                 availability = excluded.availability,
                 reason_code = excluded.reason_code,
                 updated_at = excluded.updated_at;
             END;
             CREATE TRIGGER IF NOT EXISTS desktop_automation_schedule_after_update
             AFTER UPDATE OF enabled, value_json ON desktop_automation_jobs
             BEGIN
               INSERT INTO desktop_automation_schedule_state (
                 job_id, project_id, schedule_revision, enabled, next_fire_at,
                 last_occurrence_key, availability, reason_code, updated_at
               ) VALUES (
                 NEW.id,
                 NEW.project_id,
                 COALESCE(CAST(json_extract(NEW.value_json, '$.schedule_revision') AS INTEGER), 1),
                 NEW.enabled,
                 NULL,
                 NULL,
                 CASE WHEN NEW.enabled = 1 THEN 'degraded' ELSE 'not_applicable' END,
                 CASE
                   WHEN NEW.enabled = 1
                     THEN 'local_automation_schedule_runtime_unavailable'
                   ELSE 'local_automation_schedule_disabled'
                 END,
                 COALESCE(json_extract(NEW.value_json, '$.updated_at'), NEW.created_at)
               )
               ON CONFLICT(job_id) DO UPDATE SET
                 project_id = excluded.project_id,
                 schedule_revision = excluded.schedule_revision,
                 enabled = excluded.enabled,
                 availability = excluded.availability,
                 reason_code = excluded.reason_code,
                 updated_at = excluded.updated_at;
             END;
             CREATE TRIGGER IF NOT EXISTS desktop_automation_schedule_after_delete
             AFTER DELETE ON desktop_automation_jobs
             BEGIN
               DELETE FROM desktop_automation_schedule_state WHERE job_id = OLD.id;
             END;",
        )
        .map_err(|error| error.to_string())?;
    recover_connection(connection, &SystemAutomationClock)
        .map(|_| ())
        .map_err(|error| format!("{error:?}"))
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
    let now = clock.now();
    let now_text = now.to_rfc3339();
    let receipt_id = Uuid::new_v4().to_string();
    let run_id = Uuid::new_v4().to_string();
    let operation_id = Uuid::new_v4().to_string();
    let occurrence_key = format!("manual:{}", command.idempotency_key);
    transaction
        .execute(
            "INSERT INTO desktop_automation_runs (
               id, receipt_id, project_id, job_id, job_revision, schedule_revision,
               trigger_type, status, conversation_id, scheduled_for,
               accepted_at, updated_at
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, 'manual', 'queued', ?7, ?8, ?8, ?8)",
            params![
                run_id,
                receipt_id,
                command.project_id,
                command.job_id,
                actual_revision,
                schedule_revision,
                command.conversation_id,
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
                    error_code, conversation_id
             FROM desktop_automation_runs
             WHERE project_id = ?1 AND job_id = ?2
             ORDER BY accepted_at DESC, id ASC LIMIT ?3 OFFSET ?4",
        )
        .map_err(storage)?;
    let rows = statement
        .query_map(params![project_id, job_id, limit, offset], |row| {
            Ok(json!({
                "id": row.get::<_, String>(0)?,
                "job_id": job_id,
                "project_id": project_id,
                "status": row.get::<_, String>(1)?,
                "trigger_type": row.get::<_, String>(2)?,
                "started_at": row.get::<_, Option<String>>(4)?
                    .unwrap_or(row.get::<_, String>(3)?),
                "finished_at": row.get::<_, Option<String>>(5)?,
                "duration_ms": Value::Null,
                "error_message": row.get::<_, Option<String>>(6)?,
                "result_summary": {
                    "authority": "local_durable_ledger",
                    "execution_availability": "degraded",
                    "reason_code": EXECUTION_UNAVAILABLE_REASON,
                },
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
            "SELECT id, run_id, fence_token
             FROM desktop_automation_operations
             WHERE status = 'queued' AND available_at_ms <= ?1
             ORDER BY available_at_ms ASC, created_at ASC, id ASC LIMIT 1",
            [now.timestamp_millis()],
            |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, u64>(2)?,
                ))
            },
        )
        .optional()
        .map_err(storage)?;
    let Some((operation_id, run_id, prior_fence)) = candidate else {
        transaction.commit().map_err(storage)?;
        return Ok(None);
    };
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
        worker_id: worker_id.to_string(),
        lease_token,
        fence_token,
    }))
}

#[cfg_attr(not(test), allow(dead_code))]
pub(super) fn settle_operation(
    store: &DesktopSessionStore,
    claim: &AutomationOperationClaim,
    status: AutomationRunStatus,
    error_code: Option<&str>,
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
    let settled = transaction
        .execute(
            "UPDATE desktop_automation_operations
             SET status = ?1, lease_owner = NULL, lease_token = NULL,
                 lease_expires_at_ms = NULL, last_error_code = ?2, updated_at = ?3
             WHERE id = ?4 AND run_id = ?5 AND status = 'running'
               AND lease_owner = ?6 AND lease_token = ?7 AND fence_token = ?8",
            params![
                status.as_str(),
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
    if settled != 1 {
        return Err(AutomationLedgerError::LeaseLost);
    }
    let finished_at = status.is_terminal().then_some(now_text.as_str());
    transaction
        .execute(
            "UPDATE desktop_automation_runs
             SET status = ?1, error_code = ?2, finished_at = ?3, updated_at = ?4
             WHERE id = ?5",
            params![
                status.as_str(),
                error_code,
                finished_at,
                now_text,
                claim.run_id,
            ],
        )
        .map_err(storage)?;
    transaction.commit().map_err(storage)
}

fn recover_connection(
    connection: &Connection,
    clock: &dyn AutomationClock,
) -> Result<AutomationStartupRecovery, AutomationLedgerError> {
    let transaction = connection.unchecked_transaction().map_err(storage)?;
    reconcile_schedule_state(&transaction, clock.now())?;
    let recovered = recover_transaction(&transaction, clock.now())?;
    transaction.commit().map_err(storage)?;
    Ok(recovered)
}

fn recover_transaction(
    transaction: &Transaction<'_>,
    now: DateTime<Utc>,
) -> Result<AutomationStartupRecovery, AutomationLedgerError> {
    let now_text = now.to_rfc3339();
    let now_ms = now.timestamp_millis();
    let requeued_runs = transaction
        .execute(
            "UPDATE desktop_automation_runs
             SET status = 'queued', error_code = ?1, finished_at = NULL, updated_at = ?2
             WHERE status = 'running' AND id IN (
               SELECT run_id FROM desktop_automation_operations
               WHERE status = 'running'
                 AND (lease_expires_at_ms IS NULL OR lease_expires_at_ms <= ?3)
             )",
            params![RESTART_RECOVERY_REASON, now_text, now_ms],
        )
        .map_err(storage)?;
    let expired_operations = transaction
        .execute(
            "UPDATE desktop_automation_operations
             SET status = 'queued', available_at_ms = ?1,
                 lease_owner = NULL, lease_token = NULL, lease_expires_at_ms = NULL,
                 fence_token = fence_token + 1, last_error_code = ?2, updated_at = ?3
             WHERE status = 'running'
               AND (lease_expires_at_ms IS NULL OR lease_expires_at_ms <= ?1)",
            params![now_ms, RESTART_RECOVERY_REASON, now_text],
        )
        .map_err(storage)?;
    Ok(AutomationStartupRecovery {
        expired_operations,
        requeued_runs,
    })
}

fn reconcile_schedule_state(
    transaction: &Transaction<'_>,
    now: DateTime<Utc>,
) -> Result<(), AutomationLedgerError> {
    transaction
        .execute(
            "INSERT INTO desktop_automation_schedule_state (
               job_id, project_id, schedule_revision, enabled, next_fire_at,
               last_occurrence_key, availability, reason_code, updated_at
             )
             SELECT
               id,
               project_id,
               COALESCE(CAST(json_extract(value_json, '$.schedule_revision') AS INTEGER), 1),
               enabled,
               NULL,
               NULL,
               CASE WHEN enabled = 1 THEN 'degraded' ELSE 'not_applicable' END,
               CASE WHEN enabled = 1 THEN ?1 ELSE ?2 END,
               ?3
             FROM desktop_automation_jobs WHERE true
             ON CONFLICT(job_id) DO UPDATE SET
               project_id = excluded.project_id,
               schedule_revision = excluded.schedule_revision,
               enabled = excluded.enabled,
               availability = excluded.availability,
               reason_code = excluded.reason_code,
               updated_at = excluded.updated_at",
            params![
                SCHEDULE_UNAVAILABLE_REASON,
                SCHEDULE_DISABLED_REASON,
                now.to_rfc3339(),
            ],
        )
        .map_err(storage)?;
    transaction
        .execute(
            "DELETE FROM desktop_automation_schedule_state
             WHERE NOT EXISTS (
               SELECT 1 FROM desktop_automation_jobs
               WHERE desktop_automation_jobs.id = desktop_automation_schedule_state.job_id
             )",
            [],
        )
        .map_err(storage)?;
    Ok(())
}

fn replay_receipt(
    transaction: &Transaction<'_>,
    command: ManualRunCommand<'_>,
) -> Result<Option<AutomationRunReceipt>, AutomationLedgerError> {
    let receipt = transaction
        .query_row(
            "SELECT request_hash, receipt_id, run_id, status
             FROM desktop_automation_run_receipts
             WHERE user_id = ?1 AND project_id = ?2 AND job_id = ?3
               AND idempotency_key = ?4",
            params![
                command.user_id,
                command.project_id,
                command.job_id,
                command.idempotency_key,
            ],
            |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, String>(2)?,
                    row.get::<_, String>(3)?,
                ))
            },
        )
        .optional()
        .map_err(storage)?;
    match receipt {
        Some((stored_hash, _, _, _)) if stored_hash != command.request_hash => {
            Err(AutomationLedgerError::IdempotencyConflict)
        }
        Some((_, receipt_id, run_id, status)) => Ok(Some(AutomationRunReceipt {
            receipt_id,
            run_id,
            job_id: command.job_id.to_string(),
            status: parse_status(&status)?,
            duplicate: true,
        })),
        None => Ok(None),
    }
}

fn read_job(
    transaction: &Transaction<'_>,
    project_id: &str,
    job_id: &str,
) -> Result<Option<Value>, AutomationLedgerError> {
    let encoded = transaction
        .query_row(
            "SELECT value_json FROM desktop_automation_jobs
             WHERE project_id = ?1 AND id = ?2",
            params![project_id, job_id],
            |row| row.get::<_, String>(0),
        )
        .optional()
        .map_err(storage)?;
    encoded
        .map(|value| serde_json::from_str(&value).map_err(invalid_record))
        .transpose()
}

fn required_u64(value: &Value, field: &str) -> Result<u64, AutomationLedgerError> {
    value
        .get(field)
        .and_then(Value::as_u64)
        .ok_or_else(|| AutomationLedgerError::InvalidRecord(format!("{field} must be an integer")))
}

fn parse_status(value: &str) -> Result<AutomationRunStatus, AutomationLedgerError> {
    match value {
        "queued" => Ok(AutomationRunStatus::Queued),
        "running" => Ok(AutomationRunStatus::Running),
        "waiting_human" => Ok(AutomationRunStatus::WaitingHuman),
        "success" => Ok(AutomationRunStatus::Success),
        "failed" => Ok(AutomationRunStatus::Failed),
        "timeout" => Ok(AutomationRunStatus::Timeout),
        "cancelled" => Ok(AutomationRunStatus::Cancelled),
        _ => Err(AutomationLedgerError::InvalidRecord(
            "automation run status is invalid".into(),
        )),
    }
}

fn storage(error: rusqlite::Error) -> AutomationLedgerError {
    AutomationLedgerError::Storage(error.to_string())
}

fn invalid_record(error: serde_json::Error) -> AutomationLedgerError {
    AutomationLedgerError::InvalidRecord(error.to_string())
}
