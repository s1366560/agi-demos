//! Transaction helpers for the cron runtime terminal projector.

use chrono::{DateTime, Duration, SecondsFormat, Utc};
use serde_json::{json, Map, Value};
use sqlx::{FromRow, Postgres, Transaction};

use crate::cron_runtime_types::{
    AutomationRunContext, AutomationRunLease, AutomationRunStatus,
    AutomationRuntimeRepositoryError, AutomationRuntimeScope, AutomationTerminalOutcome,
};

const FAILURE_BACKOFF_SECONDS: &[i64] = &[30, 60, 300, 900, 3_600];

#[derive(Debug, FromRow)]
pub(crate) struct ExpiredRunRow {
    pub(crate) run_id: String,
    pub(crate) runtime_execution_id: Option<String>,
    pub(crate) conversation_id: Option<String>,
    pub(crate) run_status: String,
    pub(crate) job_id: String,
    pub(crate) actor_user_id: Option<String>,
    pub(crate) actor_api_key_id: Option<String>,
    pub(crate) input_json: Value,
    pub(crate) created_by: Option<String>,
    pub(crate) payload_type: String,
    pub(crate) payload_config: Value,
    pub(crate) timeout_seconds: i32,
}

#[derive(Debug, FromRow)]
pub(crate) struct LockedRunRow {
    pub(crate) status: String,
    pub(crate) runtime_revision: i64,
    pub(crate) runtime_lease_owner: Option<String>,
    pub(crate) runtime_lease_token: Option<String>,
    pub(crate) runtime_lease_expires_at: Option<DateTime<Utc>>,
    pub(crate) deadline_at: Option<DateTime<Utc>>,
}

#[derive(Debug, FromRow)]
pub(crate) struct LockedJobRow {
    pub(crate) state: Value,
    max_retries: i32,
    delete_after_run: bool,
    schedule_type: String,
}

#[derive(Debug, FromRow)]
pub(crate) struct LockedOperationRow {
    pub(crate) id: String,
    pub(crate) status: String,
    pub(crate) input_json: Value,
}

pub(crate) fn context_from_expired(
    scope: &AutomationRuntimeScope,
    row: ExpiredRunRow,
) -> Result<AutomationRunContext, AutomationRuntimeRepositoryError> {
    let runtime_execution_id = row
        .runtime_execution_id
        .filter(|value| value == &row.run_id)
        .ok_or(AutomationRuntimeRepositoryError::InvalidRunState)?;
    Ok(AutomationRunContext {
        tenant_id: scope.tenant_id.clone(),
        project_id: scope.project_id.clone(),
        job_id: row.job_id,
        run_id: row.run_id,
        runtime_execution_id,
        conversation_id: row
            .conversation_id
            .ok_or(AutomationRuntimeRepositoryError::InvalidConversation)?,
        actor_user_id: row
            .actor_user_id
            .or(row.created_by)
            .ok_or(AutomationRuntimeRepositoryError::MissingActor)?,
        actor_api_key_id: row.actor_api_key_id,
        payload: super::cron_runtime_repo::payload_from_parts(
            &row.payload_type,
            &row.payload_config,
        )?,
        timeout_seconds: super::cron_runtime_repo::timeout_snapshot(
            &row.input_json,
            row.timeout_seconds,
        ),
        status: AutomationRunStatus::try_from(row.run_status.as_str())?,
    })
}

pub(crate) async fn lock_run(
    tx: &mut Transaction<'_, Postgres>,
    context: &AutomationRunContext,
) -> Result<Option<LockedRunRow>, AutomationRuntimeRepositoryError> {
    sqlx::query_as::<_, LockedRunRow>(
        "SELECT run.status, run.runtime_revision, run.runtime_lease_owner, \
                run.runtime_lease_token, run.runtime_lease_expires_at, run.deadline_at \
         FROM cron_job_runs AS run \
         WHERE run.id = $1 AND run.runtime_execution_id = $2 \
           AND run.project_id = $3 AND run.job_id = $4 \
         FOR UPDATE OF run",
    )
    .bind(&context.run_id)
    .bind(&context.runtime_execution_id)
    .bind(&context.project_id)
    .bind(&context.job_id)
    .fetch_optional(&mut **tx)
    .await
    .map_err(storage)
}

pub(crate) async fn lock_job(
    tx: &mut Transaction<'_, Postgres>,
    context: &AutomationRunContext,
) -> Result<LockedJobRow, AutomationRuntimeRepositoryError> {
    sqlx::query_as::<_, LockedJobRow>(
        "SELECT state, max_retries, delete_after_run, schedule_type \
         FROM cron_jobs WHERE id = $1 AND tenant_id = $2 AND project_id = $3 FOR UPDATE",
    )
    .bind(&context.job_id)
    .bind(&context.tenant_id)
    .bind(&context.project_id)
    .fetch_optional(&mut **tx)
    .await
    .map_err(storage)?
    .ok_or(AutomationRuntimeRepositoryError::NotFound)
}

pub(crate) async fn lock_operation(
    tx: &mut Transaction<'_, Postgres>,
    context: &AutomationRunContext,
) -> Result<LockedOperationRow, AutomationRuntimeRepositoryError> {
    sqlx::query_as::<_, LockedOperationRow>(
        "SELECT id, status, input_json FROM agistack_cron_operations \
         WHERE tenant_id = $1 AND project_id = $2 AND job_id = $3 \
           AND run_id = $4 AND operation_kind = 'execute_run' FOR UPDATE",
    )
    .bind(&context.tenant_id)
    .bind(&context.project_id)
    .bind(&context.job_id)
    .bind(&context.run_id)
    .fetch_optional(&mut **tx)
    .await
    .map_err(storage)?
    .ok_or(AutomationRuntimeRepositoryError::NotFound)
}

pub(crate) fn validate_terminal_authority(
    run: &LockedRunRow,
    lease: Option<&AutomationRunLease>,
    outcome: AutomationTerminalOutcome,
    observed_at: DateTime<Utc>,
) -> Result<(), AutomationRuntimeRepositoryError> {
    if outcome == AutomationTerminalOutcome::Timeout && lease.is_none() {
        return match run.deadline_at {
            Some(deadline) if deadline <= observed_at => Ok(()),
            _ => Err(AutomationRuntimeRepositoryError::LeaseLost),
        };
    }
    let lease = lease.ok_or(AutomationRuntimeRepositoryError::LeaseLost)?;
    let valid = run.runtime_revision == lease.runtime_revision
        && run.runtime_lease_owner.as_deref() == Some(lease.lease_owner.as_str())
        && run.runtime_lease_token.as_deref() == Some(lease.lease_token.as_str())
        && run
            .runtime_lease_expires_at
            .is_some_and(|expires_at| expires_at > observed_at);
    valid
        .then_some(())
        .ok_or(AutomationRuntimeRepositoryError::LeaseLost)
}

#[derive(Debug)]
pub(crate) struct RuntimePolicy {
    pub(crate) delete_after_run: bool,
    pub(crate) one_shot: bool,
    pub(crate) disable_after_failure: bool,
}

pub(crate) fn operation_policy(input: &Value, job: &LockedJobRow) -> RuntimePolicy {
    let max_retries = input
        .get("max_retries")
        .and_then(Value::as_i64)
        .and_then(|value| i32::try_from(value).ok())
        .unwrap_or(job.max_retries)
        .max(1);
    let consecutive = job
        .state
        .get("consecutive_errors")
        .and_then(Value::as_i64)
        .unwrap_or(0);
    RuntimePolicy {
        delete_after_run: input
            .get("delete_after_run")
            .and_then(Value::as_bool)
            .unwrap_or(job.delete_after_run),
        one_shot: input
            .get("one_shot")
            .and_then(Value::as_bool)
            .unwrap_or(job.schedule_type == "at"),
        disable_after_failure: consecutive + 1 >= i64::from(max_retries),
    }
}

pub(crate) fn next_job_state(
    current: &Value,
    outcome: AutomationTerminalOutcome,
    error_code: Option<&str>,
    observed_at: DateTime<Utc>,
    policy: &RuntimePolicy,
) -> Value {
    let mut state = current.as_object().cloned().unwrap_or_default();
    state.insert(
        "last_run_at".to_string(),
        Value::String(observed_at.to_rfc3339_opts(SecondsFormat::Micros, true)),
    );
    state.insert(
        "last_run_status".to_string(),
        Value::String(outcome.status().as_str().to_string()),
    );
    if outcome == AutomationTerminalOutcome::Success {
        state.insert("consecutive_errors".to_string(), json!(0));
        state.remove("backoff_until");
        state.remove("last_error");
        if policy.delete_after_run || policy.one_shot {
            state.insert(
                "retired_at".to_string(),
                Value::String(observed_at.to_rfc3339_opts(SecondsFormat::Micros, true)),
            );
            state.insert(
                "retired_reason".to_string(),
                Value::String(if policy.one_shot {
                    "one_shot".to_string()
                } else {
                    "delete_after_run".to_string()
                }),
            );
        }
    } else if outcome.counts_as_failure() {
        let consecutive = state
            .get("consecutive_errors")
            .and_then(Value::as_i64)
            .unwrap_or(0)
            + 1;
        state.insert("consecutive_errors".to_string(), json!(consecutive));
        if let Some(error_code) = error_code {
            state.insert(
                "last_error".to_string(),
                Value::String(error_code.to_string()),
            );
        }
        let index = usize::try_from(consecutive.saturating_sub(1))
            .unwrap_or(usize::MAX)
            .min(FAILURE_BACKOFF_SECONDS.len() - 1);
        state.insert(
            "backoff_until".to_string(),
            Value::String(
                (observed_at + Duration::seconds(FAILURE_BACKOFF_SECONDS[index]))
                    .to_rfc3339_opts(SecondsFormat::Micros, true),
            ),
        );
    }
    Value::Object(state)
}

pub(crate) fn terminal_summary(
    context: &AutomationRunContext,
    status: AutomationRunStatus,
    error_code: Option<&str>,
    event_count: u64,
    execution_time_ms: u64,
) -> Value {
    let mut summary = Map::from_iter([
        (
            "conversation_id".to_string(),
            Value::String(context.conversation_id.clone()),
        ),
        (
            "runtime_execution_id".to_string(),
            Value::String(context.runtime_execution_id.clone()),
        ),
        (
            "runtime_status".to_string(),
            Value::String(status.as_str().to_string()),
        ),
        ("event_count".to_string(), json!(event_count)),
        ("execution_time_ms".to_string(), json!(execution_time_ms)),
    ]);
    if let Some(error_code) = error_code {
        summary.insert(
            "error_code".to_string(),
            Value::String(error_code.to_string()),
        );
    }
    Value::Object(summary)
}

fn storage(error: sqlx::Error) -> AutomationRuntimeRepositoryError {
    AutomationRuntimeRepositoryError::Storage(error.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn success_clears_failure_state_and_retires_delete_after_jobs() {
        let now = DateTime::parse_from_rfc3339("2026-07-14T12:00:00Z")
            .expect("time")
            .with_timezone(&Utc);
        let policy = RuntimePolicy {
            delete_after_run: true,
            one_shot: false,
            disable_after_failure: false,
        };
        let state = next_job_state(
            &json!({"consecutive_errors": 2, "last_error": "execution_failed"}),
            AutomationTerminalOutcome::Success,
            None,
            now,
            &policy,
        );
        assert_eq!(state["consecutive_errors"], 0);
        assert_eq!(state["retired_reason"], "delete_after_run");
        assert!(state.get("last_error").is_none());
    }

    #[test]
    fn failure_accounting_is_arithmetic_and_stores_only_stable_code() {
        let now = DateTime::parse_from_rfc3339("2026-07-14T12:00:00Z")
            .expect("time")
            .with_timezone(&Utc);
        let policy = RuntimePolicy {
            delete_after_run: false,
            one_shot: false,
            disable_after_failure: false,
        };
        let state = next_job_state(
            &json!({"consecutive_errors": 1}),
            AutomationTerminalOutcome::Timeout,
            Some("execution_timed_out"),
            now,
            &policy,
        );
        assert_eq!(state["consecutive_errors"], 2);
        assert_eq!(state["last_error"], "execution_timed_out");
        assert!(state["backoff_until"].as_str().is_some());
    }
}
