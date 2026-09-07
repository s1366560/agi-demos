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
        let (mut report, scopes) = self.run_control_once().await?;
        for scope in &scopes {
            self.driver.drive_runtime_scope(scope).await?;
            report.runtime_scopes += 1;
        }
        Ok(report)
    }

    async fn run_control_once(
        &self,
    ) -> CoreResult<(CronSchedulerRunReport, Vec<CronControlScope>)> {
        let now = self.clock.now();
        let Some(mut authority) = self
            .ownership
            .try_acquire_global(&self.config.owner_id, self.config.owner_lease_seconds, now)
            .await
            .map_err(ownership_error)?
        else {
            return Ok((CronSchedulerRunReport::default(), Vec::new()));
        };

        let mut report = CronSchedulerRunReport {
            authority_acquired: true,
            ..Default::default()
        };
        let mut scopes = Vec::new();
        let control_result = self
            .drive_control_pages(&mut authority, &mut report, &mut scopes)
            .await;
        let released = self
            .ownership
            .release(&authority, self.clock.now())
            .await
            .map_err(ownership_error);
        if let Err(error) = control_result {
            let _ = released;
            return Err(error);
        }
        if !released? {
            report.authority_lost = true;
        }
        Ok((report, scopes))
    }

    async fn drive_control_pages(
        &self,
        authority: &mut CronSchedulerLease,
        report: &mut CronSchedulerRunReport,
        all_scopes: &mut Vec<CronControlScope>,
    ) -> CoreResult<()> {
        let mut after = None;
        for page_index in 0..self.config.max_scope_pages {
            let page = self
                .driver
                .list_work_scopes(
                    authority,
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
                let scope_report = self.driver.drive_control_scope(authority, scope).await?;
                report.scopes += 1;
                report.reconcile_admitted += scope_report.reconcile_admitted;
                report.operations_claimed += scope_report.operations_claimed;
                report.scheduled_runs_committed += scope_report.scheduled_runs_committed;
            }
            after = page.last().cloned();
            all_scopes.extend(page.iter().cloned());
            let page_is_full = page.len() == self.config.scope_page_size as usize;
            if !page_is_full || page_index + 1 >= self.config.max_scope_pages {
                break;
            }
            let renewed = self
                .ownership
                .renew(authority, self.config.owner_lease_seconds, self.clock.now())
                .await
                .map_err(ownership_error)?;
            let Some(renewed) = renewed else {
                report.authority_lost = true;
                break;
            };
            *authority = renewed;
        }
        Ok(())
    }

    async fn run_loop(self: Arc<Self>, mut shutdown: watch::Receiver<bool>) {
        // Spawning a handle is not evidence that the poll loop entered. A stop
        // before first poll must never publish running or acquire ownership.
        if *shutdown.borrow() || !self.readiness.confirm_loop_started() {
            return;
        }
        loop {
            if *shutdown.borrow() {
                return;
            }
            match self.run_control_once().await {
                Ok((_, scopes)) => {
                    for scope in &scopes {
                        // A claimed runtime operation must settle before its generation retires.
                        // Stop admission between scopes, never by dropping the active driver future.
                        if *shutdown.borrow() || shutdown.has_changed().is_err() {
                            return;
                        }
                        if let Err(error) = self.driver.drive_runtime_scope(scope).await {
                            eprintln!("[agistack] cron Agent runtime poll failed: {error:?}");
                        }
                    }
                }
                Err(error) => eprintln!("[agistack] cron scheduler control poll failed: {error:?}"),
            }
            tokio::select! {
                changed = shutdown.changed() => {
                    if changed.is_err() || *shutdown.borrow() {
                        return;
                    }
                }
                () = sleep(self.config.poll_interval) => {}
            }
        }
    }
}

fn ownership_error(_error: CronSchedulerOwnerError) -> CoreError {
    CoreError::Storage("cron scheduler ownership storage failed".to_string())
}

pub(crate) type CronSchedulerRuntime = crate::worker_lifecycle_v2::WorkerRuntimeV2;

#[cfg(test)]
mod tests;
