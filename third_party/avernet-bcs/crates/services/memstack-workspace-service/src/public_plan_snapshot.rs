//! Legacy Workspace Plan snapshot DTOs and deterministic projection mapping.

use std::collections::BTreeMap;

use memstack_workspace_store::{
    WorkspacePipelineRunRecord, WorkspacePlanBlackboardRecord, WorkspacePlanEventRecord,
    WorkspacePlanNodeRecord, WorkspacePlanOutboxRecord, WorkspacePlanRecord, WorkspacePlanSnapshot,
};
use serde::Serialize;
use serde_json::{Value, json};

/// Legacy Plan node response.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct PublicWorkspacePlanNode {
    pub id: String,
    pub parent_id: Option<String>,
    pub kind: String,
    pub title: String,
    pub description: String,
    pub depends_on: Value,
    pub acceptance_criteria: Value,
    pub feature_checkpoint: Option<Value>,
    pub handoff_package: Option<Value>,
    pub recommended_capabilities: Value,
    pub intent: String,
    pub execution: String,
    pub progress: Value,
    pub assignee_agent_id: Option<String>,
    pub current_attempt_id: Option<String>,
    pub workspace_task_id: Option<String>,
    pub priority: i64,
    pub metadata: Value,
    pub created_at: String,
    pub updated_at: Option<String>,
    pub completed_at: Option<String>,
    pub phase_contract: Option<Value>,
    pub evidence_bundle: Value,
    pub gate_status: Value,
    pub blocker_analysis: Option<Value>,
    pub actions: Value,
}

/// Legacy Plan response.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct PublicWorkspacePlan {
    pub id: String,
    pub workspace_id: String,
    pub goal_id: String,
    pub status: String,
    pub created_at: String,
    pub updated_at: Option<String>,
    pub nodes: Vec<PublicWorkspacePlanNode>,
    pub counts: BTreeMap<String, u64>,
}

/// Legacy snapshot top-level contract.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct PublicWorkspacePlanSnapshot {
    pub workspace_id: String,
    pub plan: Option<PublicWorkspacePlan>,
    pub root_goal: Option<Value>,
    pub iteration: Option<Value>,
    pub delivery: Option<Value>,
    pub blackboard: Vec<Value>,
    pub outbox: Vec<Value>,
    pub events: Vec<Value>,
    pub plan_history: Vec<Value>,
    pub iteration_runs: Vec<Value>,
    pub run_health: Option<Value>,
    pub artifact_index: Option<Value>,
}

pub(super) fn public_snapshot(
    workspace_id: &str,
    snapshot: WorkspacePlanSnapshot,
) -> PublicWorkspacePlanSnapshot {
    let selected_plan_id = snapshot.selected.as_ref().map(|plan| plan.plan_id.as_str());
    let plan = snapshot.selected.as_ref().map(|record| {
        let nodes = snapshot.nodes.iter().map(public_node).collect::<Vec<_>>();
        let mut counts = BTreeMap::new();
        for node in &snapshot.nodes {
            *counts.entry(node.status.clone()).or_insert(0) += 1;
        }
        let goal_id = snapshot
            .nodes
            .iter()
            .find(|node| node.kind == "goal")
            .map_or_else(|| record.plan_id.clone(), |node| node.node_id.clone());
        PublicWorkspacePlan {
            id: record.plan_id.clone(),
            workspace_id: record.workspace_id.clone(),
            goal_id,
            status: record.status.clone(),
            created_at: record.created_at.clone(),
            updated_at: Some(record.updated_at.clone()),
            nodes,
            counts,
        }
    });
    let root_goal = snapshot
        .nodes
        .iter()
        .find(|node| node.kind == "goal")
        .map(|node| {
            json!({
                "id": &node.node_id, "title": &node.title, "status": &node.status,
                "blocker_reason": node.metadata.get("blocker_reason"),
                "goal_health": node.metadata.get("goal_health"),
                "remediation_status": node.metadata.get("remediation_status"),
                "remediation_summary": node.metadata.get("remediation_summary"),
                "evidence_grade": node.metadata.get("evidence_grade"),
                "completion_blocker_reason": node.metadata.get("completion_blocker_reason"),
                "updated_at": &node.updated_at, "completed_at": &node.completed_at,
            })
        });
    let iteration = snapshot.selected.as_ref().map(|record| {
        let loop_state = record
            .metadata
            .get("iteration_loop")
            .cloned()
            .unwrap_or_else(|| json!({}));
        json!({
            "current_iteration": loop_state.get("current_iteration").and_then(Value::as_u64).unwrap_or(1),
            "loop_label": "Scrum feedback loop",
            "cadence": "research -> plan -> implement -> test -> deploy -> review",
            "loop_status": loop_state.get("loop_status").and_then(Value::as_str).unwrap_or("active"),
            "max_iterations": loop_state.get("max_iterations").and_then(Value::as_u64).unwrap_or(8),
            "completed_iterations": loop_state.get("completed_iterations").cloned().unwrap_or_else(|| json!([])),
            "current_sprint_goal": loop_state.get("current_sprint_goal").and_then(Value::as_str).unwrap_or(""),
            "review_summary": loop_state.get("review_summary").and_then(Value::as_str).unwrap_or(""),
            "stop_reason": loop_state.get("stop_reason").and_then(Value::as_str).unwrap_or(""),
            "active_phase": loop_state.get("active_phase").and_then(Value::as_str).unwrap_or("research"),
            "active_phase_label": loop_state.get("active_phase_label").and_then(Value::as_str).unwrap_or("Research"),
            "next_action": loop_state.get("next_action").and_then(Value::as_str).unwrap_or(""),
            "task_count": snapshot.nodes.len(),
            "task_budget": loop_state.get("task_budget").and_then(Value::as_u64).unwrap_or(6),
            "phases": [], "deliverables": [], "feedback_items": [], "history": [],
            "actions": {}, "findings": [], "rejected_finding_count": 0,
        })
    });
    let delivery = snapshot
        .selected
        .as_ref()
        .map(|_| public_delivery(&snapshot.pipeline_runs));
    PublicWorkspacePlanSnapshot {
        workspace_id: workspace_id.to_string(),
        plan,
        root_goal,
        iteration,
        delivery,
        blackboard: snapshot.blackboard.iter().map(public_blackboard).collect(),
        outbox: snapshot.outbox.iter().map(public_outbox).collect(),
        events: snapshot.events.iter().map(public_event).collect(),
        plan_history: snapshot
            .history
            .iter()
            .map(|record| public_history(record, selected_plan_id))
            .collect(),
        iteration_runs: Vec::new(),
        run_health: snapshot.selected.as_ref().map(|_| {
            json!({
                "final_status": "unknown", "attempt_success_rate": 0.0, "attempts": {},
                "interactions": {}, "top_failure_reasons": [], "recovery_events": 0,
                "provider_error_events": 0, "repair_turns": {}, "feedback_counts": {},
                "stale_evidence_events": 0, "dirty_worktree_events": 0,
                "missing_report_events": 0,
            })
        }),
        artifact_index: snapshot.selected.as_ref().map(|_| {
            json!({
                "verified_outputs": [], "claimed_outputs": [], "final_deliverables": [],
            })
        }),
    }
}

fn public_node(node: &WorkspacePlanNodeRecord) -> PublicWorkspacePlanNode {
    PublicWorkspacePlanNode {
        id: node.node_id.clone(),
        parent_id: node.parent_id.clone(),
        kind: node.kind.clone(),
        title: node.title.clone(),
        description: node.description.clone().unwrap_or_default(),
        depends_on: node.dependencies.clone(),
        acceptance_criteria: node.acceptance_criteria.clone(),
        feature_checkpoint: node.feature_checkpoint.clone(),
        handoff_package: node.handoff_package.clone(),
        recommended_capabilities: node.recommended_capabilities.clone(),
        intent: node.intent.clone().unwrap_or_else(|| node.status.clone()),
        execution: node.status.clone(),
        progress: node.progress.clone(),
        assignee_agent_id: node.assignee_agent_id.clone(),
        current_attempt_id: node.current_attempt_id.clone(),
        workspace_task_id: node.workspace_task_id.clone(),
        priority: node.priority,
        metadata: node.metadata.clone(),
        created_at: node.created_at.clone(),
        updated_at: Some(node.updated_at.clone()),
        completed_at: node.completed_at.clone(),
        phase_contract: None,
        evidence_bundle: json!({
            "artifacts": [], "evidence_refs": [], "changed_files": [],
            "pipeline_refs": [], "verification_summary": "", "review_summary": "",
        }),
        gate_status: json!({
            "status": "pending", "summary": "", "missing": [],
            "evidence_refs": [], "routing": "continue",
        }),
        blocker_analysis: None,
        actions: json!({}),
    }
}

fn public_blackboard(record: &WorkspacePlanBlackboardRecord) -> Value {
    json!({
        "plan_id": &record.plan_id, "key": &record.key, "value": &record.value,
        "published_by": record.published_by.as_deref().unwrap_or("system"),
        "version": record.version, "schema_ref": &record.schema_ref,
        "metadata": &record.metadata,
    })
}

fn public_outbox(record: &WorkspacePlanOutboxRecord) -> Value {
    json!({
        "id": &record.outbox_id, "plan_id": &record.aggregate_id,
        "workspace_id": &record.workspace_id, "event_type": &record.event_type,
        "payload": &record.payload, "status": &record.status,
        "attempt_count": record.attempt_count, "max_attempts": record.max_attempts,
        "lease_owner": &record.lease_owner, "lease_expires_at": &record.lease_expires_at,
        "last_error": &record.last_error, "next_attempt_at": &record.next_attempt_at,
        "processed_at": &record.dispatched_at, "metadata": &record.metadata,
        "created_at": &record.created_at, "updated_at": &record.updated_at, "actions": {},
    })
}

fn public_event(record: &WorkspacePlanEventRecord) -> Value {
    json!({
        "id": &record.event_id, "plan_id": &record.plan_id,
        "workspace_id": &record.workspace_id, "node_id": &record.node_id,
        "attempt_id": &record.attempt_id, "event_type": &record.event_type,
        "source": &record.source, "actor_id": &record.actor_id,
        "payload": &record.payload, "created_at": &record.created_at,
    })
}

fn public_history(record: &WorkspacePlanRecord, selected_plan_id: Option<&str>) -> Value {
    let loop_state = record
        .metadata
        .get("iteration_loop")
        .and_then(Value::as_object);
    json!({
        "plan_id": &record.plan_id, "title": &record.goal, "status": &record.status,
        "loop_status": loop_state.and_then(|state| state.get("loop_status")).and_then(Value::as_str).unwrap_or("active"),
        "root_goal_id": record.goal_json.get("id"),
        "root_goal_status": record.goal_json.get("status"),
        "current_iteration": loop_state.and_then(|state| state.get("current_iteration")).and_then(Value::as_u64).unwrap_or(1),
        "max_iterations": loop_state.and_then(|state| state.get("max_iterations")).and_then(Value::as_u64).unwrap_or(8),
        "completed_iterations": loop_state.and_then(|state| state.get("completed_iterations")).cloned().unwrap_or_else(|| json!([])),
        "task_count": record.metadata.get("task_count").and_then(Value::as_u64).unwrap_or(0),
        "created_at": &record.created_at, "updated_at": &record.updated_at,
        "is_latest": false, "is_selected": selected_plan_id == Some(record.plan_id.as_str()),
    })
}

fn public_delivery(runs: &[WorkspacePipelineRunRecord]) -> Value {
    let recent_runs = runs
        .iter()
        .map(|run| {
            json!({
                "id": &run.run_id, "provider": &run.provider, "status": &run.status,
                "reason": &run.reason, "node_id": &run.node_id, "attempt_id": &run.attempt_id,
                "commit_ref": &run.commit_ref, "stages": [], "started_at": &run.started_at,
                "completed_at": &run.completed_at, "created_at": &run.created_at,
            })
        })
        .collect::<Vec<_>>();
    json!({
        "provider": runs.first().map_or("sandbox_native", |run| run.provider.as_str()),
        "status": runs.first().map_or("not_configured", |run| run.status.as_str()),
        "contract_source": "metadata", "contract_confidence": 0.0,
        "agent_managed": true, "code_root": null,
        "latest_run": recent_runs.first(), "recent_runs": recent_runs,
        "services": [], "deployment": null, "deployments": [],
        "run_assessment": {
            "status": "not_run", "summary": "No pipeline run has been recorded.",
            "evidence_refs": [], "warnings": [], "required_services_total": 0,
            "required_services_healthy": 0, "failed_required_services": [],
        },
        "warnings": [], "actions": {},
    })
}
