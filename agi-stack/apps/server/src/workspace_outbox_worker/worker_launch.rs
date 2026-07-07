use super::worker_launch_runtime::{
    NoopWorkerLaunchRuntimeStateStore, WorkerLaunchAdmissionAction, WorkerLaunchAdmissionSnapshot,
    WorkerLaunchEventStream, WorkerLaunchRuntimeStateStore,
};
use super::worker_launch_worktree::{worker_launch_worktree_context, WorkerLaunchWorktreeContext};
use super::*;

mod admission;
mod conversation;
mod handler;
mod outbox;
mod stream;
mod terminal;

const WORKER_LAUNCH_MAX_ACTIVE_ENV: &str = "WORKSPACE_WORKER_LAUNCH_MAX_ACTIVE";
const WORKER_LAUNCH_DEFER_SECONDS_ENV: &str = "WORKSPACE_WORKER_LAUNCH_DEFER_SECONDS";
const WORKER_LAUNCH_ACTIVE_EVENT_GRACE_SECONDS_ENV: &str =
    "WORKSPACE_WORKER_LAUNCH_ACTIVE_EVENT_GRACE_SECONDS";
const WORKER_STREAM_POLL_INTERVAL_SECONDS_ENV: &str =
    "WORKSPACE_WORKER_STREAM_POLL_INTERVAL_SECONDS";
const DEFAULT_WORKER_LAUNCH_MAX_ACTIVE: i64 = 4;
const DEFAULT_WORKER_LAUNCH_DEFER_SECONDS: i64 = 20;
const DEFAULT_WORKER_LAUNCH_ACTIVE_EVENT_GRACE_SECONDS: i64 = 300;
const DEFAULT_WORKER_STREAM_POLL_INTERVAL_SECONDS: i64 = 5;
const WORKER_LAUNCH_COOLDOWN_SECONDS: u64 = 300;
const WORKER_LAUNCHABLE_ATTEMPT_STATUSES: [&str; 2] = ["pending", "running"];

#[cfg(test)]
pub(crate) use conversation::worker_conversation_id;
pub(super) use outbox::{
    worker_launch_outbox, WorkerReportPayload, WorkerStreamTerminalPersistence,
};

pub(crate) struct WorkerLaunchAdmissionConfig {
    pub max_active_worker_conversations: i64,
    pub defer_seconds: i64,
    pub active_event_grace_seconds: i64,
    pub stream_poll_interval_seconds: i64,
}

impl WorkerLaunchAdmissionConfig {
    fn from_env() -> Self {
        Self {
            max_active_worker_conversations: i64_env(
                WORKER_LAUNCH_MAX_ACTIVE_ENV,
                DEFAULT_WORKER_LAUNCH_MAX_ACTIVE,
            ),
            defer_seconds: positive_i64_env(
                WORKER_LAUNCH_DEFER_SECONDS_ENV,
                DEFAULT_WORKER_LAUNCH_DEFER_SECONDS,
            ),
            active_event_grace_seconds: positive_i64_env(
                WORKER_LAUNCH_ACTIVE_EVENT_GRACE_SECONDS_ENV,
                DEFAULT_WORKER_LAUNCH_ACTIVE_EVENT_GRACE_SECONDS,
            ),
            stream_poll_interval_seconds: positive_i64_env(
                WORKER_STREAM_POLL_INTERVAL_SECONDS_ENV,
                DEFAULT_WORKER_STREAM_POLL_INTERVAL_SECONDS,
            ),
        }
    }
}

pub(crate) struct WorkerLaunchAdmissionHandler {
    store: Arc<dyn WorkspacePlanDispatchStore>,
    runtime_state: Arc<dyn WorkerLaunchRuntimeStateStore>,
    stream_events: Arc<dyn WorkerLaunchEventStream>,
    config: WorkerLaunchAdmissionConfig,
}

impl WorkerLaunchAdmissionHandler {
    pub(crate) fn with_event_stream(
        store: Arc<dyn WorkspacePlanDispatchStore>,
        stream_events: Arc<dyn WorkerLaunchEventStream>,
    ) -> Self {
        Self::with_runtime_state_and_event_stream(
            store,
            Arc::new(NoopWorkerLaunchRuntimeStateStore),
            stream_events,
        )
    }

    pub(crate) fn with_runtime_state_and_event_stream(
        store: Arc<dyn WorkspacePlanDispatchStore>,
        runtime_state: Arc<dyn WorkerLaunchRuntimeStateStore>,
        stream_events: Arc<dyn WorkerLaunchEventStream>,
    ) -> Self {
        Self {
            store,
            runtime_state,
            stream_events,
            config: WorkerLaunchAdmissionConfig::from_env(),
        }
    }

    #[cfg(test)]
    pub(super) fn with_config(
        store: Arc<dyn WorkspacePlanDispatchStore>,
        config: WorkerLaunchAdmissionConfig,
    ) -> Self {
        Self {
            store,
            runtime_state: Arc::new(NoopWorkerLaunchRuntimeStateStore),
            stream_events: Arc::new(NoopWorkerLaunchEventStream),
            config,
        }
    }

    #[cfg(test)]
    pub(super) fn with_config_and_runtime_state(
        store: Arc<dyn WorkspacePlanDispatchStore>,
        runtime_state: Arc<dyn WorkerLaunchRuntimeStateStore>,
        config: WorkerLaunchAdmissionConfig,
    ) -> Self {
        Self {
            store,
            runtime_state,
            stream_events: Arc::new(NoopWorkerLaunchEventStream),
            config,
        }
    }

    #[cfg(test)]
    pub(super) fn with_config_and_runtime_state_and_event_stream(
        store: Arc<dyn WorkspacePlanDispatchStore>,
        runtime_state: Arc<dyn WorkerLaunchRuntimeStateStore>,
        stream_events: Arc<dyn WorkerLaunchEventStream>,
        config: WorkerLaunchAdmissionConfig,
    ) -> Self {
        Self {
            store,
            runtime_state,
            stream_events,
            config,
        }
    }

    #[cfg(test)]
    pub(super) fn with_config_and_event_stream(
        store: Arc<dyn WorkspacePlanDispatchStore>,
        stream_events: Arc<dyn WorkerLaunchEventStream>,
        config: WorkerLaunchAdmissionConfig,
    ) -> Self {
        Self {
            store,
            runtime_state: Arc::new(NoopWorkerLaunchRuntimeStateStore),
            stream_events,
            config,
        }
    }
}
