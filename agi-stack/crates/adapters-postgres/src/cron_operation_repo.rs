//! Durable, fail-closed persistence for Rust automation operations.
//!
//! This module owns only the operation queue repository. It does not register a
//! scheduler, start a worker, or expose an HTTP mutation surface. Callers must
//! provision the additive `agistack_cron_operations` table through Alembic
//! before constructing [`PgCronOperationRepository`].

use serde_json::{json, Value};
use sqlx::types::chrono::{DateTime, Utc};
use sqlx::FromRow;

use agistack_core::ports::{CoreError, CoreResult};

use crate::{CronSchedulerLease, PgPool};

const OPERATION_COLUMNS: &str = "id, tenant_id, project_id, job_id, job_revision, \
    schedule_revision, operation_kind, run_id, trigger_type, scheduled_for, input_json, \
    status, attempt_count, max_attempts, next_attempt_at, lease_owner, lease_token, \
    lease_expires_at, actor_user_id, actor_api_key_id, request_receipt_id, last_error_code, \
    last_error_redacted, result_json, created_at, updated_at, started_at, completed_at";

const CLAIM_DUE_SQL: &str = "WITH scheduler_authority AS MATERIALIZED ( \
    SELECT scope_id FROM agistack_cron_scheduler_owners \
    WHERE scope_id = $7 AND owner_kind = 'rust' AND owner_id = $8 \
      AND owner_epoch = $9 AND lease_token = $10 AND lease_expires_at = $11 \
      AND lease_expires_at > $3 \
    FOR UPDATE \
), expired_exhausted AS ( \
    UPDATE agistack_cron_operations AS operation \
    SET status = 'dead_letter', \
        lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL, \
        next_attempt_at = NULL, last_error_code = 'lease_expired', \
        last_error_redacted = 'operation lease expired after max attempts', \
        completed_at = $3, updated_at = $3 \
    FROM scheduler_authority \
    WHERE operation.tenant_id = $1 AND operation.project_id = $2 \
      AND operation.attempt_count >= operation.max_attempts \
      AND ( \
        (operation.status IN ('pending', 'failed') \
         AND (operation.next_attempt_at IS NULL OR operation.next_attempt_at <= $3)) \
        OR (operation.status = 'processing' \
            AND operation.lease_expires_at IS NOT NULL \
            AND operation.lease_expires_at <= $3) \
      ) \
    RETURNING operation.id \
), due AS ( \
    SELECT operation.id FROM agistack_cron_operations AS operation \
    CROSS JOIN scheduler_authority \
    WHERE operation.tenant_id = $1 AND operation.project_id = $2 \
      AND operation.attempt_count < operation.max_attempts \
      AND ( \
        (operation.status IN ('pending', 'failed') \
         AND (operation.next_attempt_at IS NULL OR operation.next_attempt_at <= $3)) \
        OR (operation.status = 'processing' \
            AND operation.lease_expires_at IS NOT NULL \
            AND operation.lease_expires_at <= $3) \
      ) \
    ORDER BY COALESCE(operation.next_attempt_at, operation.created_at), \
             operation.created_at, operation.id \
    LIMIT $4 \
    FOR UPDATE OF operation SKIP LOCKED \
) \
UPDATE agistack_cron_operations AS operation \
SET status = 'processing', \
    attempt_count = operation.attempt_count + 1, \
    lease_owner = $5, \
    lease_token = concat(operation.id, ':', operation.attempt_count + 1, ':', txid_current()), \
    lease_expires_at = $3 + ($6 * interval '1 second'), \
    next_attempt_at = NULL, \
    last_error_code = NULL, \
    last_error_redacted = NULL, \
    started_at = COALESCE(operation.started_at, $3), \
    completed_at = NULL, \
    updated_at = $3 \
FROM due \
WHERE operation.id = due.id \
RETURNING operation.id, operation.tenant_id, operation.project_id, operation.job_id, \
    operation.job_revision, operation.schedule_revision, operation.operation_kind, \
    operation.run_id, operation.trigger_type, operation.scheduled_for, operation.input_json, \
    operation.status, operation.attempt_count, operation.max_attempts, \
    operation.next_attempt_at, operation.lease_owner, operation.lease_token, \
    operation.lease_expires_at, operation.actor_user_id, operation.actor_api_key_id, \
    operation.request_receipt_id, operation.last_error_code, operation.last_error_redacted, \
    operation.result_json, operation.created_at, operation.updated_at, operation.started_at, \
    operation.completed_at";

const RENEW_SQL: &str = "UPDATE agistack_cron_operations \
SET lease_expires_at = $6 + ($7 * interval '1 second'), updated_at = $6 \
WHERE id = $1 AND tenant_id = $2 AND project_id = $3 \
  AND status = 'processing' \
  AND lease_owner = $4 AND lease_token = $5 \
  AND lease_expires_at > $6";

const COMPLETE_SQL: &str = "UPDATE agistack_cron_operations \
SET status = 'completed', \
    lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL, \
    next_attempt_at = NULL, last_error_code = NULL, last_error_redacted = NULL, \
    result_json = $7, completed_at = $6, updated_at = $6 \
WHERE id = $1 AND tenant_id = $2 AND project_id = $3 \
  AND status = 'processing' \
  AND lease_owner = $4 AND lease_token = $5 \
  AND lease_expires_at > $6 \
RETURNING id, tenant_id, project_id, job_id, job_revision, schedule_revision, \
    operation_kind, run_id, trigger_type, scheduled_for, input_json, status, attempt_count, \
    max_attempts, next_attempt_at, lease_owner, lease_token, lease_expires_at, actor_user_id, \
    actor_api_key_id, request_receipt_id, \
    last_error_code, last_error_redacted, result_json, created_at, updated_at, started_at, \
    completed_at";

const MARK_WAITING_RUNTIME_SQL: &str = "UPDATE agistack_cron_operations \
SET status = 'waiting_runtime', \
    lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL, \
    next_attempt_at = NULL, last_error_code = NULL, last_error_redacted = NULL, \
    result_json = $7, completed_at = NULL, updated_at = $6 \
WHERE id = $1 AND tenant_id = $2 AND project_id = $3 \
  AND status = 'processing' \
  AND lease_owner = $4 AND lease_token = $5 \
  AND lease_expires_at > $6 \
RETURNING id, tenant_id, project_id, job_id, job_revision, schedule_revision, \
    operation_kind, run_id, trigger_type, scheduled_for, input_json, status, attempt_count, \
    max_attempts, next_attempt_at, lease_owner, lease_token, lease_expires_at, actor_user_id, \
    actor_api_key_id, request_receipt_id, \
    last_error_code, last_error_redacted, result_json, created_at, updated_at, started_at, \
    completed_at";

const RECONCILE_RUNTIME_TERMINAL_SQL: &str = "UPDATE agistack_cron_operations AS operation \
SET status = 'completed', \
    result_json = operation.result_json \
        || COALESCE(run.result_summary::jsonb, '{}'::jsonb) \
        || jsonb_build_object( \
            'runtime_execution_id', run.runtime_execution_id, \
            'runtime_status', run.status \
        ), \
    next_attempt_at = NULL, last_error_code = NULL, last_error_redacted = NULL, \
    completed_at = COALESCE(run.finished_at, $4), updated_at = $4 \
FROM cron_job_runs AS run, cron_jobs AS job \
WHERE operation.id = $1 AND operation.tenant_id = $2 AND operation.project_id = $3 \
  AND operation.status = 'waiting_runtime' \
  AND operation.operation_kind = 'execute_run' \
  AND operation.run_id = run.id \
  AND run.runtime_execution_id = operation.run_id \
  AND run.project_id = operation.project_id \
  AND run.status IN ('success', 'failed', 'timeout', 'cancelled', 'skipped') \
  AND job.id = run.job_id \
  AND job.tenant_id = operation.tenant_id \
  AND job.project_id = operation.project_id \
RETURNING operation.id, operation.tenant_id, operation.project_id, operation.job_id, \
    operation.job_revision, operation.schedule_revision, operation.operation_kind, \
    operation.run_id, operation.trigger_type, operation.scheduled_for, operation.input_json, \
    operation.status, operation.attempt_count, operation.max_attempts, \
    operation.next_attempt_at, operation.lease_owner, operation.lease_token, \
    operation.lease_expires_at, operation.actor_user_id, operation.actor_api_key_id, \
    operation.request_receipt_id, operation.last_error_code, operation.last_error_redacted, \
    operation.result_json, operation.created_at, operation.updated_at, operation.started_at, \
    operation.completed_at";

const FAIL_SQL: &str = "UPDATE agistack_cron_operations \
SET status = CASE \
        WHEN attempt_count >= max_attempts THEN 'dead_letter' \
        ELSE 'failed' \
    END, \
    lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL, \
    last_error_code = $7, last_error_redacted = left($8, 2000), \
    next_attempt_at = CASE \
        WHEN attempt_count >= max_attempts THEN NULL \
        ELSE $6 + ($9 * interval '1 second') \
    END, \
    completed_at = CASE WHEN attempt_count >= max_attempts THEN $6 ELSE NULL END, \
    updated_at = $6 \
WHERE id = $1 AND tenant_id = $2 AND project_id = $3 \
  AND status = 'processing' \
  AND lease_owner = $4 AND lease_token = $5 \
  AND lease_expires_at > $6 \
RETURNING id, tenant_id, project_id, job_id, job_revision, schedule_revision, \
    operation_kind, run_id, trigger_type, scheduled_for, input_json, status, attempt_count, \
    max_attempts, next_attempt_at, lease_owner, lease_token, lease_expires_at, actor_user_id, \
    actor_api_key_id, request_receipt_id, \
    last_error_code, last_error_redacted, result_json, created_at, updated_at, started_at, \
    completed_at";

/// Tenant and project boundary required by every operation mutation.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CronOperationScope<'a> {
    pub tenant_id: &'a str,
    pub project_id: &'a str,
}

/// Durable operation categories supported by the repository foundation.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[non_exhaustive]
pub enum CronOperationKind {
    ReconcileSchedule,
    ExecuteRun,
}

impl CronOperationKind {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::ReconcileSchedule => "reconcile_schedule",
            Self::ExecuteRun => "execute_run",
        }
    }
}

impl TryFrom<&str> for CronOperationKind {
    type Error = CoreError;

    fn try_from(value: &str) -> Result<Self, Self::Error> {
        match value {
            "reconcile_schedule" => Ok(Self::ReconcileSchedule),
            "execute_run" => Ok(Self::ExecuteRun),
            other => Err(CoreError::Storage(format!(
                "unknown cron operation kind: {other}"
            ))),
        }
    }
}

/// Persisted lifecycle for a durable automation operation.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[non_exhaustive]
pub enum CronOperationStatus {
    Pending,
    Processing,
    Failed,
    WaitingRuntime,
    WaitingHuman,
    Completed,
    DeadLetter,
}

impl CronOperationStatus {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::Processing => "processing",
            Self::Failed => "failed",
            Self::WaitingRuntime => "waiting_runtime",
            Self::WaitingHuman => "waiting_human",
            Self::Completed => "completed",
            Self::DeadLetter => "dead_letter",
        }
    }
}

impl TryFrom<&str> for CronOperationStatus {
    type Error = CoreError;

    fn try_from(value: &str) -> Result<Self, Self::Error> {
        match value {
            "pending" => Ok(Self::Pending),
            "processing" => Ok(Self::Processing),
            "failed" => Ok(Self::Failed),
            "waiting_runtime" => Ok(Self::WaitingRuntime),
            "waiting_human" => Ok(Self::WaitingHuman),
            "completed" => Ok(Self::Completed),
            "dead_letter" => Ok(Self::DeadLetter),
            other => Err(CoreError::Storage(format!(
                "unknown cron operation status: {other}"
            ))),
        }
    }
}

/// Structured failure classifications; free-form error classification is rejected.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[non_exhaustive]
pub enum CronOperationErrorCode {
    HandlerUnavailable,
    InvalidOperation,
    StaleRevision,
    ExecutionFailed,
    ExecutionTimedOut,
    LeaseExpired,
    Cancelled,
}

impl CronOperationErrorCode {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::HandlerUnavailable => "handler_unavailable",
            Self::InvalidOperation => "invalid_operation",
            Self::StaleRevision => "stale_revision",
            Self::ExecutionFailed => "execution_failed",
            Self::ExecutionTimedOut => "execution_timed_out",
            Self::LeaseExpired => "lease_expired",
            Self::Cancelled => "cancelled",
        }
    }
}

impl TryFrom<&str> for CronOperationErrorCode {
    type Error = CoreError;

    fn try_from(value: &str) -> Result<Self, Self::Error> {
        match value {
            "handler_unavailable" => Ok(Self::HandlerUnavailable),
            "invalid_operation" => Ok(Self::InvalidOperation),
            "stale_revision" => Ok(Self::StaleRevision),
            "execution_failed" => Ok(Self::ExecutionFailed),
            "execution_timed_out" => Ok(Self::ExecutionTimedOut),
            "lease_expired" => Ok(Self::LeaseExpired),
            "cancelled" => Ok(Self::Cancelled),
            other => Err(CoreError::Storage(format!(
                "unknown cron operation error code: {other}"
            ))),
        }
    }
}

/// Insert payload for one durable operation. Status and lease fields are repository-owned.
#[derive(Debug, Clone)]
pub struct NewCronOperation {
    pub id: String,
    pub tenant_id: String,
    pub project_id: String,
    pub job_id: String,
    pub job_revision: i64,
    pub schedule_revision: Option<i64>,
    pub kind: CronOperationKind,
    pub run_id: Option<String>,
    pub trigger_type: Option<String>,
    pub scheduled_for: Option<DateTime<Utc>>,
    pub input_json: Value,
    pub actor_user_id: Option<String>,
    pub actor_api_key_id: Option<String>,
    pub request_receipt_id: Option<String>,
    pub max_attempts: i32,
    pub next_attempt_at: Option<DateTime<Utc>>,
    pub created_at: DateTime<Utc>,
}

/// Claimed or terminal operation returned by the repository.
#[derive(Debug, Clone, PartialEq)]
pub struct CronOperationRecord {
    pub id: String,
    pub tenant_id: String,
    pub project_id: String,
    pub job_id: String,
    pub job_revision: i64,
    pub schedule_revision: Option<i64>,
    pub kind: CronOperationKind,
    pub run_id: Option<String>,
    pub trigger_type: Option<String>,
    pub scheduled_for: Option<DateTime<Utc>>,
    pub input_json: Value,
    pub status: CronOperationStatus,
    pub attempt_count: i32,
    pub max_attempts: i32,
    pub next_attempt_at: Option<DateTime<Utc>>,
    pub lease_owner: Option<String>,
    pub lease_token: Option<String>,
    pub lease_expires_at: Option<DateTime<Utc>>,
    pub actor_user_id: Option<String>,
    pub actor_api_key_id: Option<String>,
    pub request_receipt_id: Option<String>,
    pub last_error_code: Option<CronOperationErrorCode>,
    pub last_error_redacted: Option<String>,
    pub result_json: Value,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
    pub started_at: Option<DateTime<Utc>>,
    pub completed_at: Option<DateTime<Utc>>,
}

/// Typed failure input. `redacted_text` must already be scrubbed by the caller.
#[derive(Debug, Clone, Copy)]
pub struct CronOperationFailure<'a> {
    code: CronOperationErrorCode,
    redacted_text: &'a str,
    retry_after_seconds: i64,
}

impl<'a> CronOperationFailure<'a> {
    /// Build a failure from a closed error code and caller-scrubbed text.
    pub fn new(
        code: CronOperationErrorCode,
        redacted_text: &'a str,
        retry_after_seconds: i64,
    ) -> Self {
        Self {
            code,
            redacted_text,
            retry_after_seconds,
        }
    }
}

#[derive(Debug, FromRow)]
struct CronOperationRow {
    id: String,
    tenant_id: String,
    project_id: String,
    job_id: String,
    job_revision: i64,
    schedule_revision: Option<i64>,
    operation_kind: String,
    run_id: Option<String>,
    trigger_type: Option<String>,
    scheduled_for: Option<DateTime<Utc>>,
    input_json: Option<Value>,
    status: String,
    attempt_count: i32,
    max_attempts: i32,
    next_attempt_at: Option<DateTime<Utc>>,
    lease_owner: Option<String>,
    lease_token: Option<String>,
    lease_expires_at: Option<DateTime<Utc>>,
    actor_user_id: Option<String>,
    actor_api_key_id: Option<String>,
    request_receipt_id: Option<String>,
    last_error_code: Option<String>,
    last_error_redacted: Option<String>,
    result_json: Option<Value>,
    created_at: DateTime<Utc>,
    updated_at: DateTime<Utc>,
    started_at: Option<DateTime<Utc>>,
    completed_at: Option<DateTime<Utc>>,
}

impl TryFrom<CronOperationRow> for CronOperationRecord {
    type Error = CoreError;

    fn try_from(row: CronOperationRow) -> Result<Self, Self::Error> {
        Ok(Self {
            id: row.id,
            tenant_id: row.tenant_id,
            project_id: row.project_id,
            job_id: row.job_id,
            job_revision: row.job_revision,
            schedule_revision: row.schedule_revision,
            kind: CronOperationKind::try_from(row.operation_kind.as_str())?,
            run_id: row.run_id,
            trigger_type: row.trigger_type,
            scheduled_for: row.scheduled_for,
            input_json: row.input_json.unwrap_or_else(|| json!({})),
            status: CronOperationStatus::try_from(row.status.as_str())?,
            attempt_count: row.attempt_count,
            max_attempts: row.max_attempts,
            next_attempt_at: row.next_attempt_at,
            lease_owner: row.lease_owner,
            lease_token: row.lease_token,
            lease_expires_at: row.lease_expires_at,
            actor_user_id: row.actor_user_id,
            actor_api_key_id: row.actor_api_key_id,
            request_receipt_id: row.request_receipt_id,
            last_error_code: row
                .last_error_code
                .as_deref()
                .map(CronOperationErrorCode::try_from)
                .transpose()?,
            last_error_redacted: row.last_error_redacted,
            result_json: row.result_json.unwrap_or_else(|| json!({})),
            created_at: row.created_at,
            updated_at: row.updated_at,
            started_at: row.started_at,
            completed_at: row.completed_at,
        })
    }
}

/// PostgreSQL repository for the additive `agistack_cron_operations` queue.
pub struct PgCronOperationRepository {
    pool: PgPool,
}

impl PgCronOperationRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    /// Persist a pending operation without starting any runtime worker.
    pub async fn enqueue(&self, operation: NewCronOperation) -> CoreResult<CronOperationRecord> {
        let sql = format!(
            "INSERT INTO agistack_cron_operations ( \
                id, tenant_id, project_id, job_id, job_revision, schedule_revision, \
                operation_kind, run_id, trigger_type, scheduled_for, input_json, status, \
                attempt_count, max_attempts, next_attempt_at, actor_user_id, actor_api_key_id, \
                request_receipt_id, result_json, created_at, updated_at \
             ) VALUES ( \
                $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,'pending',0,$12,$13,$14,$15,$16, \
                '{{}}'::jsonb,$17,$17 \
             ) RETURNING {OPERATION_COLUMNS}"
        );
        let row = sqlx::query_as::<_, CronOperationRow>(&sql)
            .bind(&operation.id)
            .bind(&operation.tenant_id)
            .bind(&operation.project_id)
            .bind(&operation.job_id)
            .bind(operation.job_revision)
            .bind(operation.schedule_revision)
            .bind(operation.kind.as_str())
            .bind(&operation.run_id)
            .bind(&operation.trigger_type)
            .bind(operation.scheduled_for)
            .bind(&operation.input_json)
            .bind(operation.max_attempts.max(1))
            .bind(operation.next_attempt_at)
            .bind(&operation.actor_user_id)
            .bind(&operation.actor_api_key_id)
            .bind(&operation.request_receipt_id)
            .bind(operation.created_at)
            .fetch_one(&self.pool)
            .await
            .map_err(storage)?;
        row.try_into()
    }

    /// Claim due operations only while the exact global scheduler lease is current.
    pub async fn claim_due(
        &self,
        scope: CronOperationScope<'_>,
        authority: &CronSchedulerLease,
        limit: i64,
        lease_owner: &str,
        lease_seconds: i64,
        now: DateTime<Utc>,
    ) -> CoreResult<Vec<CronOperationRecord>> {
        if limit <= 0 {
            return Ok(Vec::new());
        }
        if !authority.is_structurally_valid() {
            return Err(CoreError::Storage(
                "cron operation scheduler authority is invalid".to_string(),
            ));
        }
        let rows = sqlx::query_as::<_, CronOperationRow>(CLAIM_DUE_SQL)
            .bind(scope.tenant_id)
            .bind(scope.project_id)
            .bind(now)
            .bind(limit.clamp(1, 100))
            .bind(lease_owner)
            .bind(positive_seconds(lease_seconds))
            .bind(&authority.scope_id)
            .bind(&authority.owner_id)
            .bind(authority.owner_epoch)
            .bind(&authority.lease_token)
            .bind(authority.lease_expires_at)
            .fetch_all(&self.pool)
            .await
            .map_err(storage)?;
        rows.into_iter().map(TryInto::try_into).collect()
    }

    /// Extend an active lease. Expired or mismatched leases are never revived.
    pub async fn renew(
        &self,
        scope: CronOperationScope<'_>,
        operation_id: &str,
        lease_owner: &str,
        lease_token: &str,
        lease_seconds: i64,
        now: DateTime<Utc>,
    ) -> CoreResult<bool> {
        let result = sqlx::query(RENEW_SQL)
            .bind(operation_id)
            .bind(scope.tenant_id)
            .bind(scope.project_id)
            .bind(lease_owner)
            .bind(lease_token)
            .bind(now)
            .bind(positive_seconds(lease_seconds))
            .execute(&self.pool)
            .await
            .map_err(storage)?;
        Ok(result.rows_affected() == 1)
    }

    /// Complete an operation only while its exact lease is still active.
    pub async fn complete(
        &self,
        scope: CronOperationScope<'_>,
        operation_id: &str,
        lease_owner: &str,
        lease_token: &str,
        result_json: &Value,
        now: DateTime<Utc>,
    ) -> CoreResult<Option<CronOperationRecord>> {
        sqlx::query_as::<_, CronOperationRow>(COMPLETE_SQL)
            .bind(operation_id)
            .bind(scope.tenant_id)
            .bind(scope.project_id)
            .bind(lease_owner)
            .bind(lease_token)
            .bind(now)
            .bind(result_json)
            .fetch_optional(&self.pool)
            .await
            .map_err(storage)?
            .map(TryInto::try_into)
            .transpose()
    }

    /// Release the dispatch lease without treating runtime acceptance as completion.
    pub async fn mark_waiting_runtime(
        &self,
        scope: CronOperationScope<'_>,
        operation_id: &str,
        lease_owner: &str,
        lease_token: &str,
        dispatch_json: &Value,
        now: DateTime<Utc>,
    ) -> CoreResult<Option<CronOperationRecord>> {
        let waiting = sqlx::query_as::<_, CronOperationRow>(MARK_WAITING_RUNTIME_SQL)
            .bind(operation_id)
            .bind(scope.tenant_id)
            .bind(scope.project_id)
            .bind(lease_owner)
            .bind(lease_token)
            .bind(now)
            .bind(dispatch_json)
            .fetch_optional(&self.pool)
            .await
            .map_err(storage)?
            .map(TryInto::try_into)
            .transpose()?;
        let Some(waiting) = waiting else {
            return Ok(None);
        };
        Ok(self
            .reconcile_runtime_terminal(scope, operation_id, now)
            .await?
            .or(Some(waiting)))
    }

    /// Close a waiting delivery when its correlated Agent run is already terminal.
    pub async fn reconcile_runtime_terminal(
        &self,
        scope: CronOperationScope<'_>,
        operation_id: &str,
        now: DateTime<Utc>,
    ) -> CoreResult<Option<CronOperationRecord>> {
        sqlx::query_as::<_, CronOperationRow>(RECONCILE_RUNTIME_TERMINAL_SQL)
            .bind(operation_id)
            .bind(scope.tenant_id)
            .bind(scope.project_id)
            .bind(now)
            .fetch_optional(&self.pool)
            .await
            .map_err(storage)?
            .map(TryInto::try_into)
            .transpose()
    }

    /// Record a typed, redacted failure and retry or dead-letter atomically.
    pub async fn fail(
        &self,
        scope: CronOperationScope<'_>,
        operation_id: &str,
        lease_owner: &str,
        lease_token: &str,
        failure: CronOperationFailure<'_>,
        now: DateTime<Utc>,
    ) -> CoreResult<Option<CronOperationRecord>> {
        sqlx::query_as::<_, CronOperationRow>(FAIL_SQL)
            .bind(operation_id)
            .bind(scope.tenant_id)
            .bind(scope.project_id)
            .bind(lease_owner)
            .bind(lease_token)
            .bind(now)
            .bind(failure.code.as_str())
            .bind(failure.redacted_text)
            .bind(failure.retry_after_seconds.max(0))
            .fetch_optional(&self.pool)
            .await
            .map_err(storage)?
            .map(TryInto::try_into)
            .transpose()
    }
}

fn positive_seconds(seconds: i64) -> i32 {
    i32::try_from(seconds.max(1)).unwrap_or(i32::MAX)
}

fn storage(error: sqlx::Error) -> CoreError {
    CoreError::Storage(format!("cron operation repository: {error}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn compact(sql: &str) -> String {
        sql.split_whitespace().collect::<Vec<_>>().join(" ")
    }

    #[test]
    fn operation_kind_and_status_reject_unknown_database_values() {
        assert_eq!(
            CronOperationKind::try_from("execute_run").expect("known kind"),
            CronOperationKind::ExecuteRun
        );
        assert_eq!(
            CronOperationStatus::try_from("dead_letter").expect("known status"),
            CronOperationStatus::DeadLetter
        );
        assert!(CronOperationKind::try_from("arbitrary").is_err());
        assert!(CronOperationStatus::try_from("arbitrary").is_err());
        assert!(CronOperationErrorCode::try_from("arbitrary").is_err());
    }

    #[test]
    fn claim_sql_is_scoped_skip_locked_and_rotates_the_fencing_token() {
        let sql = compact(CLAIM_DUE_SQL);

        assert!(sql.contains(
            "scope_id = $7 AND owner_kind = 'rust' AND owner_id = $8 AND owner_epoch = $9"
        ));
        assert!(sql.contains("lease_token = $10 AND lease_expires_at = $11"));
        assert!(sql.contains("lease_expires_at > $3 FOR UPDATE"));
        assert!(sql.contains("FROM scheduler_authority"));
        assert!(sql.contains("CROSS JOIN scheduler_authority"));
        assert!(sql.contains("operation.tenant_id = $1 AND operation.project_id = $2"));
        assert!(sql.contains("FOR UPDATE OF operation SKIP LOCKED"));
        assert!(sql.contains("status = 'processing'"));
        assert!(sql.contains("lease_expires_at <= $3"));
        assert!(sql.contains("attempt_count = operation.attempt_count + 1"));
        assert!(sql.contains(
            "lease_token = concat(operation.id, ':', operation.attempt_count + 1, ':', txid_current())"
        ));
        assert!(sql.contains("operation.attempt_count >= operation.max_attempts"));
        assert!(sql.contains("last_error_code = 'lease_expired'"));
    }

    #[test]
    fn every_lease_mutation_requires_scope_owner_token_and_unexpired_lease() {
        for sql in [RENEW_SQL, COMPLETE_SQL, MARK_WAITING_RUNTIME_SQL, FAIL_SQL] {
            let sql = compact(sql);
            assert!(sql.contains("id = $1 AND tenant_id = $2 AND project_id = $3"));
            assert!(sql.contains("lease_owner = $4 AND lease_token = $5"));
            assert!(sql.contains("lease_expires_at > $6"));
        }
    }

    #[test]
    fn waiting_runtime_releases_the_dispatch_lease_without_becoming_terminal() {
        let sql = compact(MARK_WAITING_RUNTIME_SQL);

        assert!(sql.contains("status = 'waiting_runtime'"));
        assert!(sql.contains("lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL"));
        assert!(sql.contains("result_json = $7"));
        assert!(sql.contains("completed_at = NULL"));
    }

    #[test]
    fn runtime_terminal_reconciliation_is_scope_bound_and_uses_structured_run_state() {
        let sql = compact(RECONCILE_RUNTIME_TERMINAL_SQL);

        assert!(sql.contains(
            "operation.id = $1 AND operation.tenant_id = $2 AND operation.project_id = $3"
        ));
        assert!(sql.contains("operation.status = 'waiting_runtime'"));
        assert!(sql.contains("run.runtime_execution_id = operation.run_id"));
        assert!(
            sql.contains("run.status IN ('success', 'failed', 'timeout', 'cancelled', 'skipped')")
        );
        assert!(sql.contains("job.tenant_id = operation.tenant_id"));
        assert!(sql.contains("COALESCE(run.result_summary::jsonb, '{}'::jsonb)"));
        assert!(!sql.contains("run.error_message"));
    }

    #[test]
    fn failure_sql_uses_typed_fields_and_dead_letters_exhausted_operations() {
        let sql = compact(FAIL_SQL);

        assert!(sql.contains("last_error_code = $7"));
        assert!(sql.contains("last_error_redacted = left($8, 2000)"));
        assert!(sql.contains("attempt_count >= max_attempts THEN 'dead_letter'"));
        assert!(sql.contains("ELSE $6 + ($9 * interval '1 second')"));
    }

    #[test]
    fn lease_duration_is_positive_and_saturates_on_overflow() {
        assert_eq!(positive_seconds(0), 1);
        assert_eq!(positive_seconds(-1), 1);
        assert_eq!(positive_seconds(i64::MAX), i32::MAX);
    }

    #[test]
    fn failure_codes_are_closed_and_stable() {
        assert_eq!(
            CronOperationErrorCode::HandlerUnavailable.as_str(),
            "handler_unavailable"
        );
        assert_eq!(
            CronOperationErrorCode::ExecutionTimedOut.as_str(),
            "execution_timed_out"
        );
        assert_eq!(CronOperationErrorCode::Cancelled.as_str(), "cancelled");
    }
}
