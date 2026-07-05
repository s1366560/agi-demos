use super::*;

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
