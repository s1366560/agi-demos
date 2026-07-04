use std::collections::HashMap;

use super::*;

mod summaries;

use summaries::{
    delivery_summary_view, iteration_summary_view, node_iteration_phase, phase_contract_view,
    plan_history_view,
};

pub(super) fn empty_plan_snapshot(workspace_id: &str) -> WorkspacePlanSnapshotView {
    WorkspacePlanSnapshotView {
        workspace_id: workspace_id.to_string(),
        plan: None,
        root_goal: None,
        iteration: None,
        delivery: None,
        blackboard: Vec::new(),
        outbox: Vec::new(),
        events: Vec::new(),
        plan_history: Vec::new(),
        iteration_runs: Vec::new(),
        run_health: None,
        artifact_index: None,
    }
}

pub(super) fn build_plan_snapshot(
    workspace_id: &str,
    plans_with_nodes: Vec<(WorkspacePlanRecord, Vec<WorkspacePlanNodeRecord>)>,
    selected_plan_id: &str,
    include_details: bool,
    blackboard: Vec<WorkspacePlanBlackboardEntryRecord>,
    outbox: Vec<WorkspacePlanOutboxRecord>,
    events: Vec<WorkspacePlanEventRecord>,
) -> WorkspacePlanSnapshotView {
    if plans_with_nodes.is_empty() {
        return empty_plan_snapshot(workspace_id);
    }
    let selected = plans_with_nodes
        .iter()
        .find(|(plan, _)| plan.id == selected_plan_id)
        .unwrap_or(&plans_with_nodes[0]);
    let plan_view = plan_view(&selected.0, &selected.1);
    if !include_details {
        return WorkspacePlanSnapshotView {
            plan: Some(plan_view),
            root_goal: None,
            ..empty_plan_snapshot(workspace_id)
        };
    }
    let latest_plan_id = plans_with_nodes[0].0.id.clone();
    WorkspacePlanSnapshotView {
        workspace_id: workspace_id.to_string(),
        plan: Some(plan_view),
        root_goal: None,
        iteration: Some(iteration_summary_view(&selected.0, &selected.1)),
        delivery: Some(delivery_summary_view(&selected.0)),
        blackboard: blackboard
            .into_iter()
            .map(WorkspacePlanBlackboardEntryView::from)
            .collect(),
        outbox: outbox
            .into_iter()
            .map(WorkspacePlanOutboxItemView::from)
            .collect(),
        events: events
            .into_iter()
            .map(WorkspacePlanEventView::from)
            .collect(),
        plan_history: plans_with_nodes
            .iter()
            .map(|(plan, nodes)| plan_history_view(plan, nodes, &latest_plan_id, selected_plan_id))
            .collect(),
        iteration_runs: Vec::new(),
        run_health: None,
        artifact_index: None,
    }
}

fn plan_view(plan: &WorkspacePlanRecord, nodes: &[WorkspacePlanNodeRecord]) -> WorkspacePlanView {
    let mut counts = HashMap::new();
    for node in nodes {
        let intent = node_response_intent(plan, node);
        *counts.entry(format!("intent:{intent}")).or_insert(0) += 1;
        *counts
            .entry(format!("execution:{}", node.execution))
            .or_insert(0) += 1;
    }
    let mut node_views: Vec<_> = nodes.iter().map(node_view).collect();
    node_views.sort_by(|a, b| {
        a.kind
            .cmp(&b.kind)
            .then(a.priority.cmp(&b.priority))
            .then(a.id.cmp(&b.id))
    });
    WorkspacePlanView {
        id: plan.id.clone(),
        workspace_id: plan.workspace_id.clone(),
        goal_id: plan.goal_id.clone(),
        status: plan.status.clone(),
        created_at: iso(plan.created_at),
        updated_at: plan.updated_at.map(iso),
        nodes: node_views,
        counts,
    }
}

fn node_view(node: &WorkspacePlanNodeRecord) -> WorkspacePlanNodeView {
    let mut metadata = object_or_empty(node.metadata_json.clone());
    fill_pipeline_status_from_evidence(&mut metadata);
    let phase = node_iteration_phase(node);
    let evidence_bundle = evidence_bundle_view(node, &metadata);
    let gate_status = gate_status_view();
    WorkspacePlanNodeView {
        id: node.id.clone(),
        parent_id: node.parent_id.clone(),
        kind: node.kind.clone(),
        title: node.title.clone(),
        description: node.description.clone(),
        depends_on: node.depends_on_json.clone(),
        acceptance_criteria: node.acceptance_criteria_json.clone(),
        feature_checkpoint: node.feature_checkpoint_json.clone(),
        handoff_package: node.handoff_package_json.clone(),
        recommended_capabilities: node.recommended_capabilities_json.clone(),
        intent: node.intent.clone(),
        execution: node.execution.clone(),
        progress: progress_view(&node.intent, &node.progress_json),
        assignee_agent_id: node.assignee_agent_id.clone(),
        current_attempt_id: node.current_attempt_id.clone(),
        workspace_task_id: node.workspace_task_id.clone(),
        priority: node.priority,
        metadata,
        created_at: iso(node.created_at),
        updated_at: node.updated_at.map(iso),
        completed_at: node.completed_at.map(iso),
        phase_contract: Some(phase_contract_view(&phase)),
        evidence_bundle,
        gate_status,
        blocker_analysis: None,
        actions: node_actions(node),
    }
}

fn node_response_intent(plan: &WorkspacePlanRecord, node: &WorkspacePlanNodeRecord) -> String {
    if plan.status == "completed" && node.kind == "goal" {
        "done".to_string()
    } else {
        node.intent.clone()
    }
}

fn progress_view(intent: &str, raw: &Value) -> Value {
    let progress = object_or_empty(raw.clone());
    json!({
        "percent": if intent == "done" {
            100.0
        } else {
            progress.get("percent").and_then(Value::as_f64).unwrap_or(0.0)
        },
        "confidence": progress.get("confidence").and_then(Value::as_f64).unwrap_or(1.0),
        "note": progress.get("note").and_then(Value::as_str).unwrap_or("")
    })
}

pub(super) fn action(
    enabled: bool,
    label: &str,
    reason: Option<&str>,
    requires_confirmation: bool,
) -> WorkspacePlanActionCapabilityView {
    WorkspacePlanActionCapabilityView {
        enabled,
        label: label.to_string(),
        reason: reason.map(ToOwned::to_owned),
        requires_confirmation,
    }
}

fn node_actions(
    node: &WorkspacePlanNodeRecord,
) -> HashMap<String, WorkspacePlanActionCapabilityView> {
    let executable = matches!(node.kind.as_str(), "task" | "verify");
    let done = node.intent == "done";
    let blocked = node.intent == "blocked";
    let metadata = object_or_empty(node.metadata_json.clone());
    let reviewable = blocked
        || (executable
            && !done
            && metadata
                .get("last_verification_passed")
                .and_then(Value::as_bool)
                == Some(false));
    let has_attempt = node.current_attempt_id.is_some() || node.workspace_task_id.is_some();
    HashMap::from([
        (
            "open_attempt".to_string(),
            action(
                has_attempt,
                "Open attempt",
                if has_attempt {
                    None
                } else {
                    Some("No worker attempt has been linked yet.")
                },
                false,
            ),
        ),
        (
            "request_replan".to_string(),
            action(
                executable && !done,
                "Request replan",
                if executable && !done {
                    None
                } else {
                    Some("Only active task or verification nodes can be replanned.")
                },
                true,
            ),
        ),
        (
            "reopen_blocked".to_string(),
            action(
                blocked,
                "Reopen blocked node",
                if blocked {
                    None
                } else {
                    Some("Only blocked nodes can be reopened.")
                },
                false,
            ),
        ),
        (
            "accept_with_human_review".to_string(),
            action(
                reviewable,
                "Accept after review",
                if reviewable {
                    None
                } else {
                    Some("Only blocked or verification-rework nodes can be accepted after review.")
                },
                true,
            ),
        ),
    ])
}

fn evidence_bundle_view(
    node: &WorkspacePlanNodeRecord,
    metadata: &Value,
) -> WorkspacePlanEvidenceBundleView {
    let evidence_refs = metadata_string_values(
        metadata,
        &[
            "pipeline_evidence_refs",
            "evidence_refs",
            "execution_verifications",
            "verification_evidence_refs",
        ],
    );
    let mut artifacts = Vec::new();
    if let Some(checkpoint) = &node.feature_checkpoint_json {
        artifacts.extend(string_values(checkpoint.get("expected_artifacts")));
    }
    artifacts.extend(metadata_string_values(
        metadata,
        &[
            "artifacts",
            "artifact_refs",
            "deliverables",
            "expected_artifacts",
        ],
    ));
    dedup_truncate(&mut artifacts, 12);
    let mut changed_files = metadata_string_values(
        metadata,
        &["write_set", "changed_files", "git_changed_files"],
    );
    dedup_truncate(&mut changed_files, 20);
    let pipeline_refs = evidence_refs
        .iter()
        .filter(|item| {
            item.starts_with("ci_pipeline:")
                || item.starts_with("pipeline_")
                || item.starts_with("deployment_")
                || item.starts_with("preview_")
        })
        .cloned()
        .collect();
    WorkspacePlanEvidenceBundleView {
        artifacts,
        evidence_refs,
        changed_files,
        pipeline_refs,
        verification_summary: first_metadata_string(
            metadata,
            &[
                "last_verification_summary",
                "verification_summary",
                "worker_report_summary",
                "terminal_report_summary",
            ],
        ),
        review_summary: first_metadata_string(
            metadata,
            &[
                "review_summary",
                "last_review_summary",
                "phase_review_summary",
            ],
        ),
    }
}

fn gate_status_view() -> WorkspacePlanGateStatusView {
    WorkspacePlanGateStatusView {
        status: "pending".to_string(),
        summary: String::new(),
        missing: Vec::new(),
        evidence_refs: Vec::new(),
        routing: "continue".to_string(),
    }
}

fn fill_pipeline_status_from_evidence(metadata: &mut Value) {
    let mut refs = metadata_string_values(metadata, &["pipeline_evidence_refs"]);
    if refs.is_empty() {
        refs = metadata_string_values(
            metadata,
            &[
                "evidence_refs",
                "execution_verifications",
                "verification_evidence_refs",
            ],
        );
    }
    let (status, run_id) = pipeline_status_from_evidence_refs(&refs);
    if let Some(obj) = metadata.as_object_mut() {
        if let Some(status) = status {
            obj.insert("pipeline_status".to_string(), json!(status));
            obj.insert("pipeline_gate_status".to_string(), json!(status));
        }
        if let Some(run_id) = run_id {
            obj.insert("pipeline_run_id".to_string(), json!(run_id));
        }
    }
}

fn pipeline_status_from_evidence_refs(refs: &[String]) -> (Option<&'static str>, Option<String>) {
    let mut status = None;
    let mut run_id = None;
    for value in refs {
        if value == "ci_pipeline:passed" {
            status = Some("success");
        } else if value == "ci_pipeline:failed" {
            status = Some("failed");
        } else if let Some(id) = value.strip_prefix("pipeline_run:success:") {
            status = Some("success");
            run_id = Some(id.to_string());
        } else if let Some(id) = value.strip_prefix("pipeline_run:failed:") {
            status = Some("failed");
            run_id = Some(id.to_string());
        }
    }
    (status, run_id)
}

impl From<WorkspacePlanBlackboardEntryRecord> for WorkspacePlanBlackboardEntryView {
    fn from(record: WorkspacePlanBlackboardEntryRecord) -> Self {
        Self {
            plan_id: record.plan_id,
            key: record.key,
            value: record.value_json.unwrap_or(Value::Null),
            published_by: record.published_by,
            version: record.version,
            schema_ref: record.schema_ref,
            metadata: record.metadata_json,
        }
    }
}

impl From<WorkspacePlanOutboxRecord> for WorkspacePlanOutboxItemView {
    fn from(record: WorkspacePlanOutboxRecord) -> Self {
        let actions = super::plan_actions::outbox_actions(&record);
        Self {
            id: record.id,
            plan_id: record.plan_id,
            workspace_id: record.workspace_id,
            event_type: record.event_type,
            payload: record.payload_json,
            status: record.status.clone(),
            attempt_count: record.attempt_count,
            max_attempts: record.max_attempts,
            lease_owner: record.lease_owner,
            lease_expires_at: record.lease_expires_at.map(iso),
            last_error: record.last_error,
            next_attempt_at: record.next_attempt_at.map(iso),
            processed_at: record.processed_at.map(iso),
            metadata: record.metadata_json.clone(),
            created_at: iso(record.created_at),
            updated_at: record.updated_at.map(iso),
            actions,
        }
    }
}

impl From<WorkspacePlanEventRecord> for WorkspacePlanEventView {
    fn from(record: WorkspacePlanEventRecord) -> Self {
        Self {
            id: record.id,
            plan_id: record.plan_id,
            workspace_id: record.workspace_id,
            node_id: record.node_id,
            attempt_id: record.attempt_id,
            event_type: record.event_type,
            source: record.source,
            actor_id: record.actor_id,
            payload: record.payload_json,
            created_at: iso(record.created_at),
        }
    }
}
