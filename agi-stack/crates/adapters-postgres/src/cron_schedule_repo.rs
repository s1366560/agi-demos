//! Durable materialized schedule state for cron reconciliation.

use std::fmt;

use agistack_core::ports::CoreError;
use serde_json::Value;
use sqlx::types::chrono::{DateTime, Utc};

use crate::{CronOperationKind, CronOperationRecord, PgPool};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CronScheduleStatus {
    Active,
    Disabled,
    Exhausted,
}

impl CronScheduleStatus {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Active => "active",
            Self::Disabled => "disabled",
            Self::Exhausted => "exhausted",
        }
    }
}

impl TryFrom<&str> for CronScheduleStatus {
    type Error = CronScheduleRepositoryError;

    fn try_from(value: &str) -> Result<Self, Self::Error> {
        match value {
            "active" => Ok(Self::Active),
            "disabled" => Ok(Self::Disabled),
            "exhausted" => Ok(Self::Exhausted),
            _ => Err(CronScheduleRepositoryError::InvalidProjection),
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct CronScheduleSnapshot {
    pub job_id: String,
    pub tenant_id: String,
    pub project_id: String,
    pub job_revision: i64,
    pub schedule_revision: i64,
    pub enabled: bool,
    pub schedule_type: String,
    pub schedule_config: Value,
    pub timezone: String,
    pub stagger_seconds: i32,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CronScheduleProjection {
    pub status: CronScheduleStatus,
    pub schedule_fingerprint: String,
    pub next_fire_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CronScheduleMaterializedState {
    pub schedule_revision: i64,
    pub status: CronScheduleStatus,
    pub schedule_fingerprint: String,
    pub next_fire_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CronScheduleRepositoryError {
    NotFound,
    StaleRevision,
    InvalidOperation,
    InvalidProjection,
    Storage(String),
}

impl fmt::Display for CronScheduleRepositoryError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let message = match self {
            Self::NotFound => "cron schedule target not found",
            Self::StaleRevision => "cron schedule revision is stale",
            Self::InvalidOperation => "cron schedule operation is invalid",
            Self::InvalidProjection => "cron schedule projection is invalid",
            Self::Storage(_) => "cron schedule storage failed",
        };
        formatter.write_str(message)
    }
}

impl std::error::Error for CronScheduleRepositoryError {}

pub struct PgCronScheduleRepository {
    pool: PgPool,
}

impl PgCronScheduleRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn load_target(
        &self,
        operation: &CronOperationRecord,
    ) -> Result<CronScheduleSnapshot, CronScheduleRepositoryError> {
        let expected_schedule_revision = expected_schedule_revision(operation)?;
        let row = sqlx::query_as::<_, CronScheduleSnapshotRow>(
            "SELECT id AS job_id, tenant_id, project_id, revision AS job_revision, \
                    schedule_revision, enabled, schedule_type, schedule_config, timezone, \
                    stagger_seconds, created_at \
             FROM cron_jobs \
             WHERE id = $1 AND tenant_id = $2 AND project_id = $3",
        )
        .bind(&operation.job_id)
        .bind(&operation.tenant_id)
        .bind(&operation.project_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .ok_or(CronScheduleRepositoryError::NotFound)?;
        if row.schedule_revision != expected_schedule_revision {
            return Err(CronScheduleRepositoryError::StaleRevision);
        }
        Ok(row.into())
    }

    /// Apply a materialized cursor only while the source schedule revision is current.
    pub async fn apply_projection(
        &self,
        operation: &CronOperationRecord,
        projection: &CronScheduleProjection,
        observed_at: DateTime<Utc>,
    ) -> Result<Option<CronScheduleMaterializedState>, CronScheduleRepositoryError> {
        let schedule_revision = expected_schedule_revision(operation)?;
        validate_projection(projection)?;
        sqlx::query_as::<_, CronScheduleStateRow>(
            "INSERT INTO agistack_cron_schedule_state ( \
                job_id, tenant_id, project_id, schedule_revision, status, \
                schedule_fingerprint, next_fire_at, last_error_code, updated_at \
             ) SELECT job.id, job.tenant_id, job.project_id, job.schedule_revision, $5, $6, $7, \
                      NULL, $8 \
             FROM cron_jobs AS job \
             WHERE job.id = $1 AND job.tenant_id = $2 AND job.project_id = $3 \
               AND job.schedule_revision = $4 \
             ON CONFLICT (job_id) DO UPDATE SET \
                tenant_id = CASE \
                    WHEN agistack_cron_schedule_state.schedule_revision < EXCLUDED.schedule_revision \
                    THEN EXCLUDED.tenant_id ELSE agistack_cron_schedule_state.tenant_id END, \
                project_id = CASE \
                    WHEN agistack_cron_schedule_state.schedule_revision < EXCLUDED.schedule_revision \
                    THEN EXCLUDED.project_id ELSE agistack_cron_schedule_state.project_id END, \
                schedule_revision = GREATEST( \
                    agistack_cron_schedule_state.schedule_revision, EXCLUDED.schedule_revision), \
                status = CASE \
                    WHEN agistack_cron_schedule_state.schedule_revision < EXCLUDED.schedule_revision \
                    THEN EXCLUDED.status ELSE agistack_cron_schedule_state.status END, \
                schedule_fingerprint = CASE \
                    WHEN agistack_cron_schedule_state.schedule_revision < EXCLUDED.schedule_revision \
                    THEN EXCLUDED.schedule_fingerprint \
                    ELSE agistack_cron_schedule_state.schedule_fingerprint END, \
                next_fire_at = CASE \
                    WHEN agistack_cron_schedule_state.schedule_revision < EXCLUDED.schedule_revision \
                    THEN EXCLUDED.next_fire_at ELSE agistack_cron_schedule_state.next_fire_at END, \
                last_error_code = CASE \
                    WHEN agistack_cron_schedule_state.schedule_revision < EXCLUDED.schedule_revision \
                    THEN NULL ELSE agistack_cron_schedule_state.last_error_code END, \
                updated_at = CASE \
                    WHEN agistack_cron_schedule_state.schedule_revision < EXCLUDED.schedule_revision \
                    THEN EXCLUDED.updated_at ELSE agistack_cron_schedule_state.updated_at END \
             WHERE agistack_cron_schedule_state.schedule_revision < EXCLUDED.schedule_revision \
                OR (agistack_cron_schedule_state.schedule_revision = EXCLUDED.schedule_revision \
                    AND agistack_cron_schedule_state.schedule_fingerprint = \
                        EXCLUDED.schedule_fingerprint) \
             RETURNING schedule_revision, status, schedule_fingerprint, next_fire_at",
        )
        .bind(&operation.job_id)
        .bind(&operation.tenant_id)
        .bind(&operation.project_id)
        .bind(schedule_revision)
        .bind(projection.status.as_str())
        .bind(&projection.schedule_fingerprint)
        .bind(projection.next_fire_at)
        .bind(observed_at)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?
        .map(TryInto::try_into)
        .transpose()
    }
}

fn expected_schedule_revision(
    operation: &CronOperationRecord,
) -> Result<i64, CronScheduleRepositoryError> {
    if operation.kind != CronOperationKind::ReconcileSchedule {
        return Err(CronScheduleRepositoryError::InvalidOperation);
    }
    operation
        .schedule_revision
        .filter(|revision| *revision > 0)
        .ok_or(CronScheduleRepositoryError::InvalidOperation)
}

fn validate_projection(
    projection: &CronScheduleProjection,
) -> Result<(), CronScheduleRepositoryError> {
    let fingerprint_is_sha256 = projection.schedule_fingerprint.len() == 64
        && projection
            .schedule_fingerprint
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit());
    let cursor_matches_status = match projection.status {
        CronScheduleStatus::Active => projection.next_fire_at.is_some(),
        CronScheduleStatus::Disabled | CronScheduleStatus::Exhausted => {
            projection.next_fire_at.is_none()
        }
    };
    if fingerprint_is_sha256 && cursor_matches_status {
        Ok(())
    } else {
        Err(CronScheduleRepositoryError::InvalidProjection)
    }
}

#[derive(sqlx::FromRow)]
struct CronScheduleSnapshotRow {
    job_id: String,
    tenant_id: String,
    project_id: String,
    job_revision: i64,
    schedule_revision: i64,
    enabled: bool,
    schedule_type: String,
    schedule_config: Value,
    timezone: String,
    stagger_seconds: i32,
    created_at: DateTime<Utc>,
}

#[derive(sqlx::FromRow)]
struct CronScheduleStateRow {
    schedule_revision: i64,
    status: String,
    schedule_fingerprint: String,
    next_fire_at: Option<DateTime<Utc>>,
}

impl From<CronScheduleSnapshotRow> for CronScheduleSnapshot {
    fn from(row: CronScheduleSnapshotRow) -> Self {
        Self {
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
        }
    }
}

impl TryFrom<CronScheduleStateRow> for CronScheduleMaterializedState {
    type Error = CronScheduleRepositoryError;

    fn try_from(row: CronScheduleStateRow) -> Result<Self, Self::Error> {
        Ok(Self {
            schedule_revision: row.schedule_revision,
            status: CronScheduleStatus::try_from(row.status.as_str())?,
            schedule_fingerprint: row.schedule_fingerprint,
            next_fire_at: row.next_fire_at,
        })
    }
}

fn storage(error: sqlx::Error) -> CronScheduleRepositoryError {
    CronScheduleRepositoryError::Storage(error.to_string())
}

impl From<CronScheduleRepositoryError> for CoreError {
    fn from(error: CronScheduleRepositoryError) -> Self {
        CoreError::Storage(error.to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn active_projection_requires_a_sha256_fingerprint_and_cursor() {
        let projection = CronScheduleProjection {
            status: CronScheduleStatus::Active,
            schedule_fingerprint: "a".repeat(64),
            next_fire_at: None,
        };

        assert_eq!(
            validate_projection(&projection),
            Err(CronScheduleRepositoryError::InvalidProjection)
        );
    }
}
