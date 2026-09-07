use std::sync::Arc;

use agistack_adapters_mem::{InMemoryCheckpointStore, StubLlm, SystemClock};
use agistack_core::agent::SessionState;
use agistack_core::ports::{CheckpointStore, CoreError, CoreResult};
use agistack_plugin_host::HotPlugRegistry;
use async_trait::async_trait;

use super::persistence::{AutomationRunPersistence, AutomationRunPersistenceFactory};
use super::{AutomationRunExecutor, ReActAutomationRunExecutor};
use crate::cron_tool_authority::RegistryAutomationToolHostFactory;

struct UnusableBaseStore;

#[async_trait]
impl CheckpointStore for UnusableBaseStore {
    async fn save(&self, _state: &SessionState) -> CoreResult<()> {
        Err(CoreError::Checkpoint("base store reached".into()))
    }
    async fn load(&self, _session_id: &str) -> CoreResult<Option<SessionState>> {
        Err(CoreError::Checkpoint("base store reached".into()))
    }
    async fn delete(&self, _session_id: &str) -> CoreResult<()> {
        Err(CoreError::Checkpoint("base store reached".into()))
    }
}

struct TestPersistenceFactory {
    checkpoints: Arc<InMemoryCheckpointStore>,
}

#[derive(Default)]
struct FakeHitlStore;

#[async_trait]
impl super::AutomationHitlStore for FakeHitlStore {
    async fn insert_pending(
        &self,
        _request: &agistack_adapters_postgres::NewHitlRequestRecord,
    ) -> CoreResult<bool> {
        Err(CoreError::Storage("unexpected HITL request".into()))
    }
}

fn lease() -> agistack_adapters_postgres::AutomationRunLease {
    use agistack_adapters_postgres::{
        AutomationPayload, AutomationRunContext, AutomationRunLease, AutomationRunStatus,
    };
    let now = chrono::Utc::now();
    AutomationRunLease {
        context: AutomationRunContext {
            tenant_id: "tenant".into(),
            project_id: "project".into(),
            job_id: "job".into(),
            run_id: "run".into(),
            runtime_execution_id: "run".into(),
            conversation_id: "conversation".into(),
            actor_user_id: "actor".into(),
            actor_api_key_id: None,
            payload: AutomationPayload::AgentTurn {
                message: "finish".into(),
            },
            timeout_seconds: 30,
            status: AutomationRunStatus::Running,
        },
        runtime_revision: 1,
        lease_owner: "worker".into(),
        lease_token: "token".into(),
        lease_expires_at: now + chrono::Duration::seconds(30),
        deadline_at: now + chrono::Duration::seconds(30),
    }
}

impl AutomationRunPersistenceFactory for TestPersistenceFactory {
    fn for_run(
        &self,
        _lease: &agistack_adapters_postgres::AutomationRunLease,
    ) -> CoreResult<AutomationRunPersistence> {
        Ok(AutomationRunPersistence {
            checkpoints: self.checkpoints.clone(),
            hitl: Arc::new(FakeHitlStore),
        })
    }
}

fn executor() -> ReActAutomationRunExecutor {
    ReActAutomationRunExecutor::new(Arc::new(agistack_core::ReActEngine::new(
        Arc::new(StubLlm),
        Arc::new(HotPlugRegistry::new()),
        Arc::new(UnusableBaseStore),
        Arc::new(SystemClock),
    )))
    .with_tool_host_factory(Arc::new(RegistryAutomationToolHostFactory::new(
        HotPlugRegistry::new(),
    )))
}

#[tokio::test]
async fn executor_cannot_fall_back_to_the_shared_engine_checkpoint_store() {
    let error = executor().execute(&lease()).await.unwrap_err();
    assert!(error
        .to_string()
        .contains("run persistence authority is not configured"));
}

#[tokio::test]
async fn executor_load_and_save_use_the_run_bound_factory_store() {
    let checkpoints = Arc::new(InMemoryCheckpointStore::new());
    let lease = lease();
    let result = executor()
        .with_run_persistence_factory(Arc::new(TestPersistenceFactory {
            checkpoints: checkpoints.clone(),
        }))
        .execute(&lease)
        .await
        .unwrap();
    assert_eq!(
        result.boundary,
        super::AutomationExecutionBoundary::Finished
    );
    let saved = checkpoints
        .load(&lease.context.run_id)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        saved.project_id.as_deref(),
        Some(lease.context.project_id.as_str())
    );
    assert!(saved.answer.is_some());
}
