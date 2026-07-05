pub(in crate::workspace_outbox_worker) const PLAN_TERMINAL_ATTEMPT_MAX_RETRIES_ENV: &str =
    "WORKSPACE_PLAN_TERMINAL_ATTEMPT_MAX_RETRIES";
pub(in crate::workspace_outbox_worker) const AWAITING_LEADER_ADJUDICATION_STATUS: &str =
    "awaiting_leader_adjudication";
pub(in crate::workspace_outbox_worker) const DEFAULT_PLAN_TERMINAL_ATTEMPT_MAX_RETRIES: i64 = 3;

pub(in crate::workspace_outbox_worker) const SUPERVISOR_DECISION_DISPOSE_NODE_ACTION: &str =
    "dispose_node";
pub(in crate::workspace_outbox_worker) const SUPERVISOR_DISPOSED_NODE_DISPOSITION: &str =
    "supervisor_agent_disposed_node";
pub(in crate::workspace_outbox_worker) const SUPERVISOR_DECISION_MARK_BLOCKED_HUMAN_ACTION: &str =
    "mark_blocked_human";
pub(in crate::workspace_outbox_worker) const SUPERVISOR_DECISION_MARK_BLOCKED_HUMAN_REASON: &str =
    "supervisor_decision_mark_blocked_human";
pub(in crate::workspace_outbox_worker) const SUPERVISOR_BLOCKED_HUMAN_VERDICT: &str =
    "blocked_human_required";

pub(in crate::workspace_outbox_worker) const SUPERVISOR_DECISION_REQUEST_PIPELINE_ACTION: &str =
    "request_pipeline";
pub(in crate::workspace_outbox_worker) const SUPERVISOR_DECISION_REQUEST_PIPELINE_REASON: &str =
    "supervisor_decision_request_pipeline";
pub(in crate::workspace_outbox_worker) const SUPERVISOR_DECISION_WAIT_PIPELINE_ACTION: &str =
    "wait_pipeline";
pub(in crate::workspace_outbox_worker) const SUPERVISOR_DECISION_WAIT_PIPELINE_REASON: &str =
    "supervisor_decision_wait_pipeline";
pub(in crate::workspace_outbox_worker) const SUPERVISOR_DECISION_NOOP_ACTION: &str = "noop";
pub(in crate::workspace_outbox_worker) const SUPERVISOR_DECISION_NOOP_REASON: &str =
    "supervisor_decision_noop";

pub(in crate::workspace_outbox_worker) const SUPERVISOR_DECISION_CREATE_REPAIR_NODE_ACTION: &str =
    "create_repair_node";
pub(in crate::workspace_outbox_worker) const SUPERVISOR_DECISION_CREATE_REPAIR_NODE_REASON: &str =
    "supervisor_decision_create_repair_node";
pub(in crate::workspace_outbox_worker) const SUPERVISOR_DECISION_REPLAN_NODE_ACTION: &str =
    "replan_node";
pub(in crate::workspace_outbox_worker) const SUPERVISOR_DECISION_REPLAN_NODE_REASON: &str =
    "supervisor_decision_replan_node";
pub(in crate::workspace_outbox_worker) const SUPERVISOR_REPLAN_REQUESTED_VERDICT: &str =
    "replan_requested";

pub(in crate::workspace_outbox_worker) const SUPERVISOR_DECISION_RETRY_SAME_NODE_ACTION: &str =
    "retry_same_node";
pub(in crate::workspace_outbox_worker) const SUPERVISOR_DECISION_RETRY_SAME_NODE_REASON: &str =
    "supervisor_decision_retry_same_node";
pub(in crate::workspace_outbox_worker) const TERMINAL_RETRY_ATTEMPT_STATUSES: [&str; 3] =
    ["rejected", "blocked", "cancelled"];
