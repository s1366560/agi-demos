use super::*;

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
