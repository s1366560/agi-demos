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
impl CronSchedulerOwnershipStore for PgCronSchedulerOwnerRepository {
    async fn is_current(
        &self,
        lease: &CronSchedulerLease,
        now: DateTime<Utc>,
    ) -> Result<bool, CronSchedulerOwnerError> {
        PgCronSchedulerOwnerRepository::is_current(self, lease, now).await
    }
}
