use super::*;

#[test]
fn worker_conversation_id_matches_python_uuid5_contract() {
    assert_eq!(
        worker_conversation_id(
            "workspace-test",
            "agent-worker",
            "task-test",
            Some("attempt-test")
        ),
        "d267a78e-eefc-5d33-bfb3-ac4fa7ece855"
    );
}

#[test]
fn should_stop_orphaned_worker_stream_matches_python_contract() {
    let finished_without_stream =
        worker_stream_watchdog::should_stop(Some("msg-1"), None, true, 0.0, Some(900));
    assert!(finished_without_stream.should_stop);
    assert_eq!(
        finished_without_stream
            .reason
            .map(worker_stream_watchdog::StopReason::as_str),
        Some("agent_finished_without_terminal_event")
    );

    let finished_matching_stream =
        worker_stream_watchdog::should_stop(Some("msg-1"), Some("msg-1"), true, 0.0, Some(900));
    assert!(finished_matching_stream.should_stop);
    assert_eq!(
        finished_matching_stream
            .reason
            .map(worker_stream_watchdog::StopReason::as_str),
        Some("agent_finished_without_terminal_event")
    );

    let finished_for_other_message =
        worker_stream_watchdog::should_stop(Some("msg-2"), Some("msg-1"), true, 999.0, Some(900));
    assert!(!finished_for_other_message.should_stop);
    assert_eq!(finished_for_other_message.reason, None);

    let not_running_below_grace =
        worker_stream_watchdog::should_stop(None, Some("msg-1"), false, 899.0, Some(900));
    assert!(!not_running_below_grace.should_stop);
    assert_eq!(not_running_below_grace.reason, None);

    let not_running_at_grace =
        worker_stream_watchdog::should_stop(None, Some("msg-1"), false, 900.0, Some(900));
    assert!(not_running_at_grace.should_stop);
    assert_eq!(
        not_running_at_grace
            .reason
            .map(worker_stream_watchdog::StopReason::as_str),
        Some("agent_not_running_stream_idle")
    );

    let running_over_grace =
        worker_stream_watchdog::should_stop(None, Some("msg-1"), true, 1200.0, Some(900));
    assert!(!running_over_grace.should_stop);
    assert_eq!(running_over_grace.reason, None);

    let clamped_grace = worker_stream_watchdog::should_stop(None, None, false, 1.0, Some(0));
    assert!(clamped_grace.should_stop);
    assert_eq!(
        clamped_grace
            .reason
            .map(worker_stream_watchdog::StopReason::as_str),
        Some("agent_not_running_stream_idle")
    );

    let empty_finished_marker =
        worker_stream_watchdog::should_stop(Some(""), None, false, 0.5, Some(1));
    assert!(!empty_finished_marker.should_stop);
    assert_eq!(empty_finished_marker.reason, None);
}

#[test]
fn worker_stream_watchdog_extracts_message_id_like_python() {
    assert_eq!(
        worker_stream_watchdog::message_id_from_event(&json!({
            "type": "message",
            "data": {"id": "msg-primary", "message_id": "msg-secondary"}
        })),
        Some("msg-primary")
    );
    assert_eq!(
        worker_stream_watchdog::message_id_from_event(&json!({
            "type": "message",
            "data": {"message_id": "msg-secondary"}
        })),
        Some("msg-secondary")
    );
    assert_eq!(
        worker_stream_watchdog::message_id_from_event(&json!({
            "type": "message",
            "data": {"id": ""}
        })),
        None
    );
    assert_eq!(
        worker_stream_watchdog::message_id_from_event(&json!({
            "type": "text_delta",
            "data": {"id": "msg-ignored"}
        })),
        None
    );
    assert_eq!(
        worker_stream_watchdog::message_id_from_event(&json!({
            "type": "message",
            "data": []
        })),
        None
    );
}

#[test]
fn worker_stream_watchdog_idle_progress_matches_python_contract() {
    assert!(!worker_stream_watchdog::should_publish_idle_progress(
        59.9,
        0.0,
        100.0,
        Some(60)
    ));
    assert!(worker_stream_watchdog::should_publish_idle_progress(
        60.0,
        0.0,
        100.0,
        Some(60)
    ));
    assert!(!worker_stream_watchdog::should_publish_idle_progress(
        120.0,
        90.0,
        149.9,
        Some(60)
    ));
    assert!(worker_stream_watchdog::should_publish_idle_progress(
        120.0,
        90.0,
        150.0,
        Some(60)
    ));
    assert!(worker_stream_watchdog::should_publish_idle_progress(
        1.0,
        0.0,
        1.0,
        Some(0)
    ));

    assert_eq!(
            worker_stream_watchdog::idle_progress_summary(61.9, Some("observe"), true, None),
            "Worker stream still active; no new visible stream event for 61s; agent:running present; last_event=observe"
        );
    assert_eq!(
            worker_stream_watchdog::idle_progress_summary(
                900.0,
                Some(""),
                false,
                Some("msg-1")
            ),
            "Worker stream still active; no new visible stream event for 900s; agent:running missing; agent:finished=msg-1"
        );
}

#[test]
fn worker_stream_watchdog_launch_started_summary_matches_python_contract() {
    assert_eq!(
            worker_stream_watchdog::worker_launch_started_summary(
                Some("9"),
                Some(
                    "verification failed:\n  - clean_worktree_after_commit: ?? .playwright-cache/; ?? logs/"
                ),
            ),
            "Worker attempt #9 started from verifier feedback: verification failed: - clean_worktree_after_commit: ?? .playwright-cache/; ?? logs/"
        );
    assert_eq!(
        worker_stream_watchdog::worker_launch_started_summary(None, None),
        "Worker attempt started; session is bound and streaming."
    );
    let long_feedback = "x".repeat(WORKER_LAUNCH_PROGRESS_SUMMARY_CHARS + 50);
    let summary =
        worker_stream_watchdog::worker_launch_started_summary(Some("10"), Some(&long_feedback));
    assert!(summary.starts_with("Worker attempt #10 started from verifier feedback: "));
    assert!(summary.ends_with("..."));
    assert!(summary.len() < WORKER_LAUNCH_PROGRESS_SUMMARY_CHARS + 80);

    let unicode_feedback = "验".repeat(WORKER_LAUNCH_PROGRESS_SUMMARY_CHARS + 1);
    let unicode_summary =
        worker_stream_watchdog::worker_launch_started_summary(Some("11"), Some(&unicode_feedback));
    assert!(unicode_summary.ends_with("..."));
}

#[test]
fn worker_stream_watchdog_completion_summary_matches_python_contract() {
    assert_eq!(
        worker_stream_watchdog::stream_completion_summary("Finished the implementation.", ""),
        "Finished the implementation."
    );
    assert_eq!(
        worker_stream_watchdog::stream_completion_summary("", ""),
        "Worker stream completed without an explicit workspace terminal report."
    );
    let accumulated = "x".repeat(2500);
    let summary = worker_stream_watchdog::stream_completion_summary("", &accumulated);
    assert_eq!(summary.len(), WORKER_STREAM_COMPLETION_SUMMARY_CHARS);
    assert!(summary.ends_with("..."));

    let unicode_accumulated = "完".repeat(WORKER_STREAM_COMPLETION_SUMMARY_CHARS + 1);
    let unicode_summary =
        worker_stream_watchdog::stream_completion_summary("", &unicode_accumulated);
    assert_eq!(
        unicode_summary.chars().count(),
        WORKER_STREAM_COMPLETION_SUMMARY_CHARS
    );
    assert!(unicode_summary.ends_with("..."));
}

#[test]
fn worker_stream_watchdog_terminal_report_observations_match_python_contract() {
    let denied = json!({
        "type": "observe",
        "data": {
            "tool_name": "workspace_report_complete",
            "result": "{\"error\": \"completion denied: protected test/review node includes failed evidence\"}",
            "error": null
        }
    });
    assert_eq!(
        worker_stream_watchdog::terminal_report_tool_observation_status(&denied)
            .map(worker_stream_watchdog::TerminalReportToolStatus::as_str),
        Some("denied")
    );
    assert!(!worker_stream_watchdog::should_synthesize_stream_completion_report(true));

    let applied = json!({
        "type": "observe",
        "data": {
            "tool_name": "workspace_report_blocked",
            "result": "{\"applied_report\": {\"applied\": true}}",
            "error": null
        }
    });
    assert_eq!(
        worker_stream_watchdog::terminal_report_tool_observation_status(&applied)
            .map(worker_stream_watchdog::TerminalReportToolStatus::as_str),
        Some("applied")
    );
    assert_eq!(
        worker_stream_watchdog::terminal_report_tool_report_type(&applied)
            .map(worker_stream_watchdog::TerminalReportType::as_str),
        Some("blocked")
    );

    let supervisor_only = json!({
        "type": "observe",
        "data": {
            "tool_name": "workspace_report_complete",
            "result": "{\"ok\": true, \"applied_report\": {\"skipped_supervisor_only\": true, \"reason\": \"WORKSPACE_WTP_V1_ONLY\"}}",
            "error": null
        }
    });
    assert_eq!(
        worker_stream_watchdog::terminal_report_tool_observation_status(&supervisor_only)
            .map(worker_stream_watchdog::TerminalReportToolStatus::as_str),
        Some("attempted")
    );

    let non_terminal_tool = json!({
        "type": "observe",
        "data": {"tool_name": "bash", "result": "done", "error": null}
    });
    assert_eq!(
        worker_stream_watchdog::terminal_report_tool_observation_status(&non_terminal_tool),
        None
    );
    assert!(worker_stream_watchdog::should_synthesize_stream_completion_report(false));
}

#[test]
fn worker_stream_watchdog_terminal_report_metadata_matches_python_contract() {
    let metadata = json!({
        "last_worker_report_attempt_id": "attempt-1",
        "last_worker_report_type": "completed"
    });
    assert!(
        worker_stream_watchdog::terminal_report_metadata_matches_attempt(
            Some(&metadata),
            Some("attempt-1"),
            Some("completed")
        )
    );
    assert!(
        !worker_stream_watchdog::terminal_report_metadata_matches_attempt(
            Some(&metadata),
            Some("attempt-2"),
            Some("completed")
        )
    );
    assert!(
        !worker_stream_watchdog::terminal_report_metadata_matches_attempt(
            Some(&metadata),
            Some("attempt-1"),
            Some("blocked")
        )
    );
    assert!(worker_stream_watchdog::should_reconcile_terminal_report_tool(true, false));
    assert!(!worker_stream_watchdog::should_reconcile_terminal_report_tool(true, true));
    assert!(!worker_stream_watchdog::should_reconcile_terminal_report_tool(false, false));
}

#[test]
fn worker_stream_watchdog_reduces_text_then_complete_like_python_stream_loop() {
    let mut state = worker_stream_watchdog::StreamState::default();
    assert_eq!(
        state.observe_event(&json!({
            "type": "message",
            "data": {"id": "msg-1"}
        })),
        None
    );
    assert_eq!(state.stream_message_id.as_deref(), Some("msg-1"));
    assert_eq!(
        state.observe_event(&json!({
            "type": "text_delta",
            "data": {"text": "Finished "}
        })),
        None
    );
    assert_eq!(
        state.observe_event(&json!({
            "type": "text_delta",
            "data": {"text": "implementation."}
        })),
        None
    );
    assert_eq!(
        state.observe_event(&json!({
            "type": "complete",
            "data": {"content": ""}
        })),
        Some(worker_stream_watchdog::StreamTerminalEvent::Complete)
    );
    assert_eq!(state.final_content, "Finished implementation.");
    assert_eq!(state.last_stream_event_type.as_deref(), Some("complete"));

    let outcome = state.terminal_outcome(false);
    assert_eq!(outcome.outcome_reason, "completed");
    assert_eq!(outcome.launch_state, "completed_via_stream");
    assert_eq!(
        outcome
            .report_type
            .map(worker_stream_watchdog::TerminalReportType::as_str),
        Some("completed")
    );
    assert_eq!(outcome.summary, "Finished implementation.");
    assert!(outcome.should_report);
    assert!(!outcome.should_reconcile);
}

#[test]
fn worker_stream_watchdog_terminal_tool_outcomes_match_python_stream_loop() {
    let mut denied = worker_stream_watchdog::StreamState::default();
    denied.observe_event(&json!({
        "type": "observe",
        "data": {
            "tool_name": "workspace_report_complete",
            "result": "{\"error\": \"completion denied: failed tests\"}",
            "error": null
        }
    }));
    denied.observe_event(&json!({
        "type": "complete",
        "data": {"content": "ignored fallback"}
    }));
    let denied_outcome = denied.terminal_outcome(false);
    assert_eq!(denied_outcome.outcome_reason, "terminal_report_tool_denied");
    assert_eq!(denied_outcome.launch_state, "terminal_report_tool_denied");
    assert!(!denied_outcome.should_report);

    let mut applied = worker_stream_watchdog::StreamState::default();
    applied.observe_event(&json!({
        "type": "observe",
        "data": {
            "tool_name": "workspace_report_blocked",
            "result": "{\"applied_report\": {\"applied\": true}}",
            "error": null
        }
    }));
    applied.observe_event(&json!({
        "type": "complete",
        "data": {"content": "blocked summary"}
    }));
    let reconcile = applied.terminal_outcome(false);
    assert_eq!(reconcile.outcome_reason, "terminal_report_tool_reconciled");
    assert_eq!(reconcile.launch_state, "terminal_report_tool_reconciled");
    assert_eq!(
        reconcile
            .report_type
            .map(worker_stream_watchdog::TerminalReportType::as_str),
        Some("blocked")
    );
    assert!(reconcile.should_report);
    assert!(reconcile.should_reconcile);

    let already_recorded = applied.terminal_outcome(true);
    assert_eq!(
        already_recorded.outcome_reason,
        "terminal_report_tool_applied"
    );
    assert!(!already_recorded.should_report);
}

#[test]
fn worker_stream_watchdog_error_and_missing_terminal_outcomes_match_python_loop() {
    let mut error = worker_stream_watchdog::StreamState::default();
    assert_eq!(
        error.observe_event(&json!({
            "type": "error",
            "data": {"message": "worker failed"}
        })),
        Some(worker_stream_watchdog::StreamTerminalEvent::Error)
    );
    let error_outcome = error.terminal_outcome(false);
    assert_eq!(error_outcome.outcome_reason, "blocked");
    assert_eq!(error_outcome.launch_state, "blocked");
    assert_eq!(
        error_outcome
            .report_type
            .map(worker_stream_watchdog::TerminalReportType::as_str),
        Some("blocked")
    );
    assert_eq!(error_outcome.summary, "worker failed");
    assert!(error_outcome.should_report);

    let mut ended = worker_stream_watchdog::StreamState::default();
    ended.mark_stream_ended_without_terminal();
    let ended_outcome = ended.terminal_outcome(false);
    assert_eq!(ended_outcome.outcome_reason, "no_terminal_event");
    assert_eq!(
        ended_outcome.summary,
        "Worker stream ended without a terminal complete/error event."
    );
    assert!(ended_outcome.should_report);

    let mut orphan = worker_stream_watchdog::StreamState::default();
    orphan.mark_orphaned_stream_stop(Some("agent_not_running_stream_idle"));
    let orphan_outcome = orphan.terminal_outcome(false);
    assert_eq!(orphan_outcome.outcome_reason, "no_terminal_event");
    assert_eq!(
            orphan_outcome.summary,
            "Worker stream stopped without a terminal complete/error event (agent_not_running_stream_idle)."
        );
}
