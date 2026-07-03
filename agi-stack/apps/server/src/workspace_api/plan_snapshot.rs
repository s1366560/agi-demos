use super::*;

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

const ITERATION_PHASE_ORDER: [&str; 6] =
    ["research", "plan", "implement", "test", "deploy", "review"];

fn node_iteration_phase(node: &WorkspacePlanNodeRecord) -> String {
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

fn phase_contract_view(phase: &str) -> WorkspacePlanPhaseContractView {
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

fn iteration_summary_view(
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

fn delivery_summary_view(plan: &WorkspacePlanRecord) -> WorkspaceDeliverySummaryView {
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

fn plan_history_view(
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
        let actions = outbox_actions(&record);
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
