use std::sync::Arc;

use agistack_adapters_postgres::{
    AutomationRunLease, NewHitlRequestRecord, PgAutomationRunPersistence, PgPool,
};
use agistack_core::ports::{CheckpointStore, CoreResult};
use async_trait::async_trait;

use super::AutomationHitlStore;

pub(crate) struct AutomationRunPersistence {
    pub(crate) checkpoints: Arc<dyn CheckpointStore>,
    pub(crate) hitl: Arc<dyn AutomationHitlStore>,
}

pub(crate) trait AutomationRunPersistenceFactory: Send + Sync {
    fn for_run(&self, lease: &AutomationRunLease) -> CoreResult<AutomationRunPersistence>;
}

pub(crate) struct PgAutomationRunPersistenceFactory {
    pool: PgPool,
}

impl PgAutomationRunPersistenceFactory {
    pub(crate) fn new(pool: PgPool) -> Self {
        Self { pool }
    }
}

impl AutomationRunPersistenceFactory for PgAutomationRunPersistenceFactory {
    fn for_run(&self, lease: &AutomationRunLease) -> CoreResult<AutomationRunPersistence> {
        let persistence = Arc::new(PgAutomationRunPersistence::new(
            self.pool.clone(),
            lease.clone(),
        ));
        Ok(AutomationRunPersistence {
            checkpoints: persistence.clone(),
            hitl: persistence,
        })
    }
}

#[async_trait]
impl AutomationHitlStore for PgAutomationRunPersistence {
    async fn insert_pending(&self, request: &NewHitlRequestRecord) -> CoreResult<bool> {
        PgAutomationRunPersistence::insert_pending(self, request).await
    }
}
