//! Crash-safe projection of due schedule cursors into durable Agent runs.

#![allow(dead_code)]

use std::sync::Arc;

use agistack_adapters_postgres::{
    CronDueSchedule, CronOperationScope, CronScheduleFireError, CronScheduleProjection,
    CronScheduledFireResult, CronSchedulerLease, CronSchedulerOwnerError, NewCronScheduledFire,
    PgCronScheduleFireRepository,
};
use agistack_core::ports::{CoreError, CoreResult};
use async_trait::async_trait;
use chrono::{DateTime, SecondsFormat, Utc};
use uuid::Uuid;

use crate::cron_schedule_reconcile::project_schedule;
use crate::cron_scheduler_ownership::CronSchedulerOwnershipStore;
use crate::cron_worker::CronWorkerClock;

const FIRE_ID_NAMESPACE: Uuid = Uuid::from_u128(0xc4cc_1312_862e_4f4a_9ea0_3860_e4e4_c761);

#[async_trait]
pub(crate) trait CronScheduleFireStore: Send + Sync {
    async fn list_due(
        &self,
        scope: CronOperationScope<'_>,
        now: DateTime<Utc>,
        limit: i64,
    ) -> Result<Vec<CronDueSchedule>, CronScheduleFireError>;

    async fn commit_fire(
        &self,
        scope: CronOperationScope<'_>,
        candidate: &CronDueSchedule,
        next: &CronScheduleProjection,
        fire: &NewCronScheduledFire,
        authority: &CronSchedulerLease,
        observed_at: DateTime<Utc>,
    ) -> Result<Option<CronScheduledFireResult>, CronScheduleFireError>;
}

#[async_trait]
impl CronScheduleFireStore for PgCronScheduleFireRepository {
    async fn list_due(
        &self,
        scope: CronOperationScope<'_>,
        now: DateTime<Utc>,
        limit: i64,
    ) -> Result<Vec<CronDueSchedule>, CronScheduleFireError> {
        PgCronScheduleFireRepository::list_due(self, scope, now, limit).await
    }

    async fn commit_fire(
        &self,
        scope: CronOperationScope<'_>,
        candidate: &CronDueSchedule,
        next: &CronScheduleProjection,
        fire: &NewCronScheduledFire,
        authority: &CronSchedulerLease,
        observed_at: DateTime<Utc>,
    ) -> Result<Option<CronScheduledFireResult>, CronScheduleFireError> {
        PgCronScheduleFireRepository::commit_fire(
            self,
            scope,
            candidate,
            next,
            fire,
            authority,
            observed_at,
        )
        .await
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct CronScheduleFireSummary {
    pub due: usize,
    pub committed: usize,
    pub lost_compare_and_set: usize,
}

pub(crate) struct CronScheduleFireCoordinator {
    store: Arc<dyn CronScheduleFireStore>,
    ownership: Arc<dyn CronSchedulerOwnershipStore>,
    clock: Arc<dyn CronWorkerClock>,
}

impl CronScheduleFireCoordinator {
    pub(crate) fn new(
        store: Arc<dyn CronScheduleFireStore>,
        ownership: Arc<dyn CronSchedulerOwnershipStore>,
        clock: Arc<dyn CronWorkerClock>,
    ) -> Self {
        Self {
            store,
            ownership,
            clock,
        }
    }

    pub(crate) async fn fire_due(
        &self,
        authority: &CronSchedulerLease,
        tenant_id: &str,
        project_id: &str,
        limit: i64,
    ) -> CoreResult<CronScheduleFireSummary> {
        let scope = validated_scope(tenant_id, project_id)?;
        let observed_at = self.clock.now();
        if !authority.is_structurally_valid()
            || authority.lease_expires_at <= observed_at
            || !self
                .ownership
                .is_current(authority, observed_at)
                .await
                .map_err(redacted_ownership)?
        {
            return Err(CoreError::Storage(
                "cron scheduler authority is not current".to_string(),
            ));
        }
        let candidates = self
            .store
            .list_due(scope, observed_at, limit)
            .await
            .map_err(redacted_storage)?;
        let mut committed = 0;
        let mut lost_compare_and_set = 0;
        for candidate in &candidates {
            validate_candidate(scope, candidate, observed_at)?;
            let next =
                project_schedule(&candidate.snapshot, candidate.scheduled_for).map_err(|_| {
                    CoreError::Storage("cron scheduled fire projection is invalid".to_string())
                })?;
            if next.schedule_fingerprint != candidate.schedule_fingerprint {
                return Err(CoreError::Storage(
                    "cron scheduled fire fingerprint changed".to_string(),
                ));
            }
            let fire = deterministic_fire(candidate);
            match self
                .store
                .commit_fire(scope, candidate, &next, &fire, authority, observed_at)
                .await
                .map_err(redacted_storage)?
            {
                Some(_) => committed += 1,
                None => lost_compare_and_set += 1,
            }
        }
        Ok(CronScheduleFireSummary {
            due: candidates.len(),
            committed,
            lost_compare_and_set,
        })
    }
}

fn validated_scope<'a>(
    tenant_id: &'a str,
    project_id: &'a str,
) -> CoreResult<CronOperationScope<'a>> {
    if tenant_id.trim().is_empty() || project_id.trim().is_empty() {
        return Err(CoreError::Storage(
            "cron scheduled fire scope is invalid".to_string(),
        ));
    }
    Ok(CronOperationScope {
        tenant_id,
        project_id,
    })
}

fn validate_candidate(
    scope: CronOperationScope<'_>,
    candidate: &CronDueSchedule,
    observed_at: DateTime<Utc>,
) -> CoreResult<()> {
    let actor_is_valid = candidate
        .actor_user_id
        .as_deref()
        .is_some_and(|value| !value.trim().is_empty());
    if candidate.snapshot.tenant_id != scope.tenant_id
        || candidate.snapshot.project_id != scope.project_id
        || candidate.snapshot.job_id.trim().is_empty()
        || candidate.snapshot.job_revision <= 0
        || candidate.snapshot.schedule_revision <= 0
        || candidate.schedule_fingerprint.trim().is_empty()
        || candidate.scheduled_for > observed_at
        || !actor_is_valid
    {
        return Err(CoreError::Storage(
            "cron scheduled fire candidate is invalid".to_string(),
        ));
    }
    Ok(())
}

fn deterministic_fire(candidate: &CronDueSchedule) -> NewCronScheduledFire {
    let cursor = format!(
        "{}:{}:{}:{}",
        candidate.snapshot.tenant_id,
        candidate.snapshot.project_id,
        candidate.snapshot.job_id,
        candidate
            .scheduled_for
            .to_rfc3339_opts(SecondsFormat::Micros, true)
    );
    NewCronScheduledFire {
        run_id: Uuid::new_v5(&FIRE_ID_NAMESPACE, format!("run:{cursor}").as_bytes()).to_string(),
        operation_id: Uuid::new_v5(&FIRE_ID_NAMESPACE, format!("operation:{cursor}").as_bytes())
            .to_string(),
        idempotency_key: format!(
            "scheduled:{}:{}",
            candidate.snapshot.schedule_revision,
            candidate
                .scheduled_for
                .to_rfc3339_opts(SecondsFormat::Micros, true)
        ),
    }
}

fn redacted_storage(_error: CronScheduleFireError) -> CoreError {
    CoreError::Storage("cron scheduled fire storage failed".to_string())
}

fn redacted_ownership(_error: CronSchedulerOwnerError) -> CoreError {
    CoreError::Storage("cron scheduler ownership storage failed".to_string())
}

#[cfg(test)]
mod tests;
