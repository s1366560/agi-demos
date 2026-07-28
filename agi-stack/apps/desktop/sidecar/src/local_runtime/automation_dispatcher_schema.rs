use rusqlite::{params, Connection, Transaction};

use super::{
    automation_dispatcher::{
        AutomationClock, AutomationLedgerError, AutomationStartupRecovery, SystemAutomationClock,
    },
    automation_ledger_support::{ensure_column, storage},
    automation_schedule_dispatcher::reconcile_schedule_state,
};

const RESTART_RECOVERY_REASON: &str = "local_automation_restart_recovered";

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
               schedule_fingerprint TEXT,
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
               tenant_id TEXT NOT NULL DEFAULT 'local',
               actor_user_id TEXT NOT NULL DEFAULT '',
               conversation_id TEXT,
               scheduled_for TEXT,
               runtime_execution_id TEXT,
               job_snapshot_json TEXT NOT NULL DEFAULT '{}',
               timeout_seconds INTEGER NOT NULL DEFAULT 300,
               max_retries INTEGER NOT NULL DEFAULT 0,
               deadline_at_ms INTEGER,
               error_code TEXT,
               result_summary_json TEXT,
               event_count INTEGER,
               execution_time_ms INTEGER,
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
                 last_occurrence_key, schedule_fingerprint, availability, reason_code, updated_at
               ) VALUES (
                 NEW.id,
                 NEW.project_id,
                 COALESCE(CAST(json_extract(NEW.value_json, '$.schedule_revision') AS INTEGER), 1),
                 NEW.enabled,
                 NULL,
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
                 next_fire_at = NULL,
                 last_occurrence_key = NULL,
                 schedule_fingerprint = NULL,
                 availability = excluded.availability,
                 reason_code = excluded.reason_code,
                 updated_at = excluded.updated_at;
             END;
             CREATE TRIGGER IF NOT EXISTS desktop_automation_schedule_after_update
             AFTER UPDATE OF enabled, value_json ON desktop_automation_jobs
             BEGIN
               INSERT INTO desktop_automation_schedule_state (
                 job_id, project_id, schedule_revision, enabled, next_fire_at,
                 last_occurrence_key, schedule_fingerprint, availability, reason_code, updated_at
               ) VALUES (
                 NEW.id,
                 NEW.project_id,
                 COALESCE(CAST(json_extract(NEW.value_json, '$.schedule_revision') AS INTEGER), 1),
                 NEW.enabled,
                 NULL,
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
                 next_fire_at = NULL,
                 last_occurrence_key = NULL,
                 schedule_fingerprint = NULL,
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
    for (table, column, definition) in [
        (
            "desktop_automation_schedule_state",
            "schedule_fingerprint",
            "TEXT",
        ),
        (
            "desktop_automation_runs",
            "tenant_id",
            "TEXT NOT NULL DEFAULT 'local'",
        ),
        (
            "desktop_automation_runs",
            "actor_user_id",
            "TEXT NOT NULL DEFAULT ''",
        ),
        (
            "desktop_automation_runs",
            "job_snapshot_json",
            "TEXT NOT NULL DEFAULT '{}'",
        ),
        (
            "desktop_automation_runs",
            "timeout_seconds",
            "INTEGER NOT NULL DEFAULT 300",
        ),
        (
            "desktop_automation_runs",
            "max_retries",
            "INTEGER NOT NULL DEFAULT 0",
        ),
        ("desktop_automation_runs", "deadline_at_ms", "INTEGER"),
        ("desktop_automation_runs", "result_summary_json", "TEXT"),
        ("desktop_automation_runs", "event_count", "INTEGER"),
        ("desktop_automation_runs", "execution_time_ms", "INTEGER"),
    ] {
        ensure_column(connection, table, column, definition)?;
    }
    connection
        .execute_batch(
            "UPDATE desktop_automation_runs
             SET job_snapshot_json = COALESCE(
                   NULLIF(job_snapshot_json, '{}'),
                   (SELECT value_json FROM desktop_automation_jobs
                    WHERE desktop_automation_jobs.id = desktop_automation_runs.job_id
                      AND desktop_automation_jobs.project_id = desktop_automation_runs.project_id),
                   '{}'
                 ),
                 runtime_execution_id = COALESCE(
                   runtime_execution_id,
                   'local-automation-execution-' || id
                 ),
                 deadline_at_ms = COALESCE(
                   deadline_at_ms,
                   CAST(strftime('%s', accepted_at) AS INTEGER) * 1000
                     + timeout_seconds * 1000
                 );
             UPDATE desktop_automation_runs
             SET tenant_id = COALESCE(
                   json_extract(job_snapshot_json, '$.tenant_id'),
                   NULLIF(tenant_id, ''),
                   'local'
                 ),
                 actor_user_id = COALESCE(
                   json_extract(job_snapshot_json, '$.created_by'),
                   NULLIF(actor_user_id, ''),
                   ''
                 );",
        )
        .map_err(|error| error.to_string())?;
    recover_reopened_connection(connection, &SystemAutomationClock)
        .map(|_| ())
        .map_err(|error| format!("{error:?}"))
}

#[cfg(test)]
pub(super) fn recover_connection(
    connection: &Connection,
    clock: &dyn AutomationClock,
) -> Result<AutomationStartupRecovery, AutomationLedgerError> {
    let transaction = connection.unchecked_transaction().map_err(storage)?;
    reconcile_schedule_state(&transaction, clock.now())?;
    let recovered = recover_transaction(&transaction, clock.now())?;
    transaction.commit().map_err(storage)?;
    Ok(recovered)
}

fn recover_reopened_connection(
    connection: &Connection,
    clock: &dyn AutomationClock,
) -> Result<AutomationStartupRecovery, AutomationLedgerError> {
    let transaction = connection.unchecked_transaction().map_err(storage)?;
    let now = clock.now();
    reconcile_schedule_state(&transaction, now)?;
    let now_text = now.to_rfc3339();
    let requeued_runs = transaction
        .execute(
            "UPDATE desktop_automation_runs
             SET status = 'queued', error_code = ?1, finished_at = NULL, updated_at = ?2
             WHERE status = 'running' AND id IN (
               SELECT run_id FROM desktop_automation_operations WHERE status = 'running'
             )",
            params![RESTART_RECOVERY_REASON, now_text],
        )
        .map_err(storage)?;
    transaction
        .execute(
            "UPDATE desktop_automation_run_receipts
             SET status = 'queued'
             WHERE run_id IN (
               SELECT run_id FROM desktop_automation_operations WHERE status = 'running'
             )",
            [],
        )
        .map_err(storage)?;
    let recovered_operations = transaction
        .execute(
            "UPDATE desktop_automation_operations
             SET status = 'queued', available_at_ms = ?1,
                 lease_owner = NULL, lease_token = NULL, lease_expires_at_ms = NULL,
                 fence_token = fence_token + 1, last_error_code = ?2, updated_at = ?3
             WHERE status = 'running'",
            params![now.timestamp_millis(), RESTART_RECOVERY_REASON, now_text],
        )
        .map_err(storage)?;
    transaction.commit().map_err(storage)?;
    Ok(AutomationStartupRecovery {
        expired_operations: recovered_operations,
        requeued_runs,
    })
}

pub(super) fn recover_transaction(
    transaction: &Transaction<'_>,
    now: chrono::DateTime<chrono::Utc>,
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
    transaction
        .execute(
            "UPDATE desktop_automation_run_receipts
             SET status = 'queued'
             WHERE run_id IN (
               SELECT run_id FROM desktop_automation_operations
               WHERE status = 'running'
                 AND (lease_expires_at_ms IS NULL OR lease_expires_at_ms <= ?1)
             )",
            [now_ms],
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
