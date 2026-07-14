//! Atomic materialization of one due schedule cursor into an Agent run.

use std::fmt;

use serde_json::json;
use sqlx::types::chrono::{DateTime, Utc};

use agistack_core::ports::CoreError;

use crate::{
    CronOperationScope, CronScheduleProjection, CronScheduleSnapshot, CronScheduleStatus, PgPool,
};

const LIST_DUE_SQL: &str = "SELECT job.id AS job_id, job.tenant_id, job.project_id, \
    job.revision AS job_revision, job.schedule_revision, job.enabled, job.schedule_type, \
    job.schedule_config, job.timezone, job.stagger_seconds, job.created_at, \
    state.schedule_fingerprint, state.next_fire_at AS scheduled_for, \
    job.created_by AS actor_user_id, job.conversation_id, job.timeout_seconds, \
    job.max_retries, job.delete_after_run \
FROM agistack_cron_schedule_state AS state \
JOIN cron_jobs AS job ON job.id = state.job_id \
WHERE state.tenant_id = $1 AND state.project_id = $2 \
  AND state.status = 'active' AND state.next_fire_at IS NOT NULL \
  AND state.next_fire_at <= $3 \
  AND job.tenant_id = state.tenant_id AND job.project_id = state.project_id \
  AND job.schedule_revision = state.schedule_revision AND job.enabled IS TRUE \
ORDER BY state.next_fire_at, state.job_id LIMIT $4";

const LOCK_CURSOR_SQL: &str = "SELECT job.id \
FROM agistack_cron_schedule_state AS state \
JOIN cron_jobs AS job ON job.id = state.job_id \
WHERE state.job_id = $1 AND state.tenant_id = $2 AND state.project_id = $3 \
  AND state.status = 'active' AND state.schedule_revision = $4 \
  AND state.schedule_fingerprint = $5 AND state.next_fire_at = $6 \
  AND job.tenant_id = state.tenant_id AND job.project_id = state.project_id \
  AND job.revision = $7 AND job.schedule_revision = state.schedule_revision \
  AND job.enabled IS TRUE \
FOR UPDATE OF state, job";

/// Exact materialized cursor plus the immutable run policy needed to fire it.
#[derive(Debug, Clone, PartialEq)]
pub struct CronDueSchedule {
    pub snapshot: CronScheduleSnapshot,
    pub schedule_fingerprint: String,
    pub scheduled_for: DateTime<Utc>,
    pub actor_user_id: Option<String>,
    pub conversation_id: Option<String>,
    pub timeout_seconds: i32,
    pub max_retries: i32,
    pub delete_after_run: bool,
}

/// Deterministic identifiers supplied by the scheduler for one cursor.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NewCronScheduledFire {
    pub run_id: String,
    pub operation_id: String,
    pub idempotency_key: String,
}

/// Durable rows and cursor committed by one successful scheduled fire.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CronScheduledFireResult {
    pub run_id: String,
    pub operation_id: String,
    pub scheduled_for: DateTime<Utc>,
    pub schedule_status: CronScheduleStatus,
    pub next_fire_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CronScheduleFireError {
    InvalidCandidate,
    Storage(String),
}

impl fmt::Display for CronScheduleFireError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::InvalidCandidate => "cron scheduled fire candidate is invalid",
            Self::Storage(_) => "cron scheduled fire storage failed",
        })
    }
}

impl std::error::Error for CronScheduleFireError {}

#[derive(Clone)]
pub struct PgCronScheduleFireRepository {
    pool: PgPool,
}

impl PgCronScheduleFireRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    /// Read due candidates without claiming them. `commit_fire` performs the exact CAS.
    pub async fn list_due(
        &self,
        scope: CronOperationScope<'_>,
        now: DateTime<Utc>,
        limit: i64,
    ) -> Result<Vec<CronDueSchedule>, CronScheduleFireError> {
        if limit <= 0 {
            return Ok(Vec::new());
        }
        sqlx::query_as::<_, CronDueScheduleRow>(LIST_DUE_SQL)
            .bind(scope.tenant_id)
            .bind(scope.project_id)
            .bind(now)
            .bind(limit.clamp(1, 100))
            .fetch_all(&self.pool)
            .await
            .map_err(storage)?
            .into_iter()
            .map(TryInto::try_into)
            .collect()
    }

    /// Create the run and operation, then advance the exact cursor in one transaction.
    pub async fn commit_fire(
        &self,
        scope: CronOperationScope<'_>,
        candidate: &CronDueSchedule,
        next: &CronScheduleProjection,
        fire: &NewCronScheduledFire,
        observed_at: DateTime<Utc>,
    ) -> Result<Option<CronScheduledFireResult>, CronScheduleFireError> {
        validate_fire(scope, candidate, next, fire, observed_at)?;
        let actor_user_id = candidate
            .actor_user_id
            .as_deref()
            .ok_or(CronScheduleFireError::InvalidCandidate)?;
        let mut tx = self.pool.begin().await.map_err(storage)?;
        let locked = sqlx::query_scalar::<_, String>(LOCK_CURSOR_SQL)
            .bind(&candidate.snapshot.job_id)
            .bind(scope.tenant_id)
            .bind(scope.project_id)
            .bind(candidate.snapshot.schedule_revision)
            .bind(&candidate.schedule_fingerprint)
            .bind(candidate.scheduled_for)
            .bind(candidate.snapshot.job_revision)
            .fetch_optional(&mut *tx)
            .await
            .map_err(storage)?;
        if locked.is_none() {
            tx.rollback().await.map_err(storage)?;
            return Ok(None);
        }

        let max_retries = candidate.max_retries.max(1);
        let input_json = json!({
            "conversation_id": candidate.conversation_id,
            "runtime_execution_id": fire.run_id,
            "timeout_seconds": candidate.timeout_seconds.max(1),
            "delete_after_run": candidate.delete_after_run,
            "one_shot": candidate.snapshot.schedule_type == "at",
            "max_retries": max_retries,
        });
        sqlx::query(
            "INSERT INTO cron_job_runs ( \
                id, job_id, project_id, status, trigger_type, accepted_at, job_revision, \
                schedule_revision, scheduled_for, runtime_execution_id, idempotency_key, \
                request_receipt_id, started_at, result_summary, conversation_id \
             ) VALUES ( \
                $1,$2,$3,'queued','scheduled',$4,$5,$6,$7,$1,$8,NULL,$4,'{}'::json,NULL)",
        )
        .bind(&fire.run_id)
        .bind(&candidate.snapshot.job_id)
        .bind(scope.project_id)
        .bind(observed_at)
        .bind(candidate.snapshot.job_revision)
        .bind(candidate.snapshot.schedule_revision)
        .bind(candidate.scheduled_for)
        .bind(&fire.idempotency_key)
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        sqlx::query(
            "INSERT INTO agistack_cron_operations ( \
                id, tenant_id, project_id, job_id, job_revision, schedule_revision, \
                operation_kind, run_id, trigger_type, scheduled_for, input_json, status, \
                attempt_count, max_attempts, next_attempt_at, actor_user_id, actor_api_key_id, \
                request_receipt_id, result_json, created_at, updated_at \
             ) VALUES ( \
                $1,$2,$3,$4,$5,$6,'execute_run',$7,'scheduled',$8,$9,'pending',0,$10,$11, \
                $12,NULL,NULL,'{}'::jsonb,$11,$11)",
        )
        .bind(&fire.operation_id)
        .bind(scope.tenant_id)
        .bind(scope.project_id)
        .bind(&candidate.snapshot.job_id)
        .bind(candidate.snapshot.job_revision)
        .bind(candidate.snapshot.schedule_revision)
        .bind(&fire.run_id)
        .bind(candidate.scheduled_for)
        .bind(&input_json)
        .bind(max_retries.saturating_add(1))
        .bind(observed_at)
        .bind(actor_user_id)
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        let updated = sqlx::query(
            "UPDATE agistack_cron_schedule_state \
             SET status = $7, next_fire_at = $8, last_fire_at = $6, \
                 last_error_code = NULL, updated_at = $9 \
             WHERE job_id = $1 AND tenant_id = $2 AND project_id = $3 \
               AND status = 'active' AND schedule_revision = $4 \
               AND schedule_fingerprint = $5 AND next_fire_at = $6",
        )
        .bind(&candidate.snapshot.job_id)
        .bind(scope.tenant_id)
        .bind(scope.project_id)
        .bind(candidate.snapshot.schedule_revision)
        .bind(&candidate.schedule_fingerprint)
        .bind(candidate.scheduled_for)
        .bind(next.status.as_str())
        .bind(next.next_fire_at)
        .bind(observed_at)
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        if updated.rows_affected() != 1 {
            tx.rollback().await.map_err(storage)?;
            return Ok(None);
        }
        tx.commit().await.map_err(storage)?;
        Ok(Some(CronScheduledFireResult {
            run_id: fire.run_id.clone(),
            operation_id: fire.operation_id.clone(),
            scheduled_for: candidate.scheduled_for,
            schedule_status: next.status,
            next_fire_at: next.next_fire_at,
        }))
    }
}

fn validate_fire(
    scope: CronOperationScope<'_>,
    candidate: &CronDueSchedule,
    next: &CronScheduleProjection,
    fire: &NewCronScheduledFire,
    observed_at: DateTime<Utc>,
) -> Result<(), CronScheduleFireError> {
    let required = [
        candidate.snapshot.job_id.as_str(),
        candidate.snapshot.tenant_id.as_str(),
        candidate.snapshot.project_id.as_str(),
        candidate.schedule_fingerprint.as_str(),
        fire.run_id.as_str(),
        fire.operation_id.as_str(),
        fire.idempotency_key.as_str(),
    ];
    let actor_is_valid = candidate
        .actor_user_id
        .as_deref()
        .is_some_and(|value| !value.trim().is_empty());
    let fingerprint_is_sha256 = candidate.schedule_fingerprint.len() == 64
        && candidate
            .schedule_fingerprint
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit());
    let next_is_valid = match next.status {
        CronScheduleStatus::Active => next
            .next_fire_at
            .is_some_and(|value| value > candidate.scheduled_for),
        CronScheduleStatus::Exhausted => next.next_fire_at.is_none(),
        CronScheduleStatus::Disabled => false,
    };
    if required.iter().any(|value| value.trim().is_empty())
        || fire.idempotency_key.len() > 255
        || !actor_is_valid
        || candidate.snapshot.tenant_id != scope.tenant_id
        || candidate.snapshot.project_id != scope.project_id
        || candidate.snapshot.job_revision <= 0
        || candidate.snapshot.schedule_revision <= 0
        || candidate.scheduled_for > observed_at
        || !fingerprint_is_sha256
        || next.schedule_fingerprint != candidate.schedule_fingerprint
        || !next_is_valid
    {
        return Err(CronScheduleFireError::InvalidCandidate);
    }
    Ok(())
}

#[derive(sqlx::FromRow)]
struct CronDueScheduleRow {
    job_id: String,
    tenant_id: String,
    project_id: String,
    job_revision: i64,
    schedule_revision: i64,
    enabled: bool,
    schedule_type: String,
    schedule_config: serde_json::Value,
    timezone: String,
    stagger_seconds: i32,
    created_at: DateTime<Utc>,
    schedule_fingerprint: String,
    scheduled_for: DateTime<Utc>,
    actor_user_id: Option<String>,
    conversation_id: Option<String>,
    timeout_seconds: i32,
    max_retries: i32,
    delete_after_run: bool,
}

impl TryFrom<CronDueScheduleRow> for CronDueSchedule {
    type Error = CronScheduleFireError;

    fn try_from(row: CronDueScheduleRow) -> Result<Self, Self::Error> {
        Ok(Self {
            snapshot: CronScheduleSnapshot {
                job_id: row.job_id,
                tenant_id: row.tenant_id,
                project_id: row.project_id,
                job_revision: row.job_revision,
                schedule_revision: row.schedule_revision,
                enabled: row.enabled,
                schedule_type: row.schedule_type,
                schedule_config: row.schedule_config,
                timezone: row.timezone,
                stagger_seconds: row.stagger_seconds,
                created_at: row.created_at,
            },
            schedule_fingerprint: row.schedule_fingerprint,
            scheduled_for: row.scheduled_for,
            actor_user_id: row.actor_user_id,
            conversation_id: row.conversation_id,
            timeout_seconds: row.timeout_seconds,
            max_retries: row.max_retries,
            delete_after_run: row.delete_after_run,
        })
    }
}

fn storage(error: sqlx::Error) -> CronScheduleFireError {
    CronScheduleFireError::Storage(error.to_string())
}

impl From<CronScheduleFireError> for CoreError {
    fn from(error: CronScheduleFireError) -> Self {
        CoreError::Storage(error.to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn compact(sql: &str) -> String {
        sql.split_whitespace().collect::<Vec<_>>().join(" ")
    }

    #[test]
    fn due_query_is_scope_revision_and_cursor_bound() {
        let sql = compact(LIST_DUE_SQL);

        assert!(sql.contains("state.tenant_id = $1 AND state.project_id = $2"));
        assert!(sql.contains("state.next_fire_at <= $3"));
        assert!(sql.contains("job.schedule_revision = state.schedule_revision"));
        assert!(sql.contains("job.enabled IS TRUE"));
    }

    #[test]
    fn cursor_lock_fences_scope_versions_fingerprint_and_exact_fire_time() {
        let sql = compact(LOCK_CURSOR_SQL);

        assert!(sql.contains("state.job_id = $1 AND state.tenant_id = $2"));
        assert!(sql.contains("state.schedule_revision = $4"));
        assert!(sql.contains("state.schedule_fingerprint = $5"));
        assert!(sql.contains("state.next_fire_at = $6"));
        assert!(sql.contains("job.revision = $7"));
        assert!(sql.contains("FOR UPDATE OF state, job"));
    }
}
