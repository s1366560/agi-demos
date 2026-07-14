//! Durable `ReconcileSchedule` handler and deterministic next-fire projection.

#![allow(dead_code)]

use std::str::FromStr;
use std::sync::Arc;

use agistack_adapters_postgres::{
    CronOperationErrorCode, CronOperationKind, CronOperationRecord, CronScheduleMaterializedState,
    CronScheduleProjection, CronScheduleRepositoryError, CronScheduleSnapshot, CronScheduleStatus,
    PgCronScheduleRepository,
};
use agistack_core::ports::{CoreError, CoreResult};
use async_trait::async_trait;
use chrono::{DateTime, Duration, Utc};
use chrono_tz::Tz;
use croner::Cron;
use serde_json::json;
use sha2::{Digest, Sha256};

use crate::cron_worker::{
    CronOperationHandler, CronOperationHandlerFailure, CronOperationHandlerOutcome, CronWorkerClock,
};

#[async_trait]
pub(crate) trait CronScheduleStore: Send + Sync {
    async fn load_target(
        &self,
        operation: &CronOperationRecord,
    ) -> Result<CronScheduleSnapshot, CronScheduleRepositoryError>;

    async fn apply_projection(
        &self,
        operation: &CronOperationRecord,
        projection: &CronScheduleProjection,
        observed_at: DateTime<Utc>,
    ) -> Result<Option<CronScheduleMaterializedState>, CronScheduleRepositoryError>;
}

#[async_trait]
impl CronScheduleStore for PgCronScheduleRepository {
    async fn load_target(
        &self,
        operation: &CronOperationRecord,
    ) -> Result<CronScheduleSnapshot, CronScheduleRepositoryError> {
        PgCronScheduleRepository::load_target(self, operation).await
    }

    async fn apply_projection(
        &self,
        operation: &CronOperationRecord,
        projection: &CronScheduleProjection,
        observed_at: DateTime<Utc>,
    ) -> Result<Option<CronScheduleMaterializedState>, CronScheduleRepositoryError> {
        PgCronScheduleRepository::apply_projection(self, operation, projection, observed_at).await
    }
}

pub(crate) struct ReconcileScheduleHandler {
    store: Arc<dyn CronScheduleStore>,
    clock: Arc<dyn CronWorkerClock>,
}

impl ReconcileScheduleHandler {
    pub(crate) fn new(store: Arc<dyn CronScheduleStore>, clock: Arc<dyn CronWorkerClock>) -> Self {
        Self { store, clock }
    }
}

#[async_trait]
impl CronOperationHandler for ReconcileScheduleHandler {
    fn kind(&self) -> CronOperationKind {
        CronOperationKind::ReconcileSchedule
    }

    async fn handle(
        &self,
        operation: &CronOperationRecord,
    ) -> CoreResult<CronOperationHandlerOutcome> {
        let snapshot = match self.store.load_target(operation).await {
            Ok(snapshot) => snapshot,
            Err(error) => return repository_outcome(error),
        };
        let observed_at = self.clock.now();
        let projection = match project_schedule(&snapshot, observed_at) {
            Ok(projection) => projection,
            Err(_) => return Ok(invalid_schedule_failure()),
        };
        let materialized = match self
            .store
            .apply_projection(operation, &projection, observed_at)
            .await
        {
            Ok(materialized) => materialized,
            Err(error) => return repository_outcome(error),
        };
        let Some(materialized) = materialized else {
            return Ok(stale_schedule_failure());
        };

        Ok(CronOperationHandlerOutcome::Complete {
            result_json: json!({
                "job_id": snapshot.job_id,
                "job_revision": snapshot.job_revision,
                "schedule_revision": materialized.schedule_revision,
                "schedule_status": materialized.status.as_str(),
                "schedule_fingerprint": materialized.schedule_fingerprint,
                "next_fire_at": materialized.next_fire_at,
            }),
        })
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum ScheduleProjectionError {
    Invalid,
    Overflow,
}

pub(crate) fn project_schedule(
    snapshot: &CronScheduleSnapshot,
    observed_at: DateTime<Utc>,
) -> Result<CronScheduleProjection, ScheduleProjectionError> {
    let schedule_fingerprint = schedule_fingerprint(snapshot)?;
    if !snapshot.enabled {
        return Ok(CronScheduleProjection {
            status: CronScheduleStatus::Disabled,
            schedule_fingerprint,
            next_fire_at: None,
        });
    }
    if snapshot.stagger_seconds < 0 {
        return Err(ScheduleProjectionError::Invalid);
    }

    let (status, next_fire_at) = match snapshot.schedule_type.as_str() {
        "at" => {
            let run_at = required_string(&snapshot.schedule_config, "run_at")?;
            let run_at = parse_utc(run_at)?;
            let fire_at = add_seconds(run_at, i64::from(snapshot.stagger_seconds))?;
            if fire_at > observed_at {
                (CronScheduleStatus::Active, Some(fire_at))
            } else {
                (CronScheduleStatus::Exhausted, None)
            }
        }
        "every" => {
            let interval = snapshot
                .schedule_config
                .get("interval_seconds")
                .and_then(serde_json::Value::as_i64)
                .filter(|value| *value > 0)
                .ok_or(ScheduleProjectionError::Invalid)?;
            let anchor = snapshot
                .schedule_config
                .get("anchor_at")
                .and_then(serde_json::Value::as_str)
                .map(parse_utc)
                .transpose()?
                .unwrap_or(snapshot.created_at);
            let anchor = add_seconds(anchor, i64::from(snapshot.stagger_seconds))?;
            (
                CronScheduleStatus::Active,
                Some(next_interval_fire(anchor, interval, observed_at)?),
            )
        }
        "cron" => {
            let expression = required_string(&snapshot.schedule_config, "expr")?;
            let timezone = snapshot
                .schedule_config
                .get("timezone")
                .and_then(serde_json::Value::as_str)
                .unwrap_or(&snapshot.timezone);
            let timezone = Tz::from_str(timezone).map_err(|_| ScheduleProjectionError::Invalid)?;
            let cron = Cron::from_str(expression).map_err(|_| ScheduleProjectionError::Invalid)?;
            let stagger = i64::from(snapshot.stagger_seconds);
            let search_at = add_seconds(observed_at, -stagger)?;
            let next = cron
                .find_next_occurrence(&search_at.with_timezone(&timezone), false)
                .map_err(|_| ScheduleProjectionError::Invalid)?
                .with_timezone(&Utc);
            (
                CronScheduleStatus::Active,
                Some(add_seconds(next, stagger)?),
            )
        }
        _ => return Err(ScheduleProjectionError::Invalid),
    };

    Ok(CronScheduleProjection {
        status,
        schedule_fingerprint,
        next_fire_at,
    })
}

fn next_interval_fire(
    anchor: DateTime<Utc>,
    interval_seconds: i64,
    observed_at: DateTime<Utc>,
) -> Result<DateTime<Utc>, ScheduleProjectionError> {
    if anchor > observed_at {
        return Ok(anchor);
    }
    let elapsed_seconds = observed_at.signed_duration_since(anchor).num_seconds();
    let steps = elapsed_seconds
        .checked_div(interval_seconds)
        .and_then(|value| value.checked_add(1))
        .ok_or(ScheduleProjectionError::Overflow)?;
    let delta_seconds = interval_seconds
        .checked_mul(steps)
        .ok_or(ScheduleProjectionError::Overflow)?;
    add_seconds(anchor, delta_seconds)
}

fn schedule_fingerprint(
    snapshot: &CronScheduleSnapshot,
) -> Result<String, ScheduleProjectionError> {
    let canonical = json!({
        "enabled": snapshot.enabled,
        "schedule_config": snapshot.schedule_config,
        "schedule_type": snapshot.schedule_type,
        "stagger_seconds": snapshot.stagger_seconds,
        "timezone": snapshot.timezone,
    });
    let encoded = serde_json::to_vec(&canonical).map_err(|_| ScheduleProjectionError::Invalid)?;
    Ok(format!("{:x}", Sha256::digest(encoded)))
}

fn required_string<'a>(
    value: &'a serde_json::Value,
    field: &str,
) -> Result<&'a str, ScheduleProjectionError> {
    value
        .get(field)
        .and_then(serde_json::Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .ok_or(ScheduleProjectionError::Invalid)
}

fn parse_utc(value: &str) -> Result<DateTime<Utc>, ScheduleProjectionError> {
    DateTime::parse_from_rfc3339(value)
        .map(|value| value.with_timezone(&Utc))
        .map_err(|_| ScheduleProjectionError::Invalid)
}

fn add_seconds(
    value: DateTime<Utc>,
    seconds: i64,
) -> Result<DateTime<Utc>, ScheduleProjectionError> {
    value
        .checked_add_signed(Duration::seconds(seconds))
        .ok_or(ScheduleProjectionError::Overflow)
}

fn repository_outcome(
    error: CronScheduleRepositoryError,
) -> CoreResult<CronOperationHandlerOutcome> {
    match error {
        CronScheduleRepositoryError::Storage(_) => Err(CoreError::Storage(
            "cron schedule reconciliation storage failed".to_string(),
        )),
        CronScheduleRepositoryError::StaleRevision => Ok(stale_schedule_failure()),
        CronScheduleRepositoryError::NotFound
        | CronScheduleRepositoryError::InvalidOperation
        | CronScheduleRepositoryError::InvalidProjection => Ok(invalid_schedule_failure()),
    }
}

fn stale_schedule_failure() -> CronOperationHandlerOutcome {
    CronOperationHandlerOutcome::RetryOrDeadLetter(CronOperationHandlerFailure {
        code: CronOperationErrorCode::StaleRevision,
        redacted_text: "cron schedule revision is stale".to_string(),
        retry_after_seconds: 5,
    })
}

fn invalid_schedule_failure() -> CronOperationHandlerOutcome {
    CronOperationHandlerOutcome::RetryOrDeadLetter(CronOperationHandlerFailure {
        code: CronOperationErrorCode::InvalidOperation,
        redacted_text: "cron schedule reconciliation is invalid".to_string(),
        retry_after_seconds: 5,
    })
}

#[cfg(test)]
mod tests;
