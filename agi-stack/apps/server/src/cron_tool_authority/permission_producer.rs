//! Host producer for a single atomic permission suspension; never a dispatcher.
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};

use agistack_adapters_postgres::{
    AutomationPermissionOutcome, AutomationPermissionSuspensionCommand, AutomationRunLease,
    PgAutomationPermissionStore, PgPool,
};
use agistack_core::{
    automation_permission::PermissionSuspensionPort, CoreError, CoreResult, SessionState,
};
use agistack_plugin_host::{permission_binding::observe_permission_binding, HotPlugRegistry};
use async_trait::async_trait;
use chrono::Utc;
use uuid::Uuid;

use super::AutomationRunAuthority;

#[derive(Clone)]
pub(crate) struct PgAutomationPermissionProducerFactory {
    pool: PgPool,
    registry: HotPlugRegistry,
}

impl PgAutomationPermissionProducerFactory {
    pub(crate) fn new(pool: PgPool, registry: HotPlugRegistry) -> Self {
        Self { pool, registry }
    }

    pub(crate) fn for_run(
        &self,
        lease: &AutomationRunLease,
    ) -> Arc<PgAutomationPermissionProducer> {
        Arc::new(PgAutomationPermissionProducer {
            store: PgAutomationPermissionStore::new(self.pool.clone()),
            registry: self.registry.clone(),
            lease: lease.clone(),
            committed: AtomicBool::new(false),
        })
    }
}

pub(crate) struct PgAutomationPermissionProducer {
    store: PgAutomationPermissionStore,
    registry: HotPlugRegistry,
    lease: AutomationRunLease,
    committed: AtomicBool,
}

impl PgAutomationPermissionProducer {
    pub(crate) fn committed(&self) -> bool {
        self.committed.load(Ordering::Acquire)
    }
}

#[async_trait]
impl PermissionSuspensionPort for PgAutomationPermissionProducer {
    async fn suspend(&self, state: &SessionState) -> CoreResult<()> {
        let proposal = state
            .pending_hitl
            .as_ref()
            .and_then(|r| r.permission_invocation.as_ref())
            .ok_or_else(denied)?;
        let authority = AutomationRunAuthority::from_lease(&self.lease)?;
        // Applicability and identity are observed from the same immutable snapshot.
        // No live handle is retained for subsequent dispatch or reconstructed later.
        let snapshot = self.registry.snapshot();
        let tool = snapshot.get(&proposal.tool).ok_or_else(denied)?;
        if !tool.should_run(&authority.applicability_context()?) {
            return Err(denied());
        }
        let binding = observe_permission_binding(
            &snapshot,
            Uuid::new_v4().to_string(),
            &proposal.tool,
            &proposal.input,
        )
        .ok_or_else(denied)?;
        let command = AutomationPermissionSuspensionCommand {
            intent_id: Uuid::new_v4().to_string(),
            binding,
            state: state.clone(),
            expires_at: self.lease.deadline_at,
        };
        let result = self
            .store
            .suspend_with_lease(&self.lease, &command, Utc::now())
            .await
            .map_err(|_| denied())?;
        if result != AutomationPermissionOutcome::Applied {
            return Err(denied());
        }
        self.committed.store(true, Ordering::Release);
        Ok(())
    }
}

fn denied() -> CoreError {
    CoreError::Tool("atomic permission suspension was denied".into())
}
