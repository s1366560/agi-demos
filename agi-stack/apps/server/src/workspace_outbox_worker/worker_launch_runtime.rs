use super::*;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum WorkerLaunchAdmissionAction {
    Admit,
    SkipAlreadyRunning,
    SkipCooldownActive,
}

impl WorkerLaunchAdmissionAction {
    pub(crate) fn as_str(self) -> &'static str {
        match self {
            Self::Admit => "admit",
            Self::SkipAlreadyRunning => "skip_already_running",
            Self::SkipCooldownActive => "skip_cooldown_active",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct WorkerLaunchAdmissionSnapshot {
    pub(crate) conversation_id: String,
    pub(crate) reuse_existing: bool,
    pub(crate) stream_poll: bool,
    pub(crate) cooldown_claimed: Option<bool>,
    pub(crate) action: WorkerLaunchAdmissionAction,
}

#[async_trait]
pub(crate) trait WorkerLaunchRuntimeStateStore: Send + Sync {
    async fn claim_launch_cooldown(
        &self,
        conversation_id: &str,
        ttl_seconds: u64,
    ) -> CoreResult<bool>;

    async fn refresh_launch_cooldown(
        &self,
        conversation_id: &str,
        ttl_seconds: u64,
    ) -> CoreResult<bool>;

    async fn agent_finished_message_id(&self, conversation_id: &str) -> CoreResult<Option<String>>;

    async fn agent_running_exists(&self, conversation_id: &str) -> CoreResult<bool>;

    async fn refresh_agent_running_marker(
        &self,
        conversation_id: &str,
        ttl_seconds: u64,
    ) -> CoreResult<bool>;

    async fn clear_reused_session_markers(&self, conversation_id: &str) -> CoreResult<()>;
}

#[derive(Debug, Default)]
pub(super) struct NoopWorkerLaunchRuntimeStateStore;

#[async_trait]
impl WorkerLaunchRuntimeStateStore for NoopWorkerLaunchRuntimeStateStore {
    async fn claim_launch_cooldown(
        &self,
        _conversation_id: &str,
        _ttl_seconds: u64,
    ) -> CoreResult<bool> {
        Ok(true)
    }

    async fn refresh_launch_cooldown(
        &self,
        _conversation_id: &str,
        _ttl_seconds: u64,
    ) -> CoreResult<bool> {
        Ok(false)
    }

    async fn agent_finished_message_id(
        &self,
        _conversation_id: &str,
    ) -> CoreResult<Option<String>> {
        Ok(None)
    }

    async fn agent_running_exists(&self, _conversation_id: &str) -> CoreResult<bool> {
        Ok(false)
    }

    async fn refresh_agent_running_marker(
        &self,
        _conversation_id: &str,
        _ttl_seconds: u64,
    ) -> CoreResult<bool> {
        Ok(false)
    }

    async fn clear_reused_session_markers(&self, _conversation_id: &str) -> CoreResult<()> {
        Ok(())
    }
}

#[async_trait]
impl WorkerLaunchRuntimeStateStore for agistack_adapters_redis::RedisWorkerLaunchStateStore {
    async fn claim_launch_cooldown(
        &self,
        conversation_id: &str,
        ttl_seconds: u64,
    ) -> CoreResult<bool> {
        self.claim_worker_launch_cooldown(conversation_id, ttl_seconds)
            .await
    }

    async fn refresh_launch_cooldown(
        &self,
        conversation_id: &str,
        ttl_seconds: u64,
    ) -> CoreResult<bool> {
        self.refresh_worker_launch_cooldown(conversation_id, ttl_seconds)
            .await
    }

    async fn agent_finished_message_id(&self, conversation_id: &str) -> CoreResult<Option<String>> {
        self.agent_finished_message_id(conversation_id).await
    }

    async fn agent_running_exists(&self, conversation_id: &str) -> CoreResult<bool> {
        self.agent_running_exists(conversation_id).await
    }

    async fn refresh_agent_running_marker(
        &self,
        conversation_id: &str,
        ttl_seconds: u64,
    ) -> CoreResult<bool> {
        self.refresh_existing_agent_running_marker(conversation_id, ttl_seconds)
            .await
    }

    async fn clear_reused_session_markers(&self, conversation_id: &str) -> CoreResult<()> {
        self.clear_reused_worker_session_markers(conversation_id)
            .await
    }
}

#[async_trait]
pub(crate) trait WorkerLaunchEventStream: Send + Sync {
    async fn read_after(
        &self,
        conversation_id: &str,
        after_id: &str,
        limit: usize,
    ) -> CoreResult<Vec<StreamEntry>>;
}

#[derive(Debug, Default)]
pub(super) struct NoopWorkerLaunchEventStream;

#[async_trait]
impl WorkerLaunchEventStream for NoopWorkerLaunchEventStream {
    async fn read_after(
        &self,
        _conversation_id: &str,
        _after_id: &str,
        _limit: usize,
    ) -> CoreResult<Vec<StreamEntry>> {
        Ok(Vec::new())
    }
}

struct EventStreamWorkerLaunchEventSource {
    events: Arc<dyn EventStream>,
}

#[async_trait]
impl WorkerLaunchEventStream for EventStreamWorkerLaunchEventSource {
    async fn read_after(
        &self,
        conversation_id: &str,
        after_id: &str,
        limit: usize,
    ) -> CoreResult<Vec<StreamEntry>> {
        self.events
            .read_after(&worker_stream_topic(conversation_id), after_id, limit)
            .await
    }
}

fn worker_stream_topic(conversation_id: &str) -> String {
    format!("agent:events:{conversation_id}")
}

pub(crate) fn worker_launch_event_stream_source(
    events: Arc<dyn EventStream>,
) -> Arc<dyn WorkerLaunchEventStream> {
    Arc::new(EventStreamWorkerLaunchEventSource { events })
}
