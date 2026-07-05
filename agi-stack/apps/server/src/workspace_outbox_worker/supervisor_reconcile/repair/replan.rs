use super::super::super::*;

pub(in crate::workspace_outbox_worker) fn supervisor_replan_metadata_present(
    metadata: &Map<String, Value>,
) -> bool {
    metadata_string(metadata.get("last_supervisor_decision_action")).as_deref()
        == Some(SUPERVISOR_DECISION_REPLAN_NODE_ACTION)
}

pub(in crate::workspace_outbox_worker) fn supervisor_replan_summary(
    metadata: &Map<String, Value>,
) -> String {
    metadata_string(metadata.get("last_supervisor_decision_rationale"))
        .or_else(|| metadata_string(metadata.get("last_verification_summary")))
        .or_else(|| metadata_string(metadata.get(LAST_WORKER_REPORT_SUMMARY)))
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "supervisor requested replan".to_string())
}

pub(in crate::workspace_outbox_worker) fn clear_supervisor_replan_node_metadata(
    metadata: &mut Map<String, Value>,
) {
    for key in [
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
        "retry_count",
        "retry_last_reason",
        "retry_not_before",
        "source_publish_branch",
        "source_publish_commit_ref",
        "source_publish_provider",
        "source_publish_reason",
        "source_publish_source_commit_ref",
        "source_publish_status",
        "source_publish_token_env",
        "terminal_attempt_reconciled_at",
        "terminal_attempt_retry_count",
        "terminal_attempt_retry_reason",
        "terminal_attempt_status",
        "terminal_attempt_superseded_attempt_id",
        "terminal_attempt_superseded_reason",
        "terminal_attempt_superseded_status",
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
    ] {
        metadata.remove(key);
    }
    clear_attempt_retry_worker_stream_state(metadata);
}
