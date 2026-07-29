use chrono::{DateTime, Utc};
use rusqlite::{params, OptionalExtension, Transaction, TransactionBehavior};
use serde_json::Value;
use uuid::Uuid;

use super::{
    automation_dispatcher::{
        AutomationClock, AutomationLedgerError, AutomationScheduleDispatchSummary,
    },
    automation_ledger_support::{
        deadline_at, invalid_record, parse_timestamp, read_job, required_string, required_u64,
        storage,
    },
    automation_schedule::project_job_schedule,
    session_store::DesktopSessionStore,
};

const SCHEDULE_INVALID_REASON: &str = "local_automation_schedule_invalid";
const SCHEDULE_FIRE_NAMESPACE: Uuid = Uuid::from_u128(0x395e_6727_185a_4b2e_8f5d_3f76_9bb9_27fb);

pub(super) fn dispatch_due_schedules(
    store: &DesktopSessionStore,
    clock: &dyn AutomationClock,
    limit: usize,
) -> Result<AutomationScheduleDispatchSummary, AutomationLedgerError> {
    if limit == 0 || limit > 256 {
        return Err(AutomationLedgerError::InvalidRecord(
            "schedule dispatch limit must be between 1 and 256".into(),
        ));
    }
    let mut connection = store.connection().map_err(AutomationLedgerError::Storage)?;
    let transaction = connection
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(storage)?;
    let now = clock.now();
    reconcile_schedule_state(&transaction, now)?;
    let mut statement = transaction
        .prepare(
            "SELECT job_id, project_id, schedule_revision, next_fire_at,
                    schedule_fingerprint
             FROM desktop_automation_schedule_state
             WHERE enabled = 1 AND availability = 'active'
               AND next_fire_at IS NOT NULL AND next_fire_at <= ?1
             ORDER BY next_fire_at ASC, job_id ASC LIMIT ?2",
        )
        .map_err(storage)?;
    let candidates = statement
        .query_map(params![now.to_rfc3339(), limit], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, u64>(2)?,
                row.get::<_, String>(3)?,
                row.get::<_, String>(4)?,
            ))
        })
        .map_err(storage)?
        .collect::<Result<Vec<_>, _>>()
        .map_err(storage)?;
    drop(statement);

    let mut summary = AutomationScheduleDispatchSummary {
        due: candidates.len(),
        enqueued: 0,
    };
    for (job_id, project_id, schedule_revision, scheduled_for_text, fingerprint) in candidates {
        let Some(job) = read_job(&transaction, &project_id, &job_id)? else {
            continue;
        };
        if job.get("schedule_revision").and_then(Value::as_u64) != Some(schedule_revision) {
            continue;
        }
        if !has_explicit_execution_target(&job) {
            transaction
                .execute(
                    "UPDATE desktop_automation_schedule_state
                     SET next_fire_at = NULL, availability = 'unavailable',
                         reason_code = 'local_automation_workspace_required', updated_at = ?1
                     WHERE job_id = ?2 AND project_id = ?3 AND schedule_revision = ?4",
                    params![now.to_rfc3339(), job_id, project_id, schedule_revision],
                )
                .map_err(storage)?;
            continue;
        }
        let scheduled_for = parse_timestamp(&scheduled_for_text)?;
        let next = project_job_schedule(&job, scheduled_for)
            .map_err(|_| AutomationLedgerError::InvalidRecord("schedule is invalid".into()))?;
        if next.fingerprint != fingerprint {
            continue;
        }
        let occurrence_key = format!("scheduled:{schedule_revision}:{scheduled_for_text}");
        let next_fire_at = next.next_fire_at.map(|value| value.to_rfc3339());
        let advanced = transaction
            .execute(
                "UPDATE desktop_automation_schedule_state
                 SET next_fire_at = ?1, last_occurrence_key = ?2,
                     availability = ?3, reason_code = ?4, updated_at = ?5
                 WHERE job_id = ?6 AND project_id = ?7 AND schedule_revision = ?8
                   AND schedule_fingerprint = ?9 AND next_fire_at = ?10",
                params![
                    next_fire_at,
                    occurrence_key,
                    next.availability,
                    next.reason_code,
                    now.to_rfc3339(),
                    job_id,
                    project_id,
                    schedule_revision,
                    fingerprint,
                    scheduled_for_text,
                ],
            )
            .map_err(storage)?;
        if advanced != 1 {
            continue;
        }
        let cursor = format!(
            "{}:{}:{}:{}",
            required_string(&job, "tenant_id")?,
            project_id,
            job_id,
            scheduled_for_text
        );
        let run_id =
            Uuid::new_v5(&SCHEDULE_FIRE_NAMESPACE, format!("run:{cursor}").as_bytes()).to_string();
        let receipt_id = Uuid::new_v5(
            &SCHEDULE_FIRE_NAMESPACE,
            format!("receipt:{cursor}").as_bytes(),
        )
        .to_string();
        let operation_id = Uuid::new_v5(
            &SCHEDULE_FIRE_NAMESPACE,
            format!("operation:{cursor}").as_bytes(),
        )
        .to_string();
        if insert_scheduled_run(
            &transaction,
            &job,
            &run_id,
            &receipt_id,
            &operation_id,
            &occurrence_key,
            scheduled_for,
            now,
        )? {
            summary.enqueued += 1;
        }
    }
    transaction.commit().map_err(storage)?;
    Ok(summary)
}

fn has_explicit_execution_target(job: &Value) -> bool {
    ["workspace_id", "conversation_id"]
        .into_iter()
        .any(|field| {
            job.get(field)
                .and_then(Value::as_str)
                .is_some_and(|value| !value.trim().is_empty())
        })
}

#[allow(clippy::too_many_arguments)]
fn insert_scheduled_run(
    transaction: &Transaction<'_>,
    job: &Value,
    run_id: &str,
    receipt_id: &str,
    operation_id: &str,
    occurrence_key: &str,
    scheduled_for: DateTime<Utc>,
    observed_at: DateTime<Utc>,
) -> Result<bool, AutomationLedgerError> {
    let project_id = required_string(job, "project_id")?;
    let job_id = required_string(job, "id")?;
    let tenant_id = required_string(job, "tenant_id")?;
    let actor_user_id = required_string(job, "created_by")?;
    let job_revision = required_u64(job, "revision")?;
    let schedule_revision = required_u64(job, "schedule_revision")?;
    let timeout_seconds = job
        .get("timeout_seconds")
        .and_then(Value::as_u64)
        .unwrap_or(300);
    let max_retries = job
        .get("max_retries")
        .and_then(Value::as_u64)
        .unwrap_or_default();
    let conversation_id = job.get("conversation_id").and_then(Value::as_str);
    let job_snapshot_json = serde_json::to_string(job).map_err(invalid_record)?;
    let runtime_execution_id = format!("local-automation-execution-{run_id}");
    let accepted_at = observed_at.to_rfc3339();
    let scheduled_for_text = scheduled_for.to_rfc3339();
    let deadline_at_ms = deadline_at(observed_at, timeout_seconds)?.timestamp_millis();
    let inserted = transaction
        .execute(
            "INSERT OR IGNORE INTO desktop_automation_runs (
               id, receipt_id, project_id, job_id, job_revision, schedule_revision,
               trigger_type, status, tenant_id, actor_user_id, conversation_id, scheduled_for,
               runtime_execution_id, job_snapshot_json, timeout_seconds, max_retries,
               deadline_at_ms, accepted_at, updated_at
             ) VALUES (
               ?1, ?2, ?3, ?4, ?5, ?6, 'scheduled', 'queued', ?7, ?8, ?9, ?10,
               ?11, ?12, ?13, ?14, ?15, ?16, ?16
             )",
            params![
                run_id,
                receipt_id,
                project_id,
                job_id,
                job_revision,
                schedule_revision,
                tenant_id,
                actor_user_id,
                conversation_id,
                scheduled_for_text,
                runtime_execution_id,
                job_snapshot_json,
                timeout_seconds,
                max_retries,
                deadline_at_ms,
                accepted_at,
            ],
        )
        .map_err(storage)?;
    if inserted == 0 {
        return Ok(false);
    }
    transaction
        .execute(
            "INSERT INTO desktop_automation_operations (
               id, project_id, job_id, run_id, operation_kind, occurrence_key,
               status, available_at_ms, created_at, updated_at
             ) VALUES (?1, ?2, ?3, ?4, 'execute_run', ?5, 'queued', ?6, ?7, ?7)",
            params![
                operation_id,
                project_id,
                job_id,
                run_id,
                occurrence_key,
                observed_at.timestamp_millis(),
                accepted_at,
            ],
        )
        .map_err(storage)?;
    Ok(true)
}

pub(super) fn reconcile_schedule_state(
    transaction: &Transaction<'_>,
    now: DateTime<Utc>,
) -> Result<(), AutomationLedgerError> {
    let mut statement = transaction
        .prepare("SELECT value_json FROM desktop_automation_jobs ORDER BY id ASC")
        .map_err(storage)?;
    let jobs = statement
        .query_map([], |row| row.get::<_, String>(0))
        .map_err(storage)?
        .collect::<Result<Vec<_>, _>>()
        .map_err(storage)?;
    drop(statement);
    for encoded in jobs {
        let job: Value = serde_json::from_str(&encoded).map_err(invalid_record)?;
        let job_id = required_string(&job, "id")?;
        let project_id = required_string(&job, "project_id")?;
        let schedule_revision = required_u64(&job, "schedule_revision")?;
        let enabled = job.get("enabled").and_then(Value::as_bool).ok_or_else(|| {
            AutomationLedgerError::InvalidRecord("automation job enabled must be a boolean".into())
        })?;
        let projection = project_job_schedule(&job, now).ok();
        let existing = transaction
            .query_row(
                "SELECT schedule_revision, schedule_fingerprint, next_fire_at,
                        last_occurrence_key, availability, reason_code
                 FROM desktop_automation_schedule_state WHERE job_id = ?1",
                [&job_id],
                |row| {
                    Ok((
                        row.get::<_, u64>(0)?,
                        row.get::<_, Option<String>>(1)?,
                        row.get::<_, Option<String>>(2)?,
                        row.get::<_, Option<String>>(3)?,
                        row.get::<_, String>(4)?,
                        row.get::<_, Option<String>>(5)?,
                    ))
                },
            )
            .optional()
            .map_err(storage)?;
        let same_projection =
            existing
                .as_ref()
                .is_some_and(|(revision, fingerprint, _, _, _, _)| {
                    *revision == schedule_revision
                        && projection
                            .as_ref()
                            .is_some_and(|value| Some(&value.fingerprint) == fingerprint.as_ref())
                });
        let (next_fire_at, last_occurrence_key, fingerprint, availability, reason_code) =
            if same_projection {
                let (_, fingerprint, next_fire_at, last_occurrence_key, availability, reason_code) =
                    existing.expect("existing schedule projection");
                (
                    next_fire_at,
                    last_occurrence_key,
                    fingerprint,
                    availability,
                    reason_code,
                )
            } else if let Some(projection) = projection {
                (
                    projection.next_fire_at.map(|value| value.to_rfc3339()),
                    None,
                    Some(projection.fingerprint),
                    projection.availability.to_string(),
                    projection.reason_code.map(ToString::to_string),
                )
            } else {
                (
                    None,
                    None,
                    None,
                    "unavailable".to_string(),
                    Some(SCHEDULE_INVALID_REASON.to_string()),
                )
            };
        transaction
            .execute(
                "INSERT INTO desktop_automation_schedule_state (
                   job_id, project_id, schedule_revision, enabled, next_fire_at,
                   last_occurrence_key, schedule_fingerprint, availability, reason_code, updated_at
                 ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10)
                 ON CONFLICT(job_id) DO UPDATE SET
                   project_id = excluded.project_id,
                   schedule_revision = excluded.schedule_revision,
                   enabled = excluded.enabled,
                   next_fire_at = excluded.next_fire_at,
                   last_occurrence_key = excluded.last_occurrence_key,
                   schedule_fingerprint = excluded.schedule_fingerprint,
                   availability = excluded.availability,
                   reason_code = excluded.reason_code,
                   updated_at = excluded.updated_at",
                params![
                    job_id,
                    project_id,
                    schedule_revision,
                    enabled,
                    next_fire_at,
                    last_occurrence_key,
                    fingerprint,
                    availability,
                    reason_code,
                    now.to_rfc3339(),
                ],
            )
            .map_err(storage)?;
    }
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
