use super::*;

pub(in crate::workspace_api) const OPERATOR_CLEARED_RETRY_KEYS: &[&str] = &[
    "retry_count",
    "retry_last_reason",
    "retry_not_before",
    "terminal_attempt_retry_count",
    "terminal_attempt_retry_reason",
    "terminal_attempt_reconciled_at",
    "terminal_attempt_status",
    "terminal_attempt_superseded_attempt_id",
    "terminal_attempt_superseded_reason",
    "terminal_attempt_superseded_status",
];

pub(in crate::workspace_api) const OPERATOR_CLEARED_ATTEMPT_KEYS: &[&str] = &[
    "candidate_artifacts",
    "candidate_verifications",
    "deploy_mode",
    "deployment_status",
    "evidence_refs",
    "execution_verifications",
    "external_id",
    "external_provider",
    "external_url",
    "current_repair_turn",
    "last_verification_attempt_id",
    "last_verification_feedback_items",
    "last_verification_hard_fail",
    "last_verification_judge_confidence",
    "last_verification_judge_failed_criteria",
    "last_verification_judge_next_action_kind",
    "last_verification_judge_rationale",
    "last_verification_judge_repair_brief",
    "last_verification_judge_required_next_action",
    "last_verification_judge_verdict",
    "last_verification_passed",
    "last_verification_ran_at",
    "last_verification_summary",
    "last_worker_report_attempt_id",
    "last_worker_report_artifacts",
    "last_worker_report_summary",
    "last_worker_report_type",
    "last_worker_report_verifications",
    "obsolete_by_verifier_feedback",
    "obsolete_feedback_items",
    "pipeline_evidence_refs",
    "pipeline_finished_at",
    "pipeline_gate_status",
    "pipeline_last_summary",
    "pipeline_request_count",
    "pipeline_requested_at",
    "pipeline_run_id",
    "pipeline_status",
    "reported_attempt_reconciled_at",
    "reported_attempt_status",
    "source_publish_branch",
    "source_publish_commit_ref",
    "source_publish_provider",
    "source_publish_reason",
    "source_publish_source_commit_ref",
    "source_publish_status",
    "source_publish_token_env",
    "verification_evidence_refs",
    "verification_feedback_disposition",
    "verified_commit_ref",
    "verified_git_diff_summary",
    "verified_test_commands",
    "worktree_integration_attempt_id",
    "worktree_integration_commit_ref",
    "worktree_integration_dirty_signature",
    "worktree_integration_ran_at",
    "worktree_integration_status",
    "worktree_integration_summary",
    "worktree_integration_worktree_path",
];

pub(in crate::workspace_api) const BLOCKED_FILE_SEGMENTS: &[&str] = &[
    "credentials",
    "node_modules",
    ".env",
    "__pycache__",
    ".git",
    ".svn",
    ".hg",
];
pub(in crate::workspace_api) const MAX_FILE_SIZE: usize = 100 * 1024 * 1024;
pub(in crate::workspace_api) const MAX_COPY_ENTRIES: usize = 500;
/// How many file copies run concurrently inside one directory copy (each
/// copy is an object-store get+put plus a DB row).
pub(in crate::workspace_api) const COPY_FANOUT_CONCURRENCY: usize = 4;

pub(in crate::workspace_api) fn compose_workspace_metadata(body: WorkspaceCreatePayload) -> Value {
    let mut metadata = object_or_empty(body.metadata);
    let use_case = body.use_case.unwrap_or_else(|| {
        metadata
            .get("workspace_use_case")
            .and_then(|value| value.as_str())
            .unwrap_or("general")
            .to_string()
    });
    let workspace_type = match use_case.as_str() {
        "programming" => "software_development",
        "research" => "research",
        "operations" => "operations",
        _ => "general",
    };
    let collaboration_mode = body.collaboration_mode.unwrap_or_else(|| {
        metadata
            .get("collaboration_mode")
            .and_then(|value| value.as_str())
            .unwrap_or("single_agent")
            .to_string()
    });
    metadata["workspace_use_case"] = json!(use_case);
    metadata["workspace_type"] = json!(workspace_type);
    metadata["collaboration_mode"] = json!(collaboration_mode);
    metadata["agent_conversation_mode"] = json!(collaboration_mode);
    let mut profile = object_or_empty(body.autonomy_profile.unwrap_or_else(|| json!({})));
    profile["workspace_type"] = json!(workspace_type);
    metadata["autonomy_profile"] = profile;
    if let Some(root) = body
        .sandbox_code_root
        .filter(|value| !value.trim().is_empty())
    {
        metadata["sandbox_code_root"] = json!(root);
    }
    metadata
}

pub(in crate::workspace_api) fn apply_task_update(
    task: &mut WorkspaceTaskRecord,
    body: WorkspaceTaskUpdatePayload,
) -> Result<(), WorkspaceApiError> {
    if let Some(title) = body.title {
        validate_non_empty(&title, "title")?;
        task.title = title;
    }
    if body.description.is_some() {
        task.description = body.description;
    }
    if body.assignee_user_id.is_some() {
        task.assignee_user_id = body.assignee_user_id;
    }
    if let Some(status) = body.status {
        validate_task_status(&status)?;
        task.status = status;
        task.completed_at = if task.status == "done" {
            Some(Utc::now())
        } else {
            None
        };
    }
    if let Some(metadata) = body.metadata {
        task.metadata_json = object_or_empty(metadata);
    }
    if let Some(priority) = body.priority {
        task.priority = priority_rank(Some(&priority))?;
    }
    if body.estimated_effort.is_some() {
        task.estimated_effort = body.estimated_effort;
    }
    if body.blocker_reason.is_some() {
        task.blocker_reason = body.blocker_reason;
    }
    task.updated_at = Some(Utc::now());
    Ok(())
}

pub(in crate::workspace_api) fn apply_task_transition(
    task: &mut WorkspaceTaskRecord,
    action: TaskTransitionAction,
    user_id: &str,
) {
    match action {
        TaskTransitionAction::Claim => task.assignee_user_id = Some(user_id.to_string()),
        TaskTransitionAction::Start => task.status = "in_progress".to_string(),
        TaskTransitionAction::Block => task.status = "blocked".to_string(),
        TaskTransitionAction::Complete => {
            task.status = "done".to_string();
            task.completed_at = Some(Utc::now());
        }
        TaskTransitionAction::UnassignAgent => {
            task.assignee_agent_id = None;
            if let Some(obj) = task.metadata_json.as_object_mut() {
                obj.remove("workspace_agent_binding_id");
            }
        }
    }
    task.updated_at = Some(Utc::now());
}

pub(in crate::workspace_api) fn validate_non_empty(
    value: &str,
    field: &str,
) -> Result<(), WorkspaceApiError> {
    if value.trim().is_empty() {
        return Err(WorkspaceApiError::bad_request(format!(
            "{field} cannot be empty"
        )));
    }
    Ok(())
}

pub(in crate::workspace_api) fn validate_task_status(value: &str) -> Result<(), WorkspaceApiError> {
    match value {
        "todo" | "in_progress" | "blocked" | "done" | "dispatched" | "executing" | "reported"
        | "adjudicating" => Ok(()),
        _ => Err(WorkspaceApiError::bad_request("Invalid task status")),
    }
}

pub(in crate::workspace_api) fn validate_node_type(value: &str) -> Result<(), WorkspaceApiError> {
    match value {
        "user" | "agent" | "task" | "note" | "corridor" | "human_seat" | "objective" => Ok(()),
        _ => Err(WorkspaceApiError::bad_request("Invalid topology request")),
    }
}

pub(in crate::workspace_api) fn validate_post_status(value: &str) -> Result<(), WorkspaceApiError> {
    match value {
        "open" | "archived" => Ok(()),
        _ => Err(WorkspaceApiError::bad_request("Invalid blackboard request")),
    }
}

pub(in crate::workspace_api) fn priority_rank(
    value: Option<&str>,
) -> Result<i32, WorkspaceApiError> {
    match value.unwrap_or("") {
        "" => Ok(0),
        "P1" => Ok(1),
        "P2" => Ok(2),
        "P3" => Ok(3),
        "P4" => Ok(4),
        _ => Err(WorkspaceApiError::bad_request("Invalid task priority")),
    }
}

pub(in crate::workspace_api) fn clamp_limit(limit: Option<i64>, default: i64, max: i64) -> i64 {
    limit.unwrap_or(default).clamp(1, max)
}
