use std::collections::HashMap;

use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct WorkspacePlanActionCapabilityView {
    pub(in crate::workspace_api) enabled: bool,
    pub(in crate::workspace_api) label: String,
    pub(in crate::workspace_api) reason: Option<String>,
    pub(in crate::workspace_api) requires_confirmation: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct WorkspacePlanPhaseContractView {
    pub(in crate::workspace_api) phase: String,
    pub(in crate::workspace_api) title: String,
    pub(in crate::workspace_api) entry_gate: String,
    pub(in crate::workspace_api) exit_gate: String,
    pub(in crate::workspace_api) required_evidence: Vec<String>,
    pub(in crate::workspace_api) allowed_routing: Vec<String>,
    pub(in crate::workspace_api) blocked_semantics: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct WorkspacePlanGateStatusView {
    pub(in crate::workspace_api) status: String,
    pub(in crate::workspace_api) summary: String,
    pub(in crate::workspace_api) missing: Vec<String>,
    pub(in crate::workspace_api) evidence_refs: Vec<String>,
    pub(in crate::workspace_api) routing: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct WorkspacePlanEvidenceBundleView {
    pub(in crate::workspace_api) artifacts: Vec<String>,
    pub(in crate::workspace_api) evidence_refs: Vec<String>,
    pub(in crate::workspace_api) changed_files: Vec<String>,
    pub(in crate::workspace_api) pipeline_refs: Vec<String>,
    pub(in crate::workspace_api) verification_summary: String,
    pub(in crate::workspace_api) review_summary: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct WorkspacePlanBlockerAnalysisView {
    pub(in crate::workspace_api) blocker_type: String,
    pub(in crate::workspace_api) root_cause: String,
    pub(in crate::workspace_api) resolution: String,
    pub(in crate::workspace_api) routing_decision: String,
    pub(in crate::workspace_api) human_intervention_required: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct WorkspacePlanNodeView {
    pub(in crate::workspace_api) id: String,
    pub(in crate::workspace_api) parent_id: Option<String>,
    pub(in crate::workspace_api) kind: String,
    pub(in crate::workspace_api) title: String,
    pub(in crate::workspace_api) description: String,
    pub(in crate::workspace_api) depends_on: Vec<String>,
    pub(in crate::workspace_api) acceptance_criteria: Vec<Value>,
    pub(in crate::workspace_api) feature_checkpoint: Option<Value>,
    pub(in crate::workspace_api) handoff_package: Option<Value>,
    pub(in crate::workspace_api) recommended_capabilities: Vec<Value>,
    pub(in crate::workspace_api) intent: String,
    pub(in crate::workspace_api) execution: String,
    pub(in crate::workspace_api) progress: Value,
    pub(in crate::workspace_api) assignee_agent_id: Option<String>,
    pub(in crate::workspace_api) current_attempt_id: Option<String>,
    pub(in crate::workspace_api) workspace_task_id: Option<String>,
    pub(in crate::workspace_api) priority: i32,
    pub(in crate::workspace_api) metadata: Value,
    pub(in crate::workspace_api) created_at: String,
    pub(in crate::workspace_api) updated_at: Option<String>,
    pub(in crate::workspace_api) completed_at: Option<String>,
    pub(in crate::workspace_api) phase_contract: Option<WorkspacePlanPhaseContractView>,
    pub(in crate::workspace_api) evidence_bundle: WorkspacePlanEvidenceBundleView,
    pub(in crate::workspace_api) gate_status: WorkspacePlanGateStatusView,
    pub(in crate::workspace_api) blocker_analysis: Option<WorkspacePlanBlockerAnalysisView>,
    pub(in crate::workspace_api) actions: HashMap<String, WorkspacePlanActionCapabilityView>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct WorkspacePlanView {
    pub(in crate::workspace_api) id: String,
    pub(in crate::workspace_api) workspace_id: String,
    pub(in crate::workspace_api) goal_id: String,
    pub(in crate::workspace_api) status: String,
    pub(in crate::workspace_api) created_at: String,
    pub(in crate::workspace_api) updated_at: Option<String>,
    pub(in crate::workspace_api) nodes: Vec<WorkspacePlanNodeView>,
    pub(in crate::workspace_api) counts: HashMap<String, i32>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct WorkspacePlanIterationPhaseView {
    pub(in crate::workspace_api) id: String,
    pub(in crate::workspace_api) label: String,
    pub(in crate::workspace_api) total: i32,
    pub(in crate::workspace_api) done: i32,
    pub(in crate::workspace_api) running: i32,
    pub(in crate::workspace_api) blocked: i32,
    pub(in crate::workspace_api) progress: i32,
    pub(in crate::workspace_api) gate_status: WorkspacePlanGateStatusView,
    pub(in crate::workspace_api) required_artifacts: Vec<String>,
    pub(in crate::workspace_api) missing_artifacts: Vec<String>,
    pub(in crate::workspace_api) summary: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct WorkspacePlanIterationSummaryView {
    pub(in crate::workspace_api) current_iteration: i32,
    pub(in crate::workspace_api) loop_label: String,
    pub(in crate::workspace_api) cadence: String,
    pub(in crate::workspace_api) loop_status: String,
    pub(in crate::workspace_api) max_iterations: i32,
    pub(in crate::workspace_api) completed_iterations: Vec<i32>,
    pub(in crate::workspace_api) current_sprint_goal: String,
    pub(in crate::workspace_api) review_summary: String,
    pub(in crate::workspace_api) stop_reason: String,
    pub(in crate::workspace_api) active_phase: String,
    pub(in crate::workspace_api) active_phase_label: String,
    pub(in crate::workspace_api) next_action: String,
    pub(in crate::workspace_api) task_count: i32,
    pub(in crate::workspace_api) task_budget: i32,
    pub(in crate::workspace_api) phases: Vec<WorkspacePlanIterationPhaseView>,
    pub(in crate::workspace_api) deliverables: Vec<String>,
    pub(in crate::workspace_api) feedback_items: Vec<String>,
    pub(in crate::workspace_api) history: Vec<Value>,
    pub(in crate::workspace_api) actions: HashMap<String, WorkspacePlanActionCapabilityView>,
    pub(in crate::workspace_api) findings: Vec<Value>,
    pub(in crate::workspace_api) rejected_finding_count: i32,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct WorkspacePlanRunAssessmentView {
    pub(in crate::workspace_api) status: String,
    pub(in crate::workspace_api) summary: String,
    pub(in crate::workspace_api) evidence_refs: Vec<String>,
    pub(in crate::workspace_api) warnings: Vec<String>,
    pub(in crate::workspace_api) required_services_total: i32,
    pub(in crate::workspace_api) required_services_healthy: i32,
    pub(in crate::workspace_api) failed_required_services: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct WorkspaceDeliverySummaryView {
    pub(in crate::workspace_api) provider: String,
    pub(in crate::workspace_api) status: String,
    pub(in crate::workspace_api) contract_source: String,
    pub(in crate::workspace_api) contract_confidence: f64,
    pub(in crate::workspace_api) agent_managed: bool,
    pub(in crate::workspace_api) code_root: Option<String>,
    pub(in crate::workspace_api) latest_run: Option<Value>,
    pub(in crate::workspace_api) recent_runs: Vec<Value>,
    pub(in crate::workspace_api) services: Vec<Value>,
    pub(in crate::workspace_api) deployment: Option<Value>,
    pub(in crate::workspace_api) deployments: Vec<Value>,
    pub(in crate::workspace_api) run_assessment: WorkspacePlanRunAssessmentView,
    pub(in crate::workspace_api) warnings: Vec<String>,
    pub(in crate::workspace_api) actions: HashMap<String, WorkspacePlanActionCapabilityView>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct WorkspacePlanBlackboardEntryView {
    pub(in crate::workspace_api) plan_id: String,
    pub(in crate::workspace_api) key: String,
    pub(in crate::workspace_api) value: Value,
    pub(in crate::workspace_api) published_by: String,
    pub(in crate::workspace_api) version: i32,
    pub(in crate::workspace_api) schema_ref: Option<String>,
    pub(in crate::workspace_api) metadata: Value,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct WorkspacePlanOutboxItemView {
    pub(in crate::workspace_api) id: String,
    pub(in crate::workspace_api) plan_id: Option<String>,
    pub(in crate::workspace_api) workspace_id: String,
    pub(in crate::workspace_api) event_type: String,
    pub(in crate::workspace_api) payload: Value,
    pub(in crate::workspace_api) status: String,
    pub(in crate::workspace_api) attempt_count: i32,
    pub(in crate::workspace_api) max_attempts: i32,
    pub(in crate::workspace_api) lease_owner: Option<String>,
    pub(in crate::workspace_api) lease_expires_at: Option<String>,
    pub(in crate::workspace_api) last_error: Option<String>,
    pub(in crate::workspace_api) next_attempt_at: Option<String>,
    pub(in crate::workspace_api) processed_at: Option<String>,
    pub(in crate::workspace_api) metadata: Value,
    pub(in crate::workspace_api) created_at: String,
    pub(in crate::workspace_api) updated_at: Option<String>,
    pub(in crate::workspace_api) actions: HashMap<String, WorkspacePlanActionCapabilityView>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct WorkspacePlanEventView {
    pub(in crate::workspace_api) id: String,
    pub(in crate::workspace_api) plan_id: String,
    pub(in crate::workspace_api) workspace_id: String,
    pub(in crate::workspace_api) node_id: Option<String>,
    pub(in crate::workspace_api) attempt_id: Option<String>,
    pub(in crate::workspace_api) event_type: String,
    pub(in crate::workspace_api) source: String,
    pub(in crate::workspace_api) actor_id: Option<String>,
    pub(in crate::workspace_api) payload: Value,
    pub(in crate::workspace_api) created_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct WorkspacePlanHistoryItemView {
    pub(in crate::workspace_api) plan_id: String,
    pub(in crate::workspace_api) title: String,
    pub(in crate::workspace_api) status: String,
    pub(in crate::workspace_api) loop_status: String,
    pub(in crate::workspace_api) root_goal_id: Option<String>,
    pub(in crate::workspace_api) root_goal_status: Option<String>,
    pub(in crate::workspace_api) current_iteration: i32,
    pub(in crate::workspace_api) max_iterations: i32,
    pub(in crate::workspace_api) completed_iterations: Vec<i32>,
    pub(in crate::workspace_api) task_count: i32,
    pub(in crate::workspace_api) created_at: String,
    pub(in crate::workspace_api) updated_at: Option<String>,
    pub(in crate::workspace_api) is_latest: bool,
    pub(in crate::workspace_api) is_selected: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct WorkspacePlanSnapshotView {
    pub(in crate::workspace_api) workspace_id: String,
    pub(in crate::workspace_api) plan: Option<WorkspacePlanView>,
    pub(in crate::workspace_api) root_goal: Option<Value>,
    pub(in crate::workspace_api) iteration: Option<WorkspacePlanIterationSummaryView>,
    pub(in crate::workspace_api) delivery: Option<WorkspaceDeliverySummaryView>,
    pub(in crate::workspace_api) blackboard: Vec<WorkspacePlanBlackboardEntryView>,
    pub(in crate::workspace_api) outbox: Vec<WorkspacePlanOutboxItemView>,
    pub(in crate::workspace_api) events: Vec<WorkspacePlanEventView>,
    pub(in crate::workspace_api) plan_history: Vec<WorkspacePlanHistoryItemView>,
    pub(in crate::workspace_api) iteration_runs: Vec<Value>,
    pub(in crate::workspace_api) run_health: Option<Value>,
    pub(in crate::workspace_api) artifact_index: Option<Value>,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub(crate) struct WorkspacePlanActionRequest {
    #[serde(default)]
    pub(in crate::workspace_api) reason: Option<String>,
    #[serde(default)]
    pub(in crate::workspace_api) evidence_refs: Vec<String>,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub(crate) struct WorkspacePlanPipelineRunRequest {
    #[serde(default)]
    pub(in crate::workspace_api) reason: Option<String>,
    #[serde(default)]
    pub(in crate::workspace_api) evidence_refs: Vec<String>,
    #[serde(default)]
    pub(in crate::workspace_api) node_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub(crate) struct WorkspacePlanActionResultView {
    pub(in crate::workspace_api) ok: bool,
    pub(in crate::workspace_api) message: String,
    pub(in crate::workspace_api) plan_id: String,
    pub(in crate::workspace_api) node_id: Option<String>,
    pub(in crate::workspace_api) outbox_id: Option<String>,
}
