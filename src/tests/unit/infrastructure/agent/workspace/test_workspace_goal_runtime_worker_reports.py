from src.infrastructure.agent.workspace.workspace_goal_runtime import (
    _is_stale_terminal_worker_report,
)
from src.infrastructure.agent.workspace.workspace_metadata_keys import CURRENT_ATTEMPT_ID


def test_stale_terminal_worker_report_detects_superseded_attempt() -> None:
    assert _is_stale_terminal_worker_report(
        task_metadata={CURRENT_ATTEMPT_ID: "attempt-new"},
        attempt_id="attempt-old",
        report_type="completed",
    )


def test_running_worker_report_is_not_stale_even_when_attempt_differs() -> None:
    assert not _is_stale_terminal_worker_report(
        task_metadata={CURRENT_ATTEMPT_ID: "attempt-new"},
        attempt_id="attempt-old",
        report_type="progress",
    )


def test_current_terminal_worker_report_is_not_stale() -> None:
    assert not _is_stale_terminal_worker_report(
        task_metadata={CURRENT_ATTEMPT_ID: "attempt-current"},
        attempt_id="attempt-current",
        report_type="completed",
    )
