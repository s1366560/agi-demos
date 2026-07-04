use std::collections::HashMap;

use serde_json::json;

use super::*;

const ITERATION_PHASE_ORDER: [&str; 6] =
    ["research", "plan", "implement", "test", "deploy", "review"];

pub(super) fn node_iteration_phase(node: &WorkspacePlanNodeRecord) -> String {
    let metadata = object_or_empty(node.metadata_json.clone());
    if let Some(phase) = metadata.get("iteration_phase").and_then(Value::as_str) {
        if ITERATION_PHASE_ORDER.contains(&phase) {
            return phase.to_string();
        }
    }
    if let Some(sequence) = node
        .feature_checkpoint_json
        .as_ref()
        .and_then(|value| value.get("sequence"))
        .and_then(Value::as_i64)
        .filter(|value| *value > 0)
    {
        return ITERATION_PHASE_ORDER[((sequence - 1) as usize) % ITERATION_PHASE_ORDER.len()]
            .to_string();
    }
    "plan".to_string()
}

pub(super) fn phase_contract_view(phase: &str) -> WorkspacePlanPhaseContractView {
    let (title, entry_gate, exit_gate, evidence, routing) = match phase {
        "research" => (
            "Research",
            "Root goal and code context are visible to the worker.",
            "Problem facts, constraints, and unknowns are captured as evidence.",
            vec!["research notes", "scope facts"],
            vec!["continue", "replan", "recover"],
        ),
        "implement" => (
            "Implement",
            "Story card and write scope are bounded.",
            "Changed files and a local recovery boundary are recorded.",
            vec![
                "changed files",
                "commit or recovery ref",
                "scope discipline",
            ],
            vec!["continue", "recover", "replan"],
        ),
        "test" => (
            "Test",
            "Implementation evidence exists.",
            "Required checks produce machine-verifiable evidence.",
            vec!["ci pipeline", "test stage", "failure recovery"],
            vec!["continue", "recover", "replan"],
        ),
        "deploy" => (
            "Deploy",
            "Pipeline is green or recovery is in progress.",
            "Required preview services are registered and healthy.",
            vec!["deployment health", "preview URL", "service logs"],
            vec!["continue", "recover", "needs_human_review"],
        ),
        "review" => (
            "Review",
            "Pipeline and deployment evidence are available.",
            "AC-by-AC verdict and next-iteration routing verdict are recorded.",
            vec!["review verdict", "evidence index", "next routing"],
            vec![
                "complete_goal",
                "continue_next_iteration",
                "needs_human_review",
            ],
        ),
        _ => (
            "Plan",
            "Research context is available or explicitly not required.",
            "Story card includes AC, dependencies, impact, out-of-scope, and task budget.",
            vec!["story card", "acceptance criteria", "task budget"],
            vec!["continue", "replan", "needs_human_review"],
        ),
    };
    WorkspacePlanPhaseContractView {
        phase: phase.to_string(),
        title: title.to_string(),
        entry_gate: entry_gate.to_string(),
        exit_gate: exit_gate.to_string(),
        required_evidence: evidence.into_iter().map(ToOwned::to_owned).collect(),
        allowed_routing: routing.into_iter().map(ToOwned::to_owned).collect(),
        blocked_semantics: "Blocked is reserved for missing human permission, credentials, policy decisions, or irreversible operator choices. Test, pipeline, or evidence failures should route to recovery or replan.".to_string(),
    }
}

pub(super) fn iteration_summary_view(
    plan: &WorkspacePlanRecord,
    nodes: &[WorkspacePlanNodeRecord],
) -> WorkspacePlanIterationSummaryView {
    let runnable: Vec<_> = nodes
        .iter()
        .filter(|node| matches!(node.kind.as_str(), "task" | "verify"))
        .collect();
    let goal_metadata = nodes
        .iter()
        .find(|node| node.id == plan.goal_id)
        .or_else(|| nodes.iter().find(|node| node.kind == "goal"))
        .map(|node| object_or_empty(node.metadata_json.clone()))
        .unwrap_or_else(|| json!({}));
    let loop_metadata = goal_metadata
        .get("iteration_loop")
        .filter(|value| value.is_object())
        .cloned()
        .unwrap_or_else(|| json!({}));
    let loop_status = string_from_value(loop_metadata.get("loop_status")).unwrap_or_else(|| {
        if plan.status == "completed" {
            "completed".to_string()
        } else if plan.status == "suspended" {
            "suspended".to_string()
        } else {
            "active".to_string()
        }
    });
    let current_iteration = int_from_value(loop_metadata.get("current_iteration"), 1);
    let max_iterations = int_from_value(loop_metadata.get("max_iterations"), 8);
    let active_phase = runnable
        .iter()
        .find(|node| node.intent != "done")
        .map(|node| node_iteration_phase(node))
        .unwrap_or_else(|| "research".to_string());
    let phases = ITERATION_PHASE_ORDER
        .iter()
        .map(|phase| iteration_phase_view(phase, &runnable))
        .collect();
    WorkspacePlanIterationSummaryView {
        current_iteration,
        loop_label: "Scrum feedback loop".to_string(),
        cadence: "research -> plan -> implement -> test -> deploy -> review".to_string(),
        loop_status,
        max_iterations,
        completed_iterations: int_list_from_value(loop_metadata.get("completed_iterations")),
        current_sprint_goal: string_from_value(loop_metadata.get("current_sprint_goal"))
            .unwrap_or_default(),
        review_summary: string_from_value(loop_metadata.get("last_review_summary"))
            .unwrap_or_default(),
        stop_reason: string_from_value(loop_metadata.get("stop_reason")).unwrap_or_default(),
        active_phase_label: phase_label(&active_phase),
        active_phase,
        next_action: String::new(),
        task_count: runnable.len() as i32,
        task_budget: int_from_value(goal_metadata.get("task_budget"), 6),
        phases,
        deliverables: metadata_string_values(&loop_metadata, &["deliverables"]),
        feedback_items: metadata_string_values(&loop_metadata, &["feedback_items"]),
        history: Vec::new(),
        actions: HashMap::from([
            (
                "pause_iteration".to_string(),
                action(plan.status != "completed", "Pause loop", None, false),
            ),
            (
                "resume_iteration".to_string(),
                action(plan.status != "completed", "Resume loop", None, false),
            ),
            (
                "trigger_next_iteration".to_string(),
                action(
                    plan.status != "completed",
                    "Trigger next iteration",
                    None,
                    true,
                ),
            ),
        ]),
        findings: Vec::new(),
        rejected_finding_count: int_from_value(
            loop_metadata.get("last_review_rejected_finding_count"),
            0,
        ),
    }
}

fn iteration_phase_view(
    phase: &str,
    nodes: &[&WorkspacePlanNodeRecord],
) -> WorkspacePlanIterationPhaseView {
    let phase_nodes: Vec<_> = nodes
        .iter()
        .copied()
        .filter(|node| node_iteration_phase(node) == phase)
        .collect();
    let total = phase_nodes.len() as i32;
    let done = phase_nodes
        .iter()
        .filter(|node| node.intent == "done")
        .count() as i32;
    let blocked = phase_nodes
        .iter()
        .filter(|node| node.intent == "blocked")
        .count() as i32;
    let running = phase_nodes
        .iter()
        .filter(|node| {
            matches!(
                node.execution.as_str(),
                "running" | "dispatching" | "executing"
            )
        })
        .count() as i32;
    WorkspacePlanIterationPhaseView {
        id: phase.to_string(),
        label: phase_label(phase),
        total,
        done,
        running,
        blocked,
        progress: if total > 0 { (done * 100) / total } else { 0 },
        gate_status: gate_status_view(),
        required_artifacts: Vec::new(),
        missing_artifacts: Vec::new(),
        summary: String::new(),
    }
}

pub(super) fn delivery_summary_view(plan: &WorkspacePlanRecord) -> WorkspaceDeliverySummaryView {
    WorkspaceDeliverySummaryView {
        provider: "sandbox_native".to_string(),
        status: "not_configured".to_string(),
        contract_source: "metadata".to_string(),
        contract_confidence: 0.0,
        agent_managed: true,
        code_root: None,
        latest_run: None,
        recent_runs: Vec::new(),
        services: Vec::new(),
        deployment: None,
        deployments: Vec::new(),
        run_assessment: WorkspacePlanRunAssessmentView {
            status: "not_run".to_string(),
            summary: "No pipeline run has been recorded.".to_string(),
            evidence_refs: Vec::new(),
            warnings: Vec::new(),
            required_services_total: 0,
            required_services_healthy: 0,
            failed_required_services: Vec::new(),
        },
        warnings: Vec::new(),
        actions: HashMap::from([
            (
                "request_pipeline".to_string(),
                action(
                    plan.status != "completed",
                    "Run pipeline",
                    if plan.status == "completed" {
                        Some("The plan is already complete.")
                    } else {
                        None
                    },
                    false,
                ),
            ),
            (
                "regenerate_contract".to_string(),
                action(
                    plan.status != "completed",
                    "Regenerate contract",
                    if plan.status == "completed" {
                        Some("The plan is already complete.")
                    } else {
                        None
                    },
                    false,
                ),
            ),
            (
                "restart_preview".to_string(),
                action(
                    false,
                    "Restart preview",
                    Some("No preview deployment exists."),
                    false,
                ),
            ),
            (
                "rollback_preview".to_string(),
                action(
                    false,
                    "Rollback preview",
                    Some("No rollback reference is available."),
                    true,
                ),
            ),
        ]),
    }
}

pub(super) fn plan_history_view(
    plan: &WorkspacePlanRecord,
    nodes: &[WorkspacePlanNodeRecord],
    latest_plan_id: &str,
    selected_plan_id: &str,
) -> WorkspacePlanHistoryItemView {
    let runnable: Vec<_> = nodes
        .iter()
        .filter(|node| matches!(node.kind.as_str(), "task" | "verify"))
        .collect();
    let goal_node = nodes
        .iter()
        .find(|node| node.id == plan.goal_id)
        .or_else(|| nodes.iter().find(|node| node.kind == "goal"));
    let loop_metadata = goal_node
        .and_then(|node| node.metadata_json.get("iteration_loop"))
        .filter(|value| value.is_object())
        .cloned()
        .unwrap_or_else(|| json!({}));
    WorkspacePlanHistoryItemView {
        plan_id: plan.id.clone(),
        title: goal_node
            .map(|node| node.title.clone())
            .unwrap_or_else(|| plan.goal_id.clone()),
        status: plan.status.clone(),
        loop_status: string_from_value(loop_metadata.get("loop_status")).unwrap_or_else(|| {
            if plan.status == "completed" {
                "completed".to_string()
            } else if plan.status == "suspended" {
                "suspended".to_string()
            } else {
                "active".to_string()
            }
        }),
        root_goal_id: None,
        root_goal_status: None,
        current_iteration: int_from_value(loop_metadata.get("current_iteration"), 1),
        max_iterations: int_from_value(loop_metadata.get("max_iterations"), 8),
        completed_iterations: int_list_from_value(loop_metadata.get("completed_iterations")),
        task_count: runnable.len() as i32,
        created_at: iso(plan.created_at),
        updated_at: plan.updated_at.map(iso),
        is_latest: plan.id == latest_plan_id,
        is_selected: plan.id == selected_plan_id,
    }
}
