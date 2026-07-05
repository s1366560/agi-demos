use super::super::support_dispatch::FakeWorkspacePlanDispatchStore;
use super::super::support_outbox::outbox;
use super::super::*;

pub(in crate::workspace_outbox_worker::tests) fn worker_launch_handler(
    store: Arc<FakeWorkspacePlanDispatchStore>,
    max_active: i64,
) -> WorkerLaunchAdmissionHandler {
    WorkerLaunchAdmissionHandler::with_config(
        store as Arc<dyn WorkspacePlanDispatchStore>,
        WorkerLaunchAdmissionConfig {
            max_active_worker_conversations: max_active,
            defer_seconds: 30,
            active_event_grace_seconds: 60,
            stream_poll_interval_seconds: 5,
        },
    )
}

pub(in crate::workspace_outbox_worker::tests) fn worker_launch_handler_with_state(
    store: Arc<FakeWorkspacePlanDispatchStore>,
    runtime_state: Arc<FakeWorkerLaunchRuntimeStateStore>,
    max_active: i64,
) -> WorkerLaunchAdmissionHandler {
    WorkerLaunchAdmissionHandler::with_config_and_runtime_state(
        store as Arc<dyn WorkspacePlanDispatchStore>,
        runtime_state as Arc<dyn WorkerLaunchRuntimeStateStore>,
        WorkerLaunchAdmissionConfig {
            max_active_worker_conversations: max_active,
            defer_seconds: 30,
            active_event_grace_seconds: 60,
            stream_poll_interval_seconds: 5,
        },
    )
}

pub(in crate::workspace_outbox_worker::tests) fn worker_launch_handler_with_event_stream(
    store: Arc<FakeWorkspacePlanDispatchStore>,
    stream_events: Arc<FakeWorkerLaunchEventStream>,
    max_active: i64,
) -> WorkerLaunchAdmissionHandler {
    WorkerLaunchAdmissionHandler::with_config_and_event_stream(
        store as Arc<dyn WorkspacePlanDispatchStore>,
        stream_events as Arc<dyn WorkerLaunchEventStream>,
        WorkerLaunchAdmissionConfig {
            max_active_worker_conversations: max_active,
            defer_seconds: 30,
            active_event_grace_seconds: 60,
            stream_poll_interval_seconds: 5,
        },
    )
}

pub(in crate::workspace_outbox_worker::tests) fn worker_launch_handler_with_state_and_event_stream(
    store: Arc<FakeWorkspacePlanDispatchStore>,
    runtime_state: Arc<FakeWorkerLaunchRuntimeStateStore>,
    stream_events: Arc<FakeWorkerLaunchEventStream>,
    max_active: i64,
) -> WorkerLaunchAdmissionHandler {
    WorkerLaunchAdmissionHandler::with_config_and_runtime_state_and_event_stream(
        store as Arc<dyn WorkspacePlanDispatchStore>,
        runtime_state as Arc<dyn WorkerLaunchRuntimeStateStore>,
        stream_events as Arc<dyn WorkerLaunchEventStream>,
        WorkerLaunchAdmissionConfig {
            max_active_worker_conversations: max_active,
            defer_seconds: 30,
            active_event_grace_seconds: 60,
            stream_poll_interval_seconds: 5,
        },
    )
}

pub(in crate::workspace_outbox_worker::tests) fn worker_launch_item() -> WorkspacePlanOutboxRecord {
    let mut item = outbox("job-worker-launch", WORKER_LAUNCH_EVENT);
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "task_id": "task-test",
        "node_id": "node-test",
        "worker_agent_id": "agent-worker",
        "actor_user_id": "actor-test",
        "leader_agent_id": WORKSPACE_PLAN_SYSTEM_ACTOR_ID,
        "attempt_id": "attempt-test",
        "extra_instructions": "continue implementation"
    });
    item
}
