//! Shared ownership boundary for Rust cron scheduling and operation workers.

use agistack_adapters_postgres::{
    CronSchedulerLease, CronSchedulerOwnerError, PgCronSchedulerOwnerRepository,
};
use async_trait::async_trait;
use chrono::{DateTime, Utc};

#[async_trait]
pub(crate) trait CronSchedulerOwnershipStore: Send + Sync {
    async fn is_current(
        &self,
        lease: &CronSchedulerLease,
        now: DateTime<Utc>,
    ) -> Result<bool, CronSchedulerOwnerError>;
}

#[async_trait]
pub(crate) trait CronSchedulerLeaseStore: Send + Sync {
    async fn try_acquire_global(
        &self,
        owner_id: &str,
        lease_seconds: i64,
        now: DateTime<Utc>,
    ) -> Result<Option<CronSchedulerLease>, CronSchedulerOwnerError>;

    async fn renew(
        &self,
        lease: &CronSchedulerLease,
        lease_seconds: i64,
        now: DateTime<Utc>,
    ) -> Result<Option<CronSchedulerLease>, CronSchedulerOwnerError>;

    async fn release(
        &self,
        lease: &CronSchedulerLease,
        now: DateTime<Utc>,
    ) -> Result<bool, CronSchedulerOwnerError>;
}

#[async_trait]
impl CronSchedulerOwnershipStore for PgCronSchedulerOwnerRepository {
    async fn is_current(
        &self,
        lease: &CronSchedulerLease,
        now: DateTime<Utc>,
    ) -> Result<bool, CronSchedulerOwnerError> {
        PgCronSchedulerOwnerRepository::is_current(self, lease, now).await
    }
}

#[async_trait]
impl CronSchedulerLeaseStore for PgCronSchedulerOwnerRepository {
    async fn try_acquire_global(
        &self,
        owner_id: &str,
        lease_seconds: i64,
        now: DateTime<Utc>,
    ) -> Result<Option<CronSchedulerLease>, CronSchedulerOwnerError> {
        PgCronSchedulerOwnerRepository::try_acquire_global(self, owner_id, lease_seconds, now).await
    }

    async fn renew(
        &self,
        lease: &CronSchedulerLease,
        lease_seconds: i64,
        now: DateTime<Utc>,
    ) -> Result<Option<CronSchedulerLease>, CronSchedulerOwnerError> {
        PgCronSchedulerOwnerRepository::renew(self, lease, lease_seconds, now).await
    }

    async fn release(
        &self,
        lease: &CronSchedulerLease,
        now: DateTime<Utc>,
    ) -> Result<bool, CronSchedulerOwnerError> {
        PgCronSchedulerOwnerRepository::release(self, lease, now).await
    }
}
