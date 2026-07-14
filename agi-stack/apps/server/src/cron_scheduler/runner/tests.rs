use std::sync::{Arc, Mutex};
use std::time::Duration;

use agistack_adapters_postgres::{
    CronSchedulerLease, CronSchedulerOwnerError, GLOBAL_CRON_SCHEDULER_SCOPE,
};
use async_trait::async_trait;
use chrono::{DateTime, TimeZone, Utc};

use super::*;

#[derive(Debug)]
struct FixedClock(DateTime<Utc>);

impl CronWorkerClock for FixedClock {
    fn now(&self) -> DateTime<Utc> {
        self.0
    }
}

#[derive(Debug)]
struct FakeOwnership {
    events: Arc<Mutex<Vec<String>>>,
    acquire: Option<CronSchedulerLease>,
    renewed: Option<CronSchedulerLease>,
    released: bool,
}

#[async_trait]
impl CronSchedulerLeaseStore for FakeOwnership {
    async fn try_acquire_global(
        &self,
        owner_id: &str,
        _lease_seconds: i64,
        _now: DateTime<Utc>,
    ) -> Result<Option<CronSchedulerLease>, CronSchedulerOwnerError> {
        self.events
            .lock()
            .expect("events lock")
            .push(format!("acquire:{owner_id}"));
        Ok(self.acquire.clone())
    }

    async fn renew(
        &self,
        lease: &CronSchedulerLease,
        _lease_seconds: i64,
        _now: DateTime<Utc>,
    ) -> Result<Option<CronSchedulerLease>, CronSchedulerOwnerError> {
        self.events
            .lock()
            .expect("events lock")
            .push(format!("renew:{}", lease.owner_epoch));
        Ok(self.renewed.clone())
    }

    async fn release(
        &self,
        lease: &CronSchedulerLease,
        _now: DateTime<Utc>,
    ) -> Result<bool, CronSchedulerOwnerError> {
        self.events
            .lock()
            .expect("events lock")
            .push(format!("release:{}", lease.owner_epoch));
        Ok(self.released)
    }
}

#[derive(Debug)]
struct FakeDriver {
    events: Arc<Mutex<Vec<String>>>,
    pages: Vec<Vec<CronControlScope>>,
}

#[async_trait]
impl CronSchedulerDriver for FakeDriver {
    async fn list_work_scopes(
        &self,
        authority: &CronSchedulerLease,
        after: Option<&CronControlScope>,
        _limit: i64,
        _observed_at: DateTime<Utc>,
    ) -> CoreResult<Vec<CronControlScope>> {
        let page_index = usize::from(after.is_some());
        self.events
            .lock()
            .expect("events lock")
            .push(format!("list:{}:{page_index}", authority.owner_epoch));
        Ok(self.pages.get(page_index).cloned().unwrap_or_default())
    }

    async fn drive_control_scope(
        &self,
        authority: &CronSchedulerLease,
        scope: &CronControlScope,
    ) -> CoreResult<CronScopeControlReport> {
        self.events
            .lock()
            .expect("events lock")
            .push(format!(
                "control:{}:{}",
                authority.owner_epoch, scope.project_id
            ));
        Ok(CronScopeControlReport {
            reconcile_admitted: 1,
            operations_claimed: 2,
            scheduled_runs_committed: 1,
        })
    }

    async fn drive_runtime_scope(&self, scope: &CronControlScope) -> CoreResult<()> {
        self.events
            .lock()
            .expect("events lock")
            .push(format!("runtime:{}", scope.project_id));
        Ok(())
    }
}

fn observed_at() -> DateTime<Utc> {
    Utc.with_ymd_and_hms(2026, 7, 14, 10, 0, 0)
        .single()
        .expect("valid observed time")
}

fn lease(epoch: i64) -> CronSchedulerLease {
    let acquired_at = observed_at();
    CronSchedulerLease {
        scope_id: GLOBAL_CRON_SCHEDULER_SCOPE.to_string(),
        owner_id: "owner-a".to_string(),
        owner_epoch: epoch,
        lease_token: format!("token-{epoch}"),
        lease_expires_at: acquired_at + chrono::Duration::minutes(epoch),
        acquired_at,
    }
}

fn scope(project_id: &str) -> CronControlScope {
    CronControlScope {
        tenant_id: "tenant-a".to_string(),
        project_id: project_id.to_string(),
    }
}

fn enabled_config() -> CronSchedulerConfig {
    CronSchedulerConfig {
        owner_id: "owner-a".to_string(),
        owner_lease_seconds: 60,
        scope_page_size: 2,
        max_scope_pages: 2,
        reconcile_batch_size: 2,
        fire_batch_size: 2,
        operation_batch_size: 2,
        operation_lease_seconds: 60,
        runtime_batch_size: 1,
        runtime_lease_seconds: 60,
        runtime_heartbeat: Duration::from_secs(15),
        poll_interval: Duration::from_millis(1),
        autostart: true,
        production_ready: true,
    }
}

#[tokio::test]
async fn closed_gate_never_acquires_scheduler_ownership() {
    let events = Arc::new(Mutex::new(Vec::new()));
    let scheduler = CronScheduler::new(
        Arc::new(FakeOwnership {
            events: Arc::clone(&events),
            acquire: Some(lease(1)),
            renewed: None,
            released: true,
        }),
        Arc::new(FakeDriver {
            events: Arc::clone(&events),
            pages: Vec::new(),
        }),
        Arc::new(FixedClock(observed_at())),
        CronSchedulerConfig::default(),
    );

    let report = scheduler.run_once().await.expect("closed scheduler report");

    assert_eq!(report.gate, Some(CronSchedulerGate::AutostartDisabled));
    assert!(events.lock().expect("events lock").is_empty());
}

#[tokio::test]
async fn full_page_renews_exact_lease_and_release_precedes_agent_runtime() {
    let events = Arc::new(Mutex::new(Vec::new()));
    let scheduler = CronScheduler::new(
        Arc::new(FakeOwnership {
            events: Arc::clone(&events),
            acquire: Some(lease(1)),
            renewed: Some(lease(2)),
            released: true,
        }),
        Arc::new(FakeDriver {
            events: Arc::clone(&events),
            pages: vec![vec![scope("a"), scope("b")], vec![scope("c")]],
        }),
        Arc::new(FixedClock(observed_at())),
        enabled_config(),
    );

    let report = scheduler.run_once().await.expect("scheduler run");
    let events = events.lock().expect("events lock").clone();

    assert_eq!(report.pages, 2);
    assert_eq!(report.scopes, 3);
    assert_eq!(report.reconcile_admitted, 3);
    assert_eq!(report.operations_claimed, 6);
    assert_eq!(report.scheduled_runs_committed, 3);
    assert_eq!(report.runtime_scopes, 3);
    assert!(events.contains(&"renew:1".to_string()));
    assert!(events.contains(&"list:2:1".to_string()));
    let release = events
        .iter()
        .position(|event| event == "release:2")
        .expect("renewed lease released");
    let first_runtime = events
        .iter()
        .position(|event| event.starts_with("runtime:"))
        .expect("runtime driven");
    assert!(release < first_runtime);
}

#[tokio::test]
async fn lost_renewal_stops_paging_and_reports_authority_loss() {
    let events = Arc::new(Mutex::new(Vec::new()));
    let scheduler = CronScheduler::new(
        Arc::new(FakeOwnership {
            events: Arc::clone(&events),
            acquire: Some(lease(1)),
            renewed: None,
            released: false,
        }),
        Arc::new(FakeDriver {
            events: Arc::clone(&events),
            pages: vec![vec![scope("a"), scope("b")], vec![scope("c")]],
        }),
        Arc::new(FixedClock(observed_at())),
        enabled_config(),
    );

    let report = scheduler.run_once().await.expect("scheduler run");
    let events = events.lock().expect("events lock").clone();

    assert!(report.authority_lost);
    assert_eq!(report.pages, 1);
    assert_eq!(report.scopes, 2);
    assert!(!events.iter().any(|event| event == "list:2:1"));
    assert!(events.iter().any(|event| event == "release:1"));
}

