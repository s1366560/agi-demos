use std::sync::Arc;

use agistack_adapters_postgres::{CronControlScope, CronSchedulerLease, CronSchedulerOwnerError};
use agistack_core::ports::{CoreError, CoreResult};
use async_trait::async_trait;
use chrono::{DateTime, Utc};
use tokio::sync::watch;
use tokio::time::sleep;

use super::config::{CronSchedulerConfig, CRON_PRODUCTION_READY_ENV};
use crate::cron_readiness_v2::{
    CronReadinessBlockerV2, CronReadinessV2, CronRuntimeDependenciesV2,
};
use crate::cron_scheduler_ownership::CronSchedulerLeaseStore;
use crate::cron_worker::CronWorkerClock;

mod owner_lifecycle;
use owner_lifecycle::{stopped, OwnerLifecycle};

pub(crate) type SharedCronScheduler = Arc<CronScheduler>;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum CronSchedulerGate {
    Open,
    AutostartDisabled,
    ProductionNotReady,
    DependenciesUnavailable,
}

#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub(crate) struct CronScopeControlReport {
    pub(crate) reconcile_admitted: usize,
    pub(crate) operations_claimed: usize,
    pub(crate) scheduled_runs_committed: usize,
}

#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub(crate) struct CronSchedulerRunReport {
    pub(crate) gate: Option<CronSchedulerGate>,
    pub(crate) authority_acquired: bool,
    pub(crate) authority_lost: bool,
    pub(crate) pages: usize,
    pub(crate) scopes: usize,
    pub(crate) reconcile_admitted: usize,
    pub(crate) operations_claimed: usize,
    pub(crate) scheduled_runs_committed: usize,
    pub(crate) runtime_scopes: usize,
}

#[async_trait]
pub(crate) trait CronSchedulerDriver: Send + Sync {
    async fn list_work_scopes(
        &self,
        authority: &CronSchedulerLease,
        after: Option<&CronControlScope>,
        limit: i64,
        observed_at: DateTime<Utc>,
    ) -> CoreResult<Vec<CronControlScope>>;

    async fn drive_control_scope(
        &self,
        authority: &CronSchedulerLease,
        scope: &CronControlScope,
    ) -> CoreResult<CronScopeControlReport>;

    async fn drive_runtime_scope(&self, scope: &CronControlScope) -> CoreResult<()>;
}

pub(crate) struct CronScheduler {
    ownership: Arc<dyn CronSchedulerLeaseStore>,
    driver: Arc<dyn CronSchedulerDriver>,
    clock: Arc<dyn CronWorkerClock>,
    config: CronSchedulerConfig,
    readiness: Arc<CronReadinessV2>,
}

impl CronScheduler {
    #[cfg(test)]
    pub(crate) fn new(
        ownership: Arc<dyn CronSchedulerLeaseStore>,
        driver: Arc<dyn CronSchedulerDriver>,
        clock: Arc<dyn CronWorkerClock>,
        config: CronSchedulerConfig,
    ) -> Self {
        Self::with_dependencies(
            ownership,
            driver,
            clock,
            config,
            CronRuntimeDependenciesV2::ready_for_test(),
        )
    }

    pub(crate) fn with_dependencies(
        ownership: Arc<dyn CronSchedulerLeaseStore>,
        driver: Arc<dyn CronSchedulerDriver>,
        clock: Arc<dyn CronWorkerClock>,
        config: CronSchedulerConfig,
        dependencies: CronRuntimeDependenciesV2,
    ) -> Self {
        let readiness = Arc::new(CronReadinessV2::new(dependencies));
        if !config.autostart {
            readiness.blocked(CronReadinessBlockerV2::AutostartDisabled);
        }
        if !config.production_ready {
            readiness.blocked(CronReadinessBlockerV2::ProductionGateClosed);
        }
        Self {
            ownership,
            driver,
            clock,
            config,
            readiness,
        }
    }

    pub(crate) fn readiness(&self) -> Arc<CronReadinessV2> {
        Arc::clone(&self.readiness)
    }

    pub(crate) fn gate(&self) -> CronSchedulerGate {
        if !self.config.autostart {
            return CronSchedulerGate::AutostartDisabled;
        }
        if !self.config.production_ready {
            return CronSchedulerGate::ProductionNotReady;
        }
        if !self.readiness.snapshot().blockers.is_empty() {
            return CronSchedulerGate::DependenciesUnavailable;
        }
        CronSchedulerGate::Open
    }

    pub(crate) fn spawn_if_enabled(self: Arc<Self>) -> Option<CronSchedulerRuntime> {
        self.readiness.published();
        match self.gate() {
            CronSchedulerGate::AutostartDisabled => return None,
            CronSchedulerGate::ProductionNotReady => {
                eprintln!(
                    "[agistack] cron scheduler: autostart requested but production readiness gate is disabled (set {CRON_PRODUCTION_READY_ENV}=true after cutover); not acquiring ownership"
                );
                return None;
            }
            CronSchedulerGate::Open => {}
            CronSchedulerGate::DependenciesUnavailable => return None,
        }
        if self.readiness.snapshot().phase
            != crate::cron_readiness_v2::CronRuntimePhaseV2::Published
        {
            return None;
        }
        let observer = self.readiness.clone();
        Some(CronSchedulerRuntime::spawn_observed(
            "cron-scheduler",
            move |receiver| self.run_loop(receiver),
            Some(observer),
        ))
    }

    #[cfg(test)]
    pub(crate) async fn run_once(&self) -> CoreResult<CronSchedulerRunReport> {
        let gate = self.gate();
        if gate != CronSchedulerGate::Open {
            return Ok(CronSchedulerRunReport {
                gate: Some(gate),
                ..Default::default()
            });
        }
        let (_stop, shutdown) = watch::channel(false);
        let Some(owner) = OwnerLifecycle::acquire(self, shutdown.clone()).await? else {
            return Ok(CronSchedulerRunReport::default());
        };
        let result = self.run_control_once(&owner, &shutdown).await;
        let (mut report, scopes) = match result {
            Ok(result) => result,
            Err(error) => {
                owner.stop().await;
                return Err(error);
            }
        };
        for scope in &scopes {
            if owner.current().is_none() {
                report.authority_lost = true;
                break;
            }
            if let Err(error) = self.driver.drive_runtime_scope(scope).await {
                owner.stop().await;
                return Err(error);
            }
            report.runtime_scopes += 1;
        }
        owner.stop().await;
        Ok(report)
    }

    async fn run_control_once(
        &self,
        owner: &OwnerLifecycle,
        shutdown: &watch::Receiver<bool>,
    ) -> CoreResult<(CronSchedulerRunReport, Vec<CronControlScope>)> {
        let mut report = CronSchedulerRunReport {
            authority_acquired: true,
            ..Default::default()
        };
        let mut scopes = Vec::new();
        self.drive_control_pages(owner, shutdown, &mut report, &mut scopes)
            .await?;
        Ok((report, scopes))
    }

    async fn drive_control_pages(
        &self,
        owner: &OwnerLifecycle,
        shutdown: &watch::Receiver<bool>,
        report: &mut CronSchedulerRunReport,
        all_scopes: &mut Vec<CronControlScope>,
    ) -> CoreResult<()> {
        let mut after = None;
        for _ in 0..self.config.max_scope_pages {
            if stopped(shutdown) {
                break;
            }
            let Some(authority) = owner.current() else {
                report.authority_lost = true;
                break;
            };
            let page = self
                .driver
                .list_work_scopes(
                    &authority,
                    after.as_ref(),
                    self.config.scope_page_size,
                    self.clock.now(),
                )
                .await?;
            if page.is_empty() {
                break;
            }
            report.pages += 1;
            for scope in &page {
                if stopped(shutdown) {
                    return Ok(());
                }
                let Some(authority) = owner.current() else {
                    report.authority_lost = true;
                    return Ok(());
                };
                let scope_report = self.driver.drive_control_scope(&authority, scope).await?;
                report.scopes += 1;
                report.reconcile_admitted += scope_report.reconcile_admitted;
                report.operations_claimed += scope_report.operations_claimed;
                report.scheduled_runs_committed += scope_report.scheduled_runs_committed;
                all_scopes.push(scope.clone());
            }
            after = page.last().cloned();
            let page_is_full = page.len() == self.config.scope_page_size as usize;
            if !page_is_full {
                break;
            }
        }
        Ok(())
    }

    async fn run_loop(self: Arc<Self>, mut shutdown: watch::Receiver<bool>) {
        // Spawning a handle is not evidence that the poll loop entered. A stop
        // before first poll must never publish running or acquire ownership.
        if *shutdown.borrow() || !self.readiness.confirm_loop_started() {
            return;
        }
        let mut owner: Option<OwnerLifecycle> = None;
        while !stopped(&shutdown) {
            if owner
                .as_ref()
                .is_some_and(|owner| owner.current().is_none())
            {
                if let Some(prior) = owner.take() {
                    prior.stop().await;
                }
            }
            if owner.is_none() {
                match OwnerLifecycle::acquire(&self, shutdown.clone()).await {
                    Ok(acquired) => owner = acquired,
                    Err(error) => eprintln!("[agistack] cron owner acquisition failed: {error:?}"),
                }
            }
            let Some(current) = owner.as_ref() else {
                tokio::select! {
                    _ = shutdown.changed() => {},
                    () = sleep(self.config.poll_interval) => {},
                }
                continue;
            };
            match self.run_control_once(current, &shutdown).await {
                Ok((_, scopes)) => {
                    for scope in &scopes {
                        // A claimed runtime operation must settle before its generation retires.
                        // Stop admission between scopes, never by dropping the active driver future.
                        if stopped(&shutdown) || current.current().is_none() {
                            break;
                        }
                        if let Err(error) = self.driver.drive_runtime_scope(scope).await {
                            eprintln!("[agistack] cron Agent runtime poll failed: {error:?}");
                        }
                    }
                }
                Err(error) => eprintln!("[agistack] cron scheduler control poll failed: {error:?}"),
            }
            tokio::select! {
                _ = shutdown.changed() => {}
                () = current.lost() => {}
                () = sleep(self.config.poll_interval) => {}
            }
        }
        if let Some(owner) = owner {
            owner.stop().await;
        }
    }
}

fn ownership_error(_error: CronSchedulerOwnerError) -> CoreError {
    CoreError::Storage("cron scheduler ownership storage failed".to_string())
}

pub(crate) type CronSchedulerRuntime = crate::worker_lifecycle_v2::WorkerRuntimeV2;

#[cfg(test)]
mod tests;
