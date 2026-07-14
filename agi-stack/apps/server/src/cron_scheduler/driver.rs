use std::sync::Arc;

use agistack_adapters_postgres::{
    AutomationRuntimeScope, CronControlScope, CronSchedulerLease,
    PgCronAutomationRuntimeRepository, PgCronControlRepository, PgCronOperationRepository,
    PgCronScheduleFireRepository, PgCronScheduleRepository, PgCronSchedulerOwnerRepository,
    PgHitlRequestRepository, PgPool,
};
use agistack_core::ports::{CoreError, CoreResult};
use agistack_core::ReActEngine;
use agistack_plugin_host::HotPlugRegistry;
use async_trait::async_trait;
use chrono::{DateTime, Utc};

use super::config::CronSchedulerConfig;
use super::runner::{
    CronScheduler, CronSchedulerDriver, CronScopeControlReport, SharedCronScheduler,
};
use crate::cron_automation_runtime::{
    CronAutomationRuntimeWorker, ExecuteRunDispatchHandler, ReActAutomationRunExecutor,
    UuidConversationIdFactory,
};
use crate::cron_schedule_fire::CronScheduleFireCoordinator;
use crate::cron_schedule_reconcile::ReconcileScheduleHandler;
use crate::cron_scheduler_ownership::{CronSchedulerLeaseStore, CronSchedulerOwnershipStore};
use crate::cron_tool_authority::RegistryAutomationToolHostFactory;
use crate::cron_worker::{
    CronOperationHandler, CronOperationStore, CronOperationWorker, CronWorkerClock,
    CronWorkerScope, UtcCronWorkerClock,
};

pub(crate) fn build_pg_cron_scheduler(
    pool: PgPool,
    engine: Arc<ReActEngine>,
    registry: HotPlugRegistry,
) -> SharedCronScheduler {
    let config = CronSchedulerConfig::from_env();
    let ownership = Arc::new(PgCronSchedulerOwnerRepository::new(pool.clone()));
    let lease_store: Arc<dyn CronSchedulerLeaseStore> = ownership.clone();
    let ownership_store: Arc<dyn CronSchedulerOwnershipStore> = ownership;
    let clock: Arc<dyn CronWorkerClock> = Arc::new(UtcCronWorkerClock);

    let runtime_repository = Arc::new(PgCronAutomationRuntimeRepository::new(pool.clone()));
    let executor = Arc::new(
        ReActAutomationRunExecutor::new(engine)
            .with_hitl_store(Arc::new(PgHitlRequestRepository::new(pool.clone())))
            .with_tool_host_factory(Arc::new(RegistryAutomationToolHostFactory::new(registry))),
    );
    let runtime = Arc::new(CronAutomationRuntimeWorker::new(
        runtime_repository.clone(),
        executor,
        config.runtime_worker_config(),
    ));
    let fire = Arc::new(CronScheduleFireCoordinator::new(
        Arc::new(PgCronScheduleFireRepository::new(pool.clone())),
        Arc::clone(&ownership_store),
        Arc::clone(&clock),
    ));
    let driver = Arc::new(PgCronSchedulerDriver {
        control: PgCronControlRepository::new(pool.clone()),
        operation_store: Arc::new(PgCronOperationRepository::new(pool.clone())),
        schedule_store: Arc::new(PgCronScheduleRepository::new(pool)),
        dispatch_store: runtime_repository,
        ownership: ownership_store,
        clock: Arc::clone(&clock),
        fire,
        runtime,
        config: config.clone(),
    });
    Arc::new(CronScheduler::new(lease_store, driver, clock, config))
}

struct PgCronSchedulerDriver {
    control: PgCronControlRepository,
    operation_store: Arc<dyn CronOperationStore>,
    schedule_store: Arc<PgCronScheduleRepository>,
    dispatch_store: Arc<PgCronAutomationRuntimeRepository>,
    ownership: Arc<dyn CronSchedulerOwnershipStore>,
    clock: Arc<dyn CronWorkerClock>,
    fire: Arc<CronScheduleFireCoordinator>,
    runtime: Arc<CronAutomationRuntimeWorker>,
    config: CronSchedulerConfig,
}

impl PgCronSchedulerDriver {
    fn operation_worker(&self, scope: &CronControlScope) -> CronOperationWorker {
        let handlers: Vec<Arc<dyn CronOperationHandler>> = vec![
            Arc::new(ReconcileScheduleHandler::new(
                self.schedule_store.clone(),
                Arc::clone(&self.clock),
            )),
            Arc::new(ExecuteRunDispatchHandler::new(
                self.dispatch_store.clone(),
                Arc::clone(&self.clock),
                Arc::new(UuidConversationIdFactory),
            )),
        ];
        CronOperationWorker::new(
            Arc::clone(&self.operation_store),
            Arc::clone(&self.ownership),
            Arc::clone(&self.clock),
            CronWorkerScope {
                tenant_id: scope.tenant_id.clone(),
                project_id: scope.project_id.clone(),
            },
            self.config.operation_worker_config(),
            handlers,
        )
    }
}

#[async_trait]
impl CronSchedulerDriver for PgCronSchedulerDriver {
    async fn list_work_scopes(
        &self,
        authority: &CronSchedulerLease,
        after: Option<&CronControlScope>,
        limit: i64,
        observed_at: DateTime<Utc>,
    ) -> CoreResult<Vec<CronControlScope>> {
        self.control
            .list_work_scopes(authority, after, limit, observed_at)
            .await
            .map_err(CoreError::from)
    }

    async fn drive_control_scope(
        &self,
        authority: &CronSchedulerLease,
        scope: &CronControlScope,
    ) -> CoreResult<CronScopeControlReport> {
        let admitted = self
            .control
            .admit_reconcile_operations(
                authority,
                scope,
                self.config.reconcile_batch_size,
                self.clock.now(),
            )
            .await
            .map_err(CoreError::from)?
            .len();
        let worker = self.operation_worker(scope);
        let before_fire = worker.drain_once(authority).await?;
        let fire = self
            .fire
            .fire_due(
                authority,
                &scope.tenant_id,
                &scope.project_id,
                self.config.fire_batch_size,
            )
            .await?;
        let after_fire = worker.drain_once(authority).await?;
        Ok(CronScopeControlReport {
            reconcile_admitted: admitted,
            operations_claimed: before_fire.claimed + after_fire.claimed,
            scheduled_runs_committed: fire.committed,
        })
    }

    async fn drive_runtime_scope(&self, scope: &CronControlScope) -> CoreResult<()> {
        self.runtime
            .drain_once(
                &AutomationRuntimeScope {
                    tenant_id: scope.tenant_id.clone(),
                    project_id: scope.project_id.clone(),
                },
                self.clock.now(),
            )
            .await
            .map(|_| ())
            .map_err(|_| CoreError::Storage("cron automation runtime storage failed".to_string()))
    }
}
