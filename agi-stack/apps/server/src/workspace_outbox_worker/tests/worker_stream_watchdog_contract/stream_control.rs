use super::*;

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
