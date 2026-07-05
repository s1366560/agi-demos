use super::*;

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
