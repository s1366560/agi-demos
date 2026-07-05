use super::super::support_dispatch::FakeWorkspacePlanDispatchStore;
use super::super::support_outbox::outbox;
use super::super::*;

pub(in crate::workspace_outbox_worker::tests) fn supervisor_tick_handler(
    store: Arc<FakeWorkspacePlanDispatchStore>,
) -> SupervisorTickAdmissionHandler {
    SupervisorTickAdmissionHandler::new(store as Arc<dyn WorkspacePlanDispatchStore>)
}

pub(in crate::workspace_outbox_worker::tests) fn supervisor_tick_retry_item(
) -> WorkspacePlanOutboxRecord {
    let mut item = outbox("job-supervisor-tick", SUPERVISOR_TICK_EVENT);
    item.plan_id = Some("plan-test".to_string());
    item.payload_json = json!({
        "workspace_id": "workspace-test",
        "plan_id": "plan-test",
        "retry_node_id": "node-test",
        "retry_attempt_id": "attempt-stale",
        "retry_reason": "stale_plan_node_no_terminal_worker_report",
        "leader_agent_id": WORKSPACE_PLAN_SYSTEM_ACTOR_ID,
        "extra_instructions": "recover stale node"
    });
    item
}
