use super::*;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use tokio::sync::{Notify, Semaphore};

#[derive(Default)]
struct Ownership {
    current: Mutex<Option<CronSchedulerLease>>,
    acquisitions: AtomicUsize,
    renewals: AtomicUsize,
    releases: AtomicUsize,
    revoked: AtomicBool,
    renewal_failure: AtomicBool,
    renewal_stalled: AtomicBool,
    changed: Notify,
}

#[async_trait]
impl CronSchedulerLeaseStore for Ownership {
    async fn try_acquire_global(
        &self,
        owner_id: &str,
        seconds: i64,
        now: DateTime<Utc>,
    ) -> Result<Option<CronSchedulerLease>, CronSchedulerOwnerError> {
        let mut current = self.current.lock().unwrap();
        if self.revoked.load(Ordering::SeqCst)
            || current
                .as_ref()
                .is_some_and(|lease| lease.lease_expires_at > now)
        {
            return Ok(None);
        }
        let epoch = self.acquisitions.fetch_add(1, Ordering::SeqCst) as i64 + 1;
        let lease = CronSchedulerLease {
            scope_id: "global".into(),
            owner_id: owner_id.into(),
            owner_epoch: epoch,
            lease_token: format!("lease-{epoch}"),
            acquired_at: now,
            lease_expires_at: now + chrono::Duration::seconds(seconds),
        };
        *current = Some(lease.clone());
        Ok(Some(lease))
    }

    async fn renew(
        &self,
        lease: &CronSchedulerLease,
        seconds: i64,
        now: DateTime<Utc>,
    ) -> Result<Option<CronSchedulerLease>, CronSchedulerOwnerError> {
        self.renewals.fetch_add(1, Ordering::SeqCst);
        self.changed.notify_one();
        if self.renewal_stalled.load(Ordering::SeqCst) {
            std::future::pending::<()>().await;
        }
        if self.renewal_failure.load(Ordering::SeqCst) {
            return Err(CronSchedulerOwnerError::Storage(
                "injected unavailable storage".into(),
            ));
        }
        let mut current = self.current.lock().unwrap();
        if self.revoked.load(Ordering::SeqCst)
            || !current.as_ref().is_some_and(|row| {
                row.lease_token == lease.lease_token && row.lease_expires_at > now
            })
        {
            return Ok(None);
        }
        let mut renewed = lease.clone();
        renewed.lease_expires_at = now + chrono::Duration::seconds(seconds);
        *current = Some(renewed.clone());
        Ok(Some(renewed))
    }

    async fn release(
        &self,
        lease: &CronSchedulerLease,
        _now: DateTime<Utc>,
    ) -> Result<bool, CronSchedulerOwnerError> {
        let mut current = self.current.lock().unwrap();
        let matches = current
            .as_ref()
            .is_some_and(|row| row.lease_token == lease.lease_token);
        if matches {
            *current = None;
            self.releases.fetch_add(1, Ordering::SeqCst);
            self.changed.notify_one();
        }
        Ok(matches)
    }
}

struct Driver {
    polls: AtomicUsize,
    control_starts: AtomicUsize,
    runtime_starts: AtomicUsize,
    settled: AtomicUsize,
    block_control: bool,
    block_runtime: bool,
    entered: Notify,
    finish: Semaphore,
}

#[async_trait]
impl CronSchedulerDriver for Driver {
    async fn list_work_scopes(
        &self,
        _authority: &CronSchedulerLease,
        _after: Option<&CronControlScope>,
        _limit: i64,
        _now: DateTime<Utc>,
    ) -> CoreResult<Vec<CronControlScope>> {
        self.polls.fetch_add(1, Ordering::SeqCst);
        Ok(vec![scope("first"), scope("second")])
    }

    async fn drive_control_scope(
        &self,
        _authority: &CronSchedulerLease,
        _scope: &CronControlScope,
    ) -> CoreResult<CronScopeControlReport> {
        self.control_starts.fetch_add(1, Ordering::SeqCst);
        if self.block_control {
            self.entered.notify_one();
            self.finish.acquire().await.unwrap().forget();
            self.settled.fetch_add(1, Ordering::SeqCst);
        }
        Ok(CronScopeControlReport::default())
    }

    async fn drive_runtime_scope(&self, _scope: &CronControlScope) -> CoreResult<()> {
        self.runtime_starts.fetch_add(1, Ordering::SeqCst);
        if self.block_runtime {
            self.entered.notify_one();
            self.finish.acquire().await.unwrap().forget();
            self.settled.fetch_add(1, Ordering::SeqCst);
        }
        Ok(())
    }
}

fn start(
    block_control: bool,
    block_runtime: bool,
) -> (CronSchedulerRuntime, Arc<Ownership>, Arc<Driver>) {
    let ownership = Arc::new(Ownership::default());
    let driver = Arc::new(Driver {
        polls: AtomicUsize::new(0),
        control_starts: AtomicUsize::new(0),
        runtime_starts: AtomicUsize::new(0),
        settled: AtomicUsize::new(0),
        block_control,
        block_runtime,
        entered: Notify::new(),
        finish: Semaphore::new(0),
    });
    let scheduler = Arc::new(CronScheduler::new(
        ownership.clone(),
        driver.clone(),
        Arc::new(crate::cron_worker::UtcCronWorkerClock),
        CronSchedulerConfig {
            owner_lease_seconds: 1,
            max_scope_pages: 1,
            poll_interval: Duration::from_millis(5),
            ..enabled_config()
        },
    ));
    (scheduler.spawn_if_enabled().unwrap(), ownership, driver)
}

async fn wait_count(counter: &AtomicUsize, expected: usize) {
    tokio::time::timeout(Duration::from_secs(3), async {
        while counter.load(Ordering::SeqCst) < expected {
            tokio::time::sleep(Duration::from_millis(5)).await;
        }
    })
    .await
    .unwrap();
}

#[tokio::test]
async fn idle_polls_retain_one_owner_generation_until_shutdown() {
    let (runtime, ownership, driver) = start(false, false);
    wait_count(&driver.polls, 3).await;
    let acquisitions = ownership.acquisitions.load(Ordering::SeqCst);
    let held = ownership.current.lock().unwrap().is_some();
    runtime.shutdown().await.unwrap();
    assert_eq!(acquisitions, 1);
    assert!(held);
    assert_eq!(ownership.releases.load(Ordering::SeqCst), 1);
}

#[tokio::test]
async fn timed_renewal_continues_during_control_and_runtime_work() {
    for block_control in [true, false] {
        let (runtime, ownership, driver) = start(block_control, !block_control);
        driver.entered.notified().await;
        let renewed =
            tokio::time::timeout(Duration::from_secs(2), ownership.changed.notified()).await;
        runtime.request_stop();
        driver.finish.add_permits(1);
        runtime.shutdown().await.unwrap();
        assert!(renewed.is_ok(), "renewal must not wait for active work");
        assert!(ownership.renewals.load(Ordering::SeqCst) > 0);
        assert_eq!(driver.settled.load(Ordering::SeqCst), 1);
    }
}

#[tokio::test]
async fn ownership_loss_stops_new_admission_without_aborting_active_work() {
    for block_control in [true, false] {
        let (runtime, ownership, driver) = start(block_control, !block_control);
        driver.entered.notified().await;
        ownership.revoked.store(true, Ordering::SeqCst);
        wait_count(&ownership.releases, 1).await;
        assert_eq!(driver.settled.load(Ordering::SeqCst), 0);
        driver.finish.add_permits(1);
        wait_count(&driver.settled, 1).await;
        runtime.shutdown().await.unwrap();
        assert_eq!(
            driver.control_starts.load(Ordering::SeqCst),
            if block_control { 1 } else { 2 }
        );
        assert_eq!(
            driver.runtime_starts.load(Ordering::SeqCst),
            usize::from(!block_control)
        );
    }
}

#[tokio::test]
async fn renewal_storage_error_or_deadline_stops_control_without_cancelling_runtime() {
    for stalled in [false, true] {
        let (runtime, ownership, driver) = start(false, true);
        ownership.renewal_failure.store(!stalled, Ordering::SeqCst);
        ownership.renewal_stalled.store(stalled, Ordering::SeqCst);
        driver.entered.notified().await;
        wait_count(&ownership.releases, 1).await;
        assert_eq!(driver.settled.load(Ordering::SeqCst), 0);
        runtime.request_stop();
        driver.finish.add_permits(1);
        runtime.shutdown().await.unwrap();
        assert_eq!(driver.settled.load(Ordering::SeqCst), 1);
        assert_eq!(driver.runtime_starts.load(Ordering::SeqCst), 1);
    }
}
