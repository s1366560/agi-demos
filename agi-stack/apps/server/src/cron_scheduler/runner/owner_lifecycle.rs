//! Control ownership is renewed independently of admitted execution futures.

use std::{sync::Arc, time::Duration};

use agistack_adapters_postgres::CronSchedulerLease;
use agistack_core::ports::CoreResult;
use tokio::sync::watch;

use super::{ownership_error, CronScheduler};
use crate::cron_scheduler_ownership::CronSchedulerLeaseStore;
use crate::cron_worker::CronWorkerClock;
use crate::worker_lifecycle_v2::WorkerRuntimeV2;

pub(super) struct OwnerLifecycle {
    authority: watch::Receiver<Option<CronSchedulerLease>>,
    clock: Arc<dyn CronWorkerClock>,
    runtime: WorkerRuntimeV2,
}

impl OwnerLifecycle {
    pub(super) async fn acquire(
        scheduler: &CronScheduler,
        shutdown: watch::Receiver<bool>,
    ) -> CoreResult<Option<Self>> {
        if stopped(&shutdown) {
            return Ok(None);
        }
        let Some(lease) = scheduler
            .ownership
            .try_acquire_global(
                &scheduler.config.owner_id,
                scheduler.config.owner_lease_seconds,
                scheduler.clock.now(),
            )
            .await
            .map_err(ownership_error)?
        else {
            return Ok(None);
        };
        let (published, authority) = watch::channel(Some(lease.clone()));
        let ownership = scheduler.ownership.clone();
        let clock = scheduler.clock.clone();
        let seconds = scheduler.config.owner_lease_seconds;
        let runtime = WorkerRuntimeV2::spawn("cron-owner-renewal", move |stop| {
            supervise(ownership, clock, lease, seconds, published, shutdown, stop)
        });
        Ok(Some(Self {
            authority,
            clock: scheduler.clock.clone(),
            runtime,
        }))
    }

    pub(super) fn current(&self) -> Option<CronSchedulerLease> {
        if self.authority.has_changed().is_err() {
            return None;
        }
        self.authority
            .borrow()
            .clone()
            .filter(|lease| lease.lease_expires_at > self.clock.now())
    }

    pub(super) async fn lost(&self) {
        let mut authority = self.authority.clone();
        while self.current().is_some() {
            if authority.changed().await.is_err() {
                return;
            }
        }
    }

    pub(super) async fn stop(&self) {
        if let Err(error) = self.runtime.shutdown().await {
            eprintln!("[agistack] cron owner lifecycle failed: {error}");
        }
    }
}

pub(super) fn stopped(shutdown: &watch::Receiver<bool>) -> bool {
    *shutdown.borrow() || shutdown.has_changed().is_err()
}

async fn supervise(
    ownership: Arc<dyn CronSchedulerLeaseStore>,
    clock: Arc<dyn CronWorkerClock>,
    mut lease: CronSchedulerLease,
    seconds: i64,
    published: watch::Sender<Option<CronSchedulerLease>>,
    mut shutdown: watch::Receiver<bool>,
    mut stop: watch::Receiver<bool>,
) {
    // Pure lease arithmetic: leave a third of the TTL after the renewal deadline.
    let heartbeat = Duration::from_secs(seconds.max(1) as u64) / 3;
    loop {
        if stopped(&shutdown) || stopped(&stop) {
            break;
        }
        tokio::select! {
            biased;
            _ = shutdown.changed() => break,
            _ = stop.changed() => break,
            () = tokio::time::sleep(heartbeat) => {}
        }
        let renewed = tokio::select! {
            biased;
            _ = shutdown.changed() => break,
            _ = stop.changed() => break,
            result = tokio::time::timeout(
                heartbeat,
                ownership.renew(&lease, seconds, clock.now()),
            ) => result,
        };
        match renewed {
            Ok(Ok(Some(next))) if same_generation(&lease, &next) => {
                lease = next;
                published.send_replace(Some(lease.clone()));
            }
            Ok(Ok(_)) => break,
            Ok(Err(_)) | Err(_) => {
                eprintln!("[agistack] cron owner renewal failed; stopping control admission");
                break;
            }
        }
    }
    // Clearing the local capability stops new scopes. Exact DB release fences
    // concurrent transactions; it never changes an operation, Agent run or HITL.
    published.send_replace(None);
    if ownership.release(&lease, clock.now()).await.is_err() {
        eprintln!("[agistack] cron owner release failed; storage lease remains fenced by expiry");
    }
}

fn same_generation(before: &CronSchedulerLease, after: &CronSchedulerLease) -> bool {
    before.scope_id == after.scope_id
        && before.owner_id == after.owner_id
        && before.owner_epoch == after.owner_epoch
        && before.lease_token == after.lease_token
        && before.acquired_at == after.acquired_at
}
