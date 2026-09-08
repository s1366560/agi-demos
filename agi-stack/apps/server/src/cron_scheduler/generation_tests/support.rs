use std::{
    collections::BTreeMap,
    sync::{Arc, Mutex, Weak},
    time::Duration,
};

use agistack_adapters_postgres::{CronControlScope, CronSchedulerLease, CronSchedulerOwnerError};
use agistack_core::ports::CoreResult;
use agistack_plugin_host::protocol_v2::ProfileSnapshotV2;
use agistack_plugin_host::{
    parse_profile_snapshot_v2, rust_server_host_definition_v2,
    rust_server_http_routes_definition_v2, ContextV2, DataPlaneTargetV2, LoaderV2,
    PluginDefinitionV2, PluginModuleRuntimeV2, RuntimeGenerationV2, RuntimeV2Error, ScopeKindV2,
    ScopeV2,
};
use async_trait::async_trait;
use chrono::{DateTime, Utc};
use serde_json::Value;
use tokio::sync::{Notify, Semaphore};

use crate::background_worker_control_v2::{BackgroundWorkerControllerV2, WorkerFactoryV2};
use crate::background_workers_v2::{
    definitions_with_cron_resources_v2, CronWorkerResourceFactoryV2, CronWorkerResourceV2,
    WORKER_SERVICES_V2,
};
use crate::cron_scheduler::{
    config::CronSchedulerConfig,
    runner::{CronScheduler, CronSchedulerDriver, CronScopeControlReport},
};
use crate::cron_scheduler_ownership::CronSchedulerLeaseStore;
use crate::cron_worker::UtcCronWorkerClock;

pub(super) const LIMIT: Duration = Duration::from_secs(2);

#[derive(Default)]
struct LeaseState {
    current: Option<CronSchedulerLease>,
    acquires: usize,
    releases: usize,
}

#[derive(Default)]
pub(super) struct Ownership(Mutex<LeaseState>);

impl Ownership {
    pub(super) fn acquires(&self) -> usize {
        self.0.lock().unwrap().acquires
    }
    pub(super) fn releases(&self) -> usize {
        self.0.lock().unwrap().releases
    }
}

#[async_trait]
impl CronSchedulerLeaseStore for Ownership {
    async fn try_acquire_global(
        &self,
        owner_id: &str,
        lease_seconds: i64,
        now: DateTime<Utc>,
    ) -> Result<Option<CronSchedulerLease>, CronSchedulerOwnerError> {
        let mut state = self.0.lock().unwrap();
        if state
            .current
            .as_ref()
            .is_some_and(|lease| lease.lease_expires_at > now)
        {
            return Ok(None);
        }
        state.acquires += 1;
        let lease = CronSchedulerLease {
            scope_id: "global".into(),
            owner_id: owner_id.into(),
            owner_epoch: state.acquires as i64,
            lease_token: format!("lease-{}", state.acquires),
            acquired_at: now,
            lease_expires_at: now + chrono::Duration::seconds(lease_seconds),
        };
        state.current = Some(lease.clone());
        Ok(Some(lease))
    }
    async fn renew(
        &self,
        lease: &CronSchedulerLease,
        _seconds: i64,
        _now: DateTime<Utc>,
    ) -> Result<Option<CronSchedulerLease>, CronSchedulerOwnerError> {
        Ok(self
            .0
            .lock()
            .unwrap()
            .current
            .as_ref()
            .filter(|current| *current == lease)
            .cloned())
    }
    async fn release(
        &self,
        lease: &CronSchedulerLease,
        _now: DateTime<Utc>,
    ) -> Result<bool, CronSchedulerOwnerError> {
        let mut state = self.0.lock().unwrap();
        if state.current.as_ref() != Some(lease) {
            return Ok(false);
        }
        state.current = None;
        state.releases += 1;
        Ok(true)
    }
}

pub(super) struct Driver {
    entered: Notify,
    pub(super) finish: Semaphore,
    counts: Mutex<(usize, usize)>,
}
impl Driver {
    fn new() -> Arc<Self> {
        Arc::new(Self {
            entered: Notify::new(),
            finish: Semaphore::new(0),
            counts: Mutex::new((0, 0)),
        })
    }
    pub(super) fn starts(&self) -> usize {
        self.counts.lock().unwrap().0
    }
    pub(super) fn settled(&self) -> usize {
        self.counts.lock().unwrap().1
    }
}
#[async_trait]
impl CronSchedulerDriver for Driver {
    async fn list_work_scopes(
        &self,
        _authority: &CronSchedulerLease,
        _after: Option<&CronControlScope>,
        _limit: i64,
        _observed_at: DateTime<Utc>,
    ) -> CoreResult<Vec<CronControlScope>> {
        Ok(["first", "second"]
            .into_iter()
            .map(|project_id| CronControlScope {
                tenant_id: "tenant".into(),
                project_id: project_id.into(),
            })
            .collect())
    }
    async fn drive_control_scope(
        &self,
        _authority: &CronSchedulerLease,
        _scope: &CronControlScope,
    ) -> CoreResult<CronScopeControlReport> {
        Ok(CronScopeControlReport::default())
    }
    async fn drive_runtime_scope(&self, _scope: &CronControlScope) -> CoreResult<()> {
        self.counts.lock().unwrap().0 += 1;
        self.entered.notify_one();
        self.finish.acquire().await.unwrap().forget();
        self.counts.lock().unwrap().1 += 1;
        Ok(())
    }
}

#[derive(Default)]
pub(super) struct Probe {
    resources: Mutex<Vec<(Weak<CronScheduler>, Arc<Driver>)>>,
    pub(super) ownership: Arc<Ownership>,
}
impl Probe {
    pub(super) fn new() -> Arc<Self> {
        Arc::new(Self::default())
    }
    pub(super) fn built(&self) -> usize {
        self.resources.lock().unwrap().len()
    }
    pub(super) fn alive(&self, index: usize) -> bool {
        self.resources.lock().unwrap()[index].0.upgrade().is_some()
    }
    pub(super) fn scheduler(&self, index: usize) -> Arc<CronScheduler> {
        self.resources.lock().unwrap()[index].0.upgrade().unwrap()
    }
    pub(super) fn driver(&self, index: usize) -> Arc<Driver> {
        self.resources.lock().unwrap()[index].1.clone()
    }
    pub(super) async fn wait_entered(&self, index: usize) {
        tokio::time::timeout(LIMIT, self.driver(index).entered.notified())
            .await
            .unwrap();
    }
    pub(super) fn factory(self: &Arc<Self>) -> CronWorkerResourceFactoryV2 {
        self.factory_with_ownership(self.ownership.clone())
    }
    pub(super) fn factory_with_ownership(
        self: &Arc<Self>,
        ownership: Arc<dyn CronSchedulerLeaseStore>,
    ) -> CronWorkerResourceFactoryV2 {
        let probe = self.clone();
        Arc::new(move || {
            let driver = Driver::new();
            let scheduler = Arc::new(CronScheduler::new(
                ownership.clone(),
                driver.clone(),
                Arc::new(UtcCronWorkerClock),
                CronSchedulerConfig {
                    owner_id: format!("generation-{}", probe.built()),
                    autostart: true,
                    production_ready: true,
                    max_scope_pages: 1,
                    poll_interval: Duration::from_millis(10),
                    ..CronSchedulerConfig::default()
                },
            ));
            probe
                .resources
                .lock()
                .unwrap()
                .push((Arc::downgrade(&scheduler), driver));
            CronWorkerResourceV2 {
                readiness: scheduler.readiness(),
                factory: Arc::new(move || scheduler.clone().spawn_if_enabled()),
            }
        })
    }
}

pub(super) fn profile(generation: u64) -> ProfileSnapshotV2 {
    let mut result = parse_profile_snapshot_v2(include_str!(
        "../../../../../../shared/profiles/memstack-default-bootstrap.v2.json"
    ))
    .unwrap();
    result.generation = generation;
    result.digest = format!("cron-lifecycle-{generation}");
    result
}

struct FailAfterApply(Arc<dyn PluginModuleRuntimeV2>);
#[async_trait]
impl PluginModuleRuntimeV2 for FailAfterApply {
    async fn apply(
        &self,
        context: &mut ContextV2,
        config: &BTreeMap<String, Value>,
    ) -> Result<(), RuntimeV2Error> {
        self.0.apply(context, config).await?;
        Err(RuntimeV2Error::Module(
            "failure after Cron resources staged".into(),
        ))
    }
}

pub(super) fn loader(factory: CronWorkerResourceFactoryV2, fail_after_cron: bool) -> LoaderV2 {
    let no_worker: WorkerFactoryV2 = Arc::new(|| None);
    let mut workers = definitions_with_cron_resources_v2(no_worker.clone(), no_worker, factory);
    if fail_after_cron {
        workers[2].module = Arc::new(FailAfterApply(workers[2].module.clone()));
    }
    let definitions: Vec<PluginDefinitionV2> = [
        rust_server_host_definition_v2(),
        rust_server_http_routes_definition_v2(),
    ]
    .into_iter()
    .chain(workers)
    .collect();
    LoaderV2::for_target(DataPlaneTargetV2::RustServer, definitions)
}
pub(super) fn resolve_controller(
    generation: &RuntimeGenerationV2,
) -> Result<Arc<BackgroundWorkerControllerV2>, RuntimeV2Error> {
    generation
        .resolve::<Arc<BackgroundWorkerControllerV2>>(
            WORKER_SERVICES_V2[2],
            &ScopeV2 {
                kind: ScopeKindV2::Root,
                tenant_id: None,
                project_id: None,
                session_id: None,
            },
            None,
        )
        .map(|controller| controller.as_ref().clone())
}
pub(super) fn controllers(
    generation: &RuntimeGenerationV2,
) -> Vec<Arc<BackgroundWorkerControllerV2>> {
    vec![resolve_controller(generation).unwrap()]
}
