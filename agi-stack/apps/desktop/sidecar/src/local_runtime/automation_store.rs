use rusqlite::{params, Connection, OptionalExtension, Transaction};
use serde_json::Value;

use super::session_store::DesktopSessionStore;

#[derive(Debug, PartialEq, Eq)]
pub(super) enum AutomationStoreError {
    NotFound,
    RevisionConflict { expected: u64, actual: u64 },
    IdempotencyConflict,
    InvalidRecord(String),
    Storage(String),
}

pub(super) struct AutomationMutation {
    pub(super) value: Value,
    pub(super) replayed: bool,
}

pub(super) fn initialize_schema(connection: &Connection) -> Result<(), String> {
    connection
        .execute_batch(
            "CREATE TABLE IF NOT EXISTS desktop_automation_jobs (
               id TEXT PRIMARY KEY,
               project_id TEXT NOT NULL,
               enabled INTEGER NOT NULL,
               created_at TEXT NOT NULL,
               value_json TEXT NOT NULL
             );
             CREATE TABLE IF NOT EXISTS desktop_automation_mutations (
               user_id TEXT NOT NULL,
               project_id TEXT NOT NULL,
               operation TEXT NOT NULL,
               idempotency_key TEXT NOT NULL,
               request_hash TEXT NOT NULL,
               response_json TEXT NOT NULL,
               created_at TEXT NOT NULL,
               PRIMARY KEY(user_id, project_id, operation, idempotency_key)
             );
             CREATE INDEX IF NOT EXISTS idx_desktop_automation_jobs_project
               ON desktop_automation_jobs(project_id, enabled, created_at DESC);
             CREATE INDEX IF NOT EXISTS idx_desktop_automation_mutations_scope
               ON desktop_automation_mutations(user_id, project_id, created_at DESC);",
        )
        .map_err(|error| error.to_string())?;
    super::automation_dispatcher::initialize_schema(connection)
}

pub(super) fn list(
    store: &DesktopSessionStore,
    project_id: &str,
    include_disabled: bool,
    limit: i64,
    offset: i64,
) -> Result<(Vec<Value>, i64), AutomationStoreError> {
    let connection = store.connection().map_err(AutomationStoreError::Storage)?;
    let enabled_filter = i64::from(!include_disabled);
    let total = connection
        .query_row(
            "SELECT COUNT(*) FROM desktop_automation_jobs
             WHERE project_id = ?1 AND (?2 = 0 OR enabled = 1)",
            params![project_id, enabled_filter],
            |row| row.get(0),
        )
        .map_err(storage)?;
    let mut statement = connection
        .prepare(&format!(
            "{JOB_PROJECTION_SQL}
             WHERE job.project_id = ?1 AND (?2 = 0 OR job.enabled = 1)
             ORDER BY job.created_at DESC, job.id ASC LIMIT ?3 OFFSET ?4"
        ))
        .map_err(storage)?;
    let items = statement
        .query_map(
            params![project_id, enabled_filter, limit, offset],
            decode_job_projection,
        )
        .map_err(storage)?
        .collect::<Result<Vec<_>, _>>()
        .map_err(storage)?;
    Ok((items, total))
}

pub(super) fn get(
    store: &DesktopSessionStore,
    project_id: &str,
    automation_id: &str,
) -> Result<Value, AutomationStoreError> {
    let connection = store.connection().map_err(AutomationStoreError::Storage)?;
    connection
        .query_row(
            &format!("{JOB_PROJECTION_SQL} WHERE job.id = ?1 AND job.project_id = ?2"),
            params![automation_id, project_id],
            decode_job_projection,
        )
        .optional()
        .map_err(storage)?
        .ok_or(AutomationStoreError::NotFound)
}

pub(super) fn create(
    store: &DesktopSessionStore,
    user_id: &str,
    project_id: &str,
    idempotency_key: &str,
    request_hash: &str,
    job: &Value,
    now: &str,
) -> Result<AutomationMutation, AutomationStoreError> {
    let mut connection = store.connection().map_err(AutomationStoreError::Storage)?;
    let transaction = connection.transaction().map_err(storage)?;
    if let Some(value) = replay_receipt(
        &transaction,
        user_id,
        project_id,
        "create",
        idempotency_key,
        request_hash,
    )? {
        return Ok(AutomationMutation {
            value,
            replayed: true,
        });
    }
    let id = required_string(job, "id")?;
    let enabled = required_bool(job, "enabled")?;
    let created_at = required_string(job, "created_at")?;
    let encoded = serde_json::to_string(job).map_err(invalid_record)?;
    transaction
        .execute(
            "INSERT INTO desktop_automation_jobs(id, project_id, enabled, created_at, value_json)
             VALUES (?1, ?2, ?3, ?4, ?5)",
            params![id, project_id, enabled, created_at, encoded],
        )
        .map_err(storage)?;
    store_receipt(
        &transaction,
        user_id,
        project_id,
        "create",
        idempotency_key,
        request_hash,
        job,
        now,
    )?;
    transaction.commit().map_err(storage)?;
    Ok(AutomationMutation {
        value: job.clone(),
        replayed: false,
    })
}

#[allow(clippy::too_many_arguments)]
pub(super) fn update<F>(
    store: &DesktopSessionStore,
    user_id: &str,
    project_id: &str,
    automation_id: &str,
    operation: &str,
    idempotency_key: &str,
    request_hash: &str,
    expected_revision: u64,
    now: &str,
    mutate: F,
) -> Result<AutomationMutation, AutomationStoreError>
where
    F: FnOnce(&mut Value) -> Result<(), AutomationStoreError>,
{
    let mut connection = store.connection().map_err(AutomationStoreError::Storage)?;
    let transaction = connection.transaction().map_err(storage)?;
    if let Some(value) = replay_receipt(
        &transaction,
        user_id,
        project_id,
        operation,
        idempotency_key,
        request_hash,
    )? {
        return Ok(AutomationMutation {
            value,
            replayed: true,
        });
    }
    let mut job =
        read_job(&transaction, project_id, automation_id)?.ok_or(AutomationStoreError::NotFound)?;
    let actual_revision = required_u64(&job, "revision")?;
    if actual_revision != expected_revision {
        return Err(AutomationStoreError::RevisionConflict {
            expected: expected_revision,
            actual: actual_revision,
        });
    }
    mutate(&mut job)?;
    let object = job.as_object_mut().ok_or_else(|| {
        AutomationStoreError::InvalidRecord("automation must be an object".into())
    })?;
    object.insert("revision".into(), Value::from(actual_revision + 1));
    object.insert("updated_at".into(), Value::from(now));
    let enabled = required_bool(&job, "enabled")?;
    let encoded = serde_json::to_string(&job).map_err(invalid_record)?;
    transaction
        .execute(
            "UPDATE desktop_automation_jobs SET enabled = ?1, value_json = ?2
             WHERE id = ?3 AND project_id = ?4",
            params![enabled, encoded, automation_id, project_id],
        )
        .map_err(storage)?;
    store_receipt(
        &transaction,
        user_id,
        project_id,
        operation,
        idempotency_key,
        request_hash,
        &job,
        now,
    )?;
    transaction.commit().map_err(storage)?;
    Ok(AutomationMutation {
        value: job,
        replayed: false,
    })
}

#[allow(clippy::too_many_arguments)]
pub(super) fn delete(
    store: &DesktopSessionStore,
    user_id: &str,
    project_id: &str,
    automation_id: &str,
    idempotency_key: &str,
    request_hash: &str,
    expected_revision: u64,
    now: &str,
) -> Result<bool, AutomationStoreError> {
    let operation = format!("delete:{automation_id}");
    let mut connection = store.connection().map_err(AutomationStoreError::Storage)?;
    let transaction = connection.transaction().map_err(storage)?;
    if replay_receipt(
        &transaction,
        user_id,
        project_id,
        &operation,
        idempotency_key,
        request_hash,
    )?
    .is_some()
    {
        return Ok(true);
    }
    let job =
        read_job(&transaction, project_id, automation_id)?.ok_or(AutomationStoreError::NotFound)?;
    let actual_revision = required_u64(&job, "revision")?;
    if actual_revision != expected_revision {
        return Err(AutomationStoreError::RevisionConflict {
            expected: expected_revision,
            actual: actual_revision,
        });
    }
    transaction
        .execute(
            "DELETE FROM desktop_automation_jobs WHERE id = ?1 AND project_id = ?2",
            params![automation_id, project_id],
        )
        .map_err(storage)?;
    store_receipt(
        &transaction,
        user_id,
        project_id,
        &operation,
        idempotency_key,
        request_hash,
        &serde_json::json!({ "deleted": true }),
        now,
    )?;
    transaction.commit().map_err(storage)?;
    Ok(false)
}

fn read_job(
    connection: &Connection,
    project_id: &str,
    automation_id: &str,
) -> Result<Option<Value>, AutomationStoreError> {
    let encoded = connection
        .query_row(
            "SELECT value_json FROM desktop_automation_jobs WHERE id = ?1 AND project_id = ?2",
            params![automation_id, project_id],
            |row| row.get::<_, String>(0),
        )
        .optional()
        .map_err(storage)?;
    encoded
        .map(|value| serde_json::from_str(&value).map_err(invalid_record))
        .transpose()
}

fn replay_receipt(
    transaction: &Transaction<'_>,
    user_id: &str,
    project_id: &str,
    operation: &str,
    idempotency_key: &str,
    request_hash: &str,
) -> Result<Option<Value>, AutomationStoreError> {
    let receipt = transaction
        .query_row(
            "SELECT request_hash, response_json FROM desktop_automation_mutations
             WHERE user_id = ?1 AND project_id = ?2 AND operation = ?3 AND idempotency_key = ?4",
            params![user_id, project_id, operation, idempotency_key],
            |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?)),
        )
        .optional()
        .map_err(storage)?;
    match receipt {
        Some((stored_hash, _)) if stored_hash != request_hash => {
            Err(AutomationStoreError::IdempotencyConflict)
        }
        Some((_, response)) => serde_json::from_str(&response)
            .map(Some)
            .map_err(invalid_record),
        None => Ok(None),
    }
}

#[allow(clippy::too_many_arguments)]
fn store_receipt(
    transaction: &Transaction<'_>,
    user_id: &str,
    project_id: &str,
    operation: &str,
    idempotency_key: &str,
    request_hash: &str,
    response: &Value,
    now: &str,
) -> Result<(), AutomationStoreError> {
    let response_json = serde_json::to_string(response).map_err(invalid_record)?;
    transaction
        .execute(
            "INSERT INTO desktop_automation_mutations
             (user_id, project_id, operation, idempotency_key, request_hash, response_json, created_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
            params![
                user_id,
                project_id,
                operation,
                idempotency_key,
                request_hash,
                response_json,
                now
            ],
        )
        .map_err(storage)?;
    Ok(())
}

fn required_string(value: &Value, field: &str) -> Result<String, AutomationStoreError> {
    value
        .get(field)
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
        .ok_or_else(|| AutomationStoreError::InvalidRecord(format!("{field} must be a string")))
}

fn required_bool(value: &Value, field: &str) -> Result<bool, AutomationStoreError> {
    value
        .get(field)
        .and_then(Value::as_bool)
        .ok_or_else(|| AutomationStoreError::InvalidRecord(format!("{field} must be a boolean")))
}

fn required_u64(value: &Value, field: &str) -> Result<u64, AutomationStoreError> {
    value
        .get(field)
        .and_then(Value::as_u64)
        .ok_or_else(|| AutomationStoreError::InvalidRecord(format!("{field} must be an integer")))
}

fn storage(error: rusqlite::Error) -> AutomationStoreError {
    AutomationStoreError::Storage(error.to_string())
}

fn invalid_record(error: serde_json::Error) -> AutomationStoreError {
    AutomationStoreError::InvalidRecord(error.to_string())
}

// Read runtime projections without changing job revisions or immutable mutation receipts.
const JOB_PROJECTION_SQL: &str = "
    SELECT job.value_json, schedule.next_fire_at,
      (SELECT COUNT(*) FROM desktop_automation_runs AS run
       WHERE run.job_id = job.id AND run.project_id = job.project_id
         AND run.tenant_id = json_extract(job.value_json, '$.tenant_id')
         AND run.status = 'skipped'
         AND run.error_code = 'local_automation_app_was_not_running'),
      last_run.finished_at, last_run.status
    FROM desktop_automation_jobs AS job
    LEFT JOIN desktop_automation_schedule_state AS schedule
      ON schedule.job_id = job.id AND schedule.project_id = job.project_id
    LEFT JOIN desktop_automation_runs AS last_run ON last_run.id = (
      SELECT run.id FROM desktop_automation_runs AS run
      WHERE run.job_id = job.id AND run.project_id = job.project_id
        AND run.tenant_id = json_extract(job.value_json, '$.tenant_id')
        AND run.finished_at IS NOT NULL
        AND run.status IN ('success', 'failed', 'timeout', 'cancelled', 'skipped')
      ORDER BY run.finished_at DESC, run.id ASC LIMIT 1)";

fn decode_job_projection(row: &rusqlite::Row<'_>) -> rusqlite::Result<Value> {
    let encoded: String = row.get(0)?;
    let mut job: Value = serde_json::from_str(&encoded).map_err(|error| {
        rusqlite::Error::FromSqlConversionFailure(0, rusqlite::types::Type::Text, Box::new(error))
    })?;
    let next_fire_at: Option<String> = row.get(1)?;
    let missed_run_count: u64 = row.get(2)?;
    let last_run_at: Option<String> = row.get(3)?;
    let last_run_status: Option<String> = row.get(4)?;
    let Some(state) = job.get_mut("state").and_then(Value::as_object_mut) else {
        return Err(rusqlite::Error::InvalidQuery);
    };
    if let (Some(at), Some(status)) = (last_run_at, last_run_status) {
        state.insert("last_run_at".into(), Value::from(at));
        state.insert("last_run_status".into(), Value::from(status));
    } else {
        state.remove("last_run_at");
        state.remove("last_run_status");
    }
    state.insert("execution_target".into(), Value::from("local"));
    state.insert("missed_run_count".into(), Value::from(missed_run_count));
    state.insert(
        "next_run_at".into(),
        next_fire_at.map_or(Value::Null, Value::from),
    );
    Ok(job)
}
