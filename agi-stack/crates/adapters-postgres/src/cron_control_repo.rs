//! Fenced discovery and reconciliation admission for the Rust cron control loop.

use std::fmt;

use agistack_core::ports::CoreError;
use sqlx::types::chrono::{DateTime, Utc};

use crate::{CronSchedulerLease, PgPool};

const LIST_WORK_SCOPES_SQL: &str = "WITH scheduler_authority AS MATERIALIZED ( \
    SELECT scope_id FROM agistack_cron_scheduler_owners \
    WHERE scope_id = $1 AND owner_kind = 'rust' AND owner_id = $2 \
      AND owner_epoch = $3 AND lease_token = $4 AND lease_expires_at = $5 \
      AND lease_expires_at > $6 \
    FOR SHARE \
), scopes AS ( \
    SELECT tenant_id, project_id FROM cron_jobs \
    UNION \
    SELECT tenant_id, project_id FROM agistack_cron_operations \
    WHERE status IN ('pending', 'failed', 'processing', 'waiting_runtime') \
    UNION \
    SELECT job.tenant_id, run.project_id \
    FROM cron_job_runs AS run \
    JOIN cron_jobs AS job ON job.id = run.job_id \
    WHERE run.status IN ('queued', 'running', 'waiting_human') \
) \
SELECT scopes.tenant_id, scopes.project_id \
FROM scopes CROSS JOIN scheduler_authority \
WHERE $7::text IS NULL \
   OR (scopes.tenant_id, scopes.project_id) > ($7::text, $8::text) \
ORDER BY scopes.tenant_id, scopes.project_id \
LIMIT $9";

const ADMIT_RECONCILE_SQL: &str = "WITH scheduler_authority AS MATERIALIZED ( \
    SELECT scope_id FROM agistack_cron_scheduler_owners \
    WHERE scope_id = $1 AND owner_kind = 'rust' AND owner_id = $2 \
      AND owner_epoch = $3 AND lease_token = $4 AND lease_expires_at = $5 \
      AND lease_expires_at > $6 \
    FOR UPDATE \
), candidates AS ( \
    SELECT job.id AS job_id, job.tenant_id, job.project_id, \
           job.revision AS job_revision, job.schedule_revision \
    FROM cron_jobs AS job \
    LEFT JOIN agistack_cron_schedule_state AS state ON state.job_id = job.id \
    CROSS JOIN scheduler_authority \
    WHERE job.tenant_id = $7 AND job.project_id = $8 \
      AND job.schedule_revision > 0 \
      AND (state.job_id IS NULL OR state.schedule_revision < job.schedule_revision) \
    ORDER BY job.tenant_id, job.project_id, job.id \
    LIMIT $9 \
    FOR UPDATE OF job SKIP LOCKED \
) \
INSERT INTO agistack_cron_operations ( \
    id, tenant_id, project_id, job_id, job_revision, schedule_revision, \
    operation_kind, input_json, status, attempt_count, max_attempts, \
    next_attempt_at, result_json, created_at, updated_at \
) \
SELECT concat('cron-reconcile:', candidate.job_id, ':', candidate.schedule_revision::text), \
       candidate.tenant_id, candidate.project_id, candidate.job_id, candidate.job_revision, \
       candidate.schedule_revision, 'reconcile_schedule', '{}'::jsonb, 'pending', 0, 5, \
       $6, '{}'::jsonb, $6, $6 \
FROM candidates AS candidate \
ON CONFLICT (job_id, operation_kind, schedule_revision) \
    WHERE operation_kind = 'reconcile_schedule' DO NOTHING \
RETURNING id AS operation_id, tenant_id, project_id, job_id, schedule_revision";

#[derive(Debug, Clone, PartialEq, Eq, sqlx::FromRow)]
pub struct CronControlScope {
    pub tenant_id: String,
    pub project_id: String,
}

#[derive(Debug, Clone, PartialEq, Eq, sqlx::FromRow)]
pub struct CronReconcileAdmission {
    pub operation_id: String,
    pub tenant_id: String,
    pub project_id: String,
    pub job_id: String,
    pub schedule_revision: i64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CronControlRepositoryError {
    InvalidAuthority,
    InvalidCursor,
    InvalidScope,
    Storage(String),
}

impl fmt::Display for CronControlRepositoryError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::InvalidAuthority => "cron control authority is invalid",
            Self::InvalidCursor => "cron control scope cursor is invalid",
            Self::InvalidScope => "cron control scope is invalid",
            Self::Storage(_) => "cron control storage failed",
        })
    }
}

impl std::error::Error for CronControlRepositoryError {}

#[derive(Clone)]
pub struct PgCronControlRepository {
    pool: PgPool,
}

impl PgCronControlRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn list_work_scopes(
        &self,
        authority: &CronSchedulerLease,
        after: Option<&CronControlScope>,
        limit: i64,
        observed_at: DateTime<Utc>,
    ) -> Result<Vec<CronControlScope>, CronControlRepositoryError> {
        if limit <= 0 {
            return Ok(Vec::new());
        }
        validate_authority(authority)?;
        if after.is_some_and(|cursor| {
            cursor.tenant_id.trim().is_empty() || cursor.project_id.trim().is_empty()
        }) {
            return Err(CronControlRepositoryError::InvalidCursor);
        }
        let after_tenant_id = after.map(|cursor| cursor.tenant_id.as_str());
        let after_project_id = after.map(|cursor| cursor.project_id.as_str());
        sqlx::query_as::<_, CronControlScope>(LIST_WORK_SCOPES_SQL)
            .bind(&authority.scope_id)
            .bind(&authority.owner_id)
            .bind(authority.owner_epoch)
            .bind(&authority.lease_token)
            .bind(authority.lease_expires_at)
            .bind(observed_at)
            .bind(after_tenant_id)
            .bind(after_project_id)
            .bind(limit.clamp(1, 1_000))
            .fetch_all(&self.pool)
            .await
            .map_err(storage)
    }

    pub async fn admit_reconcile_operations(
        &self,
        authority: &CronSchedulerLease,
        scope: &CronControlScope,
        limit: i64,
        observed_at: DateTime<Utc>,
    ) -> Result<Vec<CronReconcileAdmission>, CronControlRepositoryError> {
        if limit <= 0 {
            return Ok(Vec::new());
        }
        validate_authority(authority)?;
        validate_scope(scope)?;
        sqlx::query_as::<_, CronReconcileAdmission>(ADMIT_RECONCILE_SQL)
            .bind(&authority.scope_id)
            .bind(&authority.owner_id)
            .bind(authority.owner_epoch)
            .bind(&authority.lease_token)
            .bind(authority.lease_expires_at)
            .bind(observed_at)
            .bind(&scope.tenant_id)
            .bind(&scope.project_id)
            .bind(limit.clamp(1, 1_000))
            .fetch_all(&self.pool)
            .await
            .map_err(storage)
    }
}

fn validate_authority(authority: &CronSchedulerLease) -> Result<(), CronControlRepositoryError> {
    if authority.is_structurally_valid() {
        Ok(())
    } else {
        Err(CronControlRepositoryError::InvalidAuthority)
    }
}

fn validate_scope(scope: &CronControlScope) -> Result<(), CronControlRepositoryError> {
    if scope.tenant_id.trim().is_empty() || scope.project_id.trim().is_empty() {
        Err(CronControlRepositoryError::InvalidScope)
    } else {
        Ok(())
    }
}

fn storage(error: sqlx::Error) -> CronControlRepositoryError {
    CronControlRepositoryError::Storage(error.to_string())
}

impl From<CronControlRepositoryError> for CoreError {
    fn from(error: CronControlRepositoryError) -> Self {
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
    fn control_queries_require_exact_scheduler_authority() {
        for sql in [LIST_WORK_SCOPES_SQL, ADMIT_RECONCILE_SQL] {
            let sql = compact(sql);
            assert!(sql.contains("scope_id = $1 AND owner_kind = 'rust' AND owner_id = $2"));
            assert!(sql.contains("owner_epoch = $3 AND lease_token = $4"));
            assert!(sql.contains("lease_expires_at = $5"));
            assert!(sql.contains("lease_expires_at > $6"));
        }
    }

    #[test]
    fn scope_discovery_is_keyset_paginated_across_all_active_work() {
        let sql = compact(LIST_WORK_SCOPES_SQL);
        assert!(sql.contains("SELECT tenant_id, project_id FROM cron_jobs UNION"));
        assert!(sql.contains("FROM agistack_cron_operations"));
        assert!(sql.contains("run.status IN ('queued', 'running', 'waiting_human')"));
        assert!(sql.contains("(scopes.tenant_id, scopes.project_id) > ($7::text, $8::text)"));
    }

    #[test]
    fn reconciliation_admission_is_revision_idempotent_and_job_locked() {
        let sql = compact(ADMIT_RECONCILE_SQL);
        assert!(sql.contains("state.schedule_revision < job.schedule_revision"));
        assert!(sql.contains("job.tenant_id = $7 AND job.project_id = $8"));
        assert!(sql.contains("FOR UPDATE OF job SKIP LOCKED"));
        assert!(sql.contains("operation_kind = 'reconcile_schedule' DO NOTHING"));
        assert!(sql.contains(
            "concat('cron-reconcile:', candidate.job_id, ':', candidate.schedule_revision::text)"
        ));
    }
}
