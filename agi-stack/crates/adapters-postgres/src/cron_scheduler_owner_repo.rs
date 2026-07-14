//! Fenced ownership lease for the Python-to-Rust cron scheduler cutover.

use std::fmt;

use sqlx::types::chrono::{DateTime, Utc};

use agistack_core::ports::CoreError;

use crate::PgPool;

pub const GLOBAL_CRON_SCHEDULER_SCOPE: &str = "global";

const ACQUIRE_SQL: &str = "UPDATE agistack_cron_scheduler_owners \
SET owner_id = $2, owner_epoch = owner_epoch + 1, \
    lease_token = concat(scope_id, ':', owner_epoch + 1, ':', txid_current()), \
    lease_expires_at = $3 + ($4 * interval '1 second'), acquired_at = $3, updated_at = $3 \
WHERE scope_id = $1 AND owner_kind = 'rust' \
  AND (lease_token IS NULL OR lease_expires_at IS NULL OR lease_expires_at <= $3) \
RETURNING scope_id, owner_id, owner_epoch, lease_token, lease_expires_at, acquired_at";

const RENEW_SQL: &str = "UPDATE agistack_cron_scheduler_owners \
SET lease_expires_at = $6 + ($7 * interval '1 second'), updated_at = $6 \
WHERE scope_id = $1 AND owner_kind = 'rust' AND owner_id = $2 \
  AND owner_epoch = $3 AND lease_token = $4 AND lease_expires_at = $5 \
  AND lease_expires_at > $6 \
RETURNING scope_id, owner_id, owner_epoch, lease_token, lease_expires_at, acquired_at";

const IS_CURRENT_SQL: &str = "SELECT EXISTS( \
    SELECT 1 FROM agistack_cron_scheduler_owners \
    WHERE scope_id = $1 AND owner_kind = 'rust' AND owner_id = $2 \
      AND owner_epoch = $3 AND lease_token = $4 AND lease_expires_at = $5 \
      AND lease_expires_at > $6)";

const RELEASE_SQL: &str = "UPDATE agistack_cron_scheduler_owners \
SET owner_id = NULL, lease_token = NULL, lease_expires_at = NULL, updated_at = $6 \
WHERE scope_id = $1 AND owner_kind = 'rust' AND owner_id = $2 \
  AND owner_epoch = $3 AND lease_token = $4 AND lease_expires_at = $5";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CronSchedulerLease {
    pub scope_id: String,
    pub owner_id: String,
    pub owner_epoch: i64,
    pub lease_token: String,
    pub lease_expires_at: DateTime<Utc>,
    pub acquired_at: DateTime<Utc>,
}

impl CronSchedulerLease {
    pub fn is_structurally_valid(&self) -> bool {
        self.scope_id == GLOBAL_CRON_SCHEDULER_SCOPE
            && !self.owner_id.trim().is_empty()
            && self.owner_epoch > 0
            && !self.lease_token.trim().is_empty()
            && self.lease_expires_at > self.acquired_at
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CronSchedulerOwnerError {
    InvalidLease,
    Storage(String),
}

impl fmt::Display for CronSchedulerOwnerError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::InvalidLease => "cron scheduler lease is invalid",
            Self::Storage(_) => "cron scheduler ownership storage failed",
        })
    }
}

impl std::error::Error for CronSchedulerOwnerError {}

#[derive(Clone)]
pub struct PgCronSchedulerOwnerRepository {
    pool: PgPool,
}

impl PgCronSchedulerOwnerRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    /// Acquire only when the control-plane row explicitly delegates to Rust.
    pub async fn try_acquire_global(
        &self,
        owner_id: &str,
        lease_seconds: i64,
        now: DateTime<Utc>,
    ) -> Result<Option<CronSchedulerLease>, CronSchedulerOwnerError> {
        validate_owner_id(owner_id)?;
        sqlx::query_as::<_, CronSchedulerLeaseRow>(ACQUIRE_SQL)
            .bind(GLOBAL_CRON_SCHEDULER_SCOPE)
            .bind(owner_id)
            .bind(now)
            .bind(positive_seconds(lease_seconds))
            .fetch_optional(&self.pool)
            .await
            .map_err(storage)?
            .map(TryInto::try_into)
            .transpose()
    }

    pub async fn renew(
        &self,
        lease: &CronSchedulerLease,
        lease_seconds: i64,
        now: DateTime<Utc>,
    ) -> Result<Option<CronSchedulerLease>, CronSchedulerOwnerError> {
        validate_lease(lease)?;
        sqlx::query_as::<_, CronSchedulerLeaseRow>(RENEW_SQL)
            .bind(&lease.scope_id)
            .bind(&lease.owner_id)
            .bind(lease.owner_epoch)
            .bind(&lease.lease_token)
            .bind(lease.lease_expires_at)
            .bind(now)
            .bind(positive_seconds(lease_seconds))
            .fetch_optional(&self.pool)
            .await
            .map_err(storage)?
            .map(TryInto::try_into)
            .transpose()
    }

    pub async fn is_current(
        &self,
        lease: &CronSchedulerLease,
        now: DateTime<Utc>,
    ) -> Result<bool, CronSchedulerOwnerError> {
        validate_lease(lease)?;
        sqlx::query_scalar::<_, bool>(IS_CURRENT_SQL)
            .bind(&lease.scope_id)
            .bind(&lease.owner_id)
            .bind(lease.owner_epoch)
            .bind(&lease.lease_token)
            .bind(lease.lease_expires_at)
            .bind(now)
            .fetch_one(&self.pool)
            .await
            .map_err(storage)
    }

    pub async fn release(
        &self,
        lease: &CronSchedulerLease,
        now: DateTime<Utc>,
    ) -> Result<bool, CronSchedulerOwnerError> {
        validate_lease(lease)?;
        sqlx::query(RELEASE_SQL)
            .bind(&lease.scope_id)
            .bind(&lease.owner_id)
            .bind(lease.owner_epoch)
            .bind(&lease.lease_token)
            .bind(lease.lease_expires_at)
            .bind(now)
            .execute(&self.pool)
            .await
            .map(|result| result.rows_affected() == 1)
            .map_err(storage)
    }
}

fn validate_owner_id(owner_id: &str) -> Result<(), CronSchedulerOwnerError> {
    if owner_id.trim().is_empty() || owner_id.len() > 255 {
        Err(CronSchedulerOwnerError::InvalidLease)
    } else {
        Ok(())
    }
}

fn validate_lease(lease: &CronSchedulerLease) -> Result<(), CronSchedulerOwnerError> {
    if lease.is_structurally_valid()
        && lease.owner_id.len() <= 255
        && lease.lease_token.len() <= 255
    {
        Ok(())
    } else {
        Err(CronSchedulerOwnerError::InvalidLease)
    }
}

fn positive_seconds(seconds: i64) -> i32 {
    i32::try_from(seconds.max(1)).unwrap_or(i32::MAX)
}

#[derive(sqlx::FromRow)]
struct CronSchedulerLeaseRow {
    scope_id: String,
    owner_id: Option<String>,
    owner_epoch: i64,
    lease_token: Option<String>,
    lease_expires_at: Option<DateTime<Utc>>,
    acquired_at: Option<DateTime<Utc>>,
}

impl TryFrom<CronSchedulerLeaseRow> for CronSchedulerLease {
    type Error = CronSchedulerOwnerError;

    fn try_from(row: CronSchedulerLeaseRow) -> Result<Self, Self::Error> {
        let lease = Self {
            scope_id: row.scope_id,
            owner_id: row.owner_id.ok_or(CronSchedulerOwnerError::InvalidLease)?,
            owner_epoch: row.owner_epoch,
            lease_token: row
                .lease_token
                .ok_or(CronSchedulerOwnerError::InvalidLease)?,
            lease_expires_at: row
                .lease_expires_at
                .ok_or(CronSchedulerOwnerError::InvalidLease)?,
            acquired_at: row
                .acquired_at
                .ok_or(CronSchedulerOwnerError::InvalidLease)?,
        };
        validate_lease(&lease)?;
        Ok(lease)
    }
}

fn storage(error: sqlx::Error) -> CronSchedulerOwnerError {
    CronSchedulerOwnerError::Storage(error.to_string())
}

impl From<CronSchedulerOwnerError> for CoreError {
    fn from(error: CronSchedulerOwnerError) -> Self {
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
    fn acquire_requires_explicit_rust_cutover_and_rotates_epoch_token() {
        let sql = compact(ACQUIRE_SQL);

        assert!(sql.contains("scope_id = $1 AND owner_kind = 'rust'"));
        assert!(sql.contains("owner_epoch = owner_epoch + 1"));
        assert!(sql.contains("lease_expires_at <= $3"));
        assert!(sql.contains("txid_current()"));
    }

    #[test]
    fn renew_requires_the_exact_unexpired_lease_snapshot() {
        let sql = compact(RENEW_SQL);

        assert!(sql.contains("owner_epoch = $3 AND lease_token = $4"));
        assert!(sql.contains("lease_expires_at = $5"));
        assert!(sql.contains("lease_expires_at > $6"));
    }

    #[test]
    fn release_cannot_use_a_pre_renewal_lease_snapshot() {
        let sql = compact(RELEASE_SQL);

        assert!(sql.contains("owner_epoch = $3 AND lease_token = $4"));
        assert!(sql.contains("lease_expires_at = $5"));
    }
}
