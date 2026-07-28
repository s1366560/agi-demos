use chrono::{DateTime, TimeDelta, Utc};
use rusqlite::{params, Connection, OptionalExtension, Transaction};
use serde_json::Value;

use super::automation_dispatcher::{
    AutomationLedgerError, AutomationRunReceipt, AutomationRunStatus, ManualRunCommand,
};

pub(super) fn replay_receipt(
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

pub(super) fn read_job(
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

pub(super) fn ensure_column(
    connection: &Connection,
    table: &str,
    column: &str,
    definition: &str,
) -> Result<(), String> {
    let exists = connection
        .query_row(
            "SELECT EXISTS(
               SELECT 1 FROM pragma_table_info(?1) WHERE name = ?2
             )",
            params![table, column],
            |row| row.get::<_, bool>(0),
        )
        .map_err(|error| error.to_string())?;
    if exists {
        return Ok(());
    }
    connection
        .execute_batch(&format!(
            "ALTER TABLE {table} ADD COLUMN {column} {definition};"
        ))
        .map_err(|error| error.to_string())
}

pub(super) fn required_string<'a>(
    value: &'a Value,
    field: &str,
) -> Result<&'a str, AutomationLedgerError> {
    value
        .get(field)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| {
            AutomationLedgerError::InvalidRecord(format!("{field} must be a non-empty string"))
        })
}

pub(super) fn required_u64(value: &Value, field: &str) -> Result<u64, AutomationLedgerError> {
    value
        .get(field)
        .and_then(Value::as_u64)
        .ok_or_else(|| AutomationLedgerError::InvalidRecord(format!("{field} must be an integer")))
}

pub(super) fn deadline_at(
    accepted_at: DateTime<Utc>,
    timeout_seconds: u64,
) -> Result<DateTime<Utc>, AutomationLedgerError> {
    let timeout_seconds = i64::try_from(timeout_seconds).map_err(|_| {
        AutomationLedgerError::InvalidRecord("automation timeout is too large".into())
    })?;
    accepted_at
        .checked_add_signed(TimeDelta::seconds(timeout_seconds))
        .ok_or_else(|| AutomationLedgerError::InvalidRecord("automation deadline overflow".into()))
}

pub(super) fn parse_timestamp(value: &str) -> Result<DateTime<Utc>, AutomationLedgerError> {
    DateTime::parse_from_rfc3339(value)
        .map(|value| value.with_timezone(&Utc))
        .map_err(|_| AutomationLedgerError::InvalidRecord("timestamp is invalid".into()))
}

pub(super) fn parse_status(value: &str) -> Result<AutomationRunStatus, AutomationLedgerError> {
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

pub(super) fn storage(error: rusqlite::Error) -> AutomationLedgerError {
    AutomationLedgerError::Storage(error.to_string())
}

pub(super) fn invalid_record(error: serde_json::Error) -> AutomationLedgerError {
    AutomationLedgerError::InvalidRecord(error.to_string())
}
