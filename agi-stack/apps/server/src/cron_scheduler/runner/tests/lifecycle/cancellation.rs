use super::*;

struct DelayedStore {
    inner: Ownership,
    delay_acquire: bool,
    acquire_entered: Notify,
    acquire_finish: Semaphore,
    delay_release: bool,
    release_entered: Notify,
    release_finish: Semaphore,
}

#[async_trait]
impl CronSchedulerLeaseStore for DelayedStore {
    async fn try_acquire_global(
        &self,
        owner: &str,
        seconds: i64,
        now: DateTime<Utc>,
    ) -> Result<Option<CronSchedulerLease>, CronSchedulerOwnerError> {
        self.acquire_entered.notify_one();
        if self.delay_acquire {
            self.acquire_finish.acquire().await.unwrap().forget();
        }
        self.inner.try_acquire_global(owner, seconds, now).await
    }

    async fn renew(
        &self,
        lease: &CronSchedulerLease,
        seconds: i64,
        now: DateTime<Utc>,
    ) -> Result<Option<CronSchedulerLease>, CronSchedulerOwnerError> {
        self.inner.renew(lease, seconds, now).await
    }

    async fn release(
        &self,
        lease: &CronSchedulerLease,
        now: DateTime<Utc>,
    ) -> Result<bool, CronSchedulerOwnerError> {
        self.release_entered.notify_one();
        if self.delay_release {
            self.release_finish.acquire().await.unwrap().forget();
        }
        self.inner.release(lease, now).await
    }
}

fn fixture(
    delay_acquire: bool,
    delay_release: bool,
) -> (Arc<CronScheduler>, Arc<DelayedStore>, Arc<Driver>) {
    let store = Arc::new(DelayedStore {
        inner: Ownership::default(),
        delay_acquire,
        delay_release,
        acquire_entered: Notify::new(),
        acquire_finish: Semaphore::new(0),
        release_entered: Notify::new(),
        release_finish: Semaphore::new(0),
    });
    let driver = Arc::new(Driver {
        polls: AtomicUsize::new(0),
        control_starts: AtomicUsize::new(0),
        runtime_starts: AtomicUsize::new(0),
        settled: AtomicUsize::new(0),
        block_control: false,
        block_runtime: false,
        entered: Notify::new(),
        finish: Semaphore::new(0),
    });
    let scheduler = Arc::new(CronScheduler::new(
        store.clone(),
        driver.clone(),
        Arc::new(crate::cron_worker::UtcCronWorkerClock),
        CronSchedulerConfig {
            owner_lease_seconds: 1,
            max_scope_pages: 1,
            poll_interval: Duration::from_millis(5),
            ..enabled_config()
        },
    ));
    (scheduler, store, driver)
}

#[tokio::test]
async fn acquire_completing_after_shutdown_releases_without_admitting_work() {
    let (scheduler, store, driver) = fixture(true, false);
    let runtime = scheduler.spawn_if_enabled().unwrap();
    tokio::time::timeout(Duration::from_secs(2), store.acquire_entered.notified())
        .await
        .unwrap();
    runtime.request_stop();
    store.acquire_finish.add_permits(1);
    tokio::time::timeout(Duration::from_secs(2), runtime.shutdown())
        .await
        .unwrap()
        .unwrap();
    assert_eq!(driver.polls.load(Ordering::SeqCst), 0);
    assert_eq!(driver.control_starts.load(Ordering::SeqCst), 0);
    assert_eq!(driver.runtime_starts.load(Ordering::SeqCst), 0);
    assert_eq!(store.inner.releases.load(Ordering::SeqCst), 1);
}

#[tokio::test]
async fn stalled_owner_release_cannot_hold_settled_generation_forever() {
    let (scheduler, store, driver) = fixture(false, true);
    let runtime = scheduler.spawn_if_enabled().unwrap();
    wait_count(&driver.polls, 1).await;
    runtime.request_stop();
    tokio::time::timeout(Duration::from_secs(2), store.release_entered.notified())
        .await
        .unwrap();
    let finished = tokio::time::timeout(Duration::from_secs(2), runtime.shutdown()).await;
    // Clean up the intentionally stalled pre-fix worker before reporting RED.
    store.release_finish.add_permits(1);
    runtime.shutdown().await.unwrap();
    assert!(
        finished.is_ok(),
        "settled generation cannot wait without a release deadline"
    );
}

#[tokio::test]
async fn expired_local_snapshot_is_not_a_capability_while_loss_notification_waits() {
    struct MovingClock(Mutex<DateTime<Utc>>);
    impl CronWorkerClock for MovingClock {
        fn now(&self) -> DateTime<Utc> {
            *self.0.lock().unwrap()
        }
    }
    let (mut scheduler, _, _) = fixture(false, false);
    let clock = Arc::new(MovingClock(Mutex::new(Utc::now())));
    Arc::get_mut(&mut scheduler).unwrap().clock = clock.clone();
    let (_stop, shutdown) = watch::channel(false);
    let owner = Arc::new(
        OwnerLifecycle::acquire(&scheduler, shutdown)
            .await
            .unwrap()
            .unwrap(),
    );
    let waiter = {
        let owner = owner.clone();
        tokio::spawn(async move { owner.lost().await })
    };
    tokio::task::yield_now().await;
    *clock.0.lock().unwrap() += chrono::Duration::seconds(2);
    assert!(
        owner.current().is_none(),
        "expired snapshot cannot authorize another scope"
    );
    // Waiting for the watch notification does not make the capability current.
    tokio::time::timeout(Duration::from_secs(2), waiter)
        .await
        .unwrap()
        .unwrap();
    assert!(owner.current().is_none());
    owner.stop().await;
}
