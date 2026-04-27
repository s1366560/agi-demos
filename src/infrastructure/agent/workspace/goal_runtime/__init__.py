"""M8 — `workspace_goal_runtime` split into focused submodules.

The original ``workspace_goal_runtime.py`` was a 1446-line God module that
mixed six concerns. This package factors the leaf helpers out so each file
carries a single responsibility (<= 300 lines each):

* :mod:`activation`               — Agent-First gate: "should workspace authority run?"
* :mod:`root_selection`           — select an existing root task as candidate source
* :mod:`execution_state`          — build ``execution_state`` metadata dicts + task-id extraction
* :mod:`worker_report_parsing`    — normalize worker report payloads, fingerprint them, service factory
* :mod:`decomposition`            — delegate goal decomposition to task_decomposer (+ V2 bridge)
* :mod:`retry_scheduler`          — background retry attempt scheduling

The public API continues to live on ``workspace_goal_runtime`` (thin facade
that re-exports from here), so no call sites change.
"""

from src.infrastructure.agent.workspace.goal_runtime.activation import (
    _WORKSPACE_TASK_ID_PATTERN,
    TaskDecomposerProtocol,
    should_activate_workspace_authority,
)
from src.infrastructure.agent.workspace.goal_runtime.decomposition import _decompose_root_goal
from src.infrastructure.agent.workspace.goal_runtime.execution_state import (
    _build_execution_state,
    _extract_workspace_task_id,
)
from src.infrastructure.agent.workspace.goal_runtime.root_selection import (
    _select_existing_root_candidate,
)
from src.infrastructure.agent.workspace.goal_runtime.task_transitions import (
    MAX_AUTO_REPLAN_ATTEMPTS,
    WORKER_TERMINAL_REPORT_TYPES,
    ensure_execution_attempt,
    ensure_root_task_started,
)
from src.infrastructure.agent.workspace.goal_runtime.v2_bridge import (
    kickoff_v2_plan,
    reset_orchestrator_singleton_for_testing,
)
from src.infrastructure.agent.workspace.goal_runtime.worker_report_parsing import (
    _build_attempt_service,
    _build_worker_report_fingerprint,
    _parse_worker_report_payload,
)

__all__ = [
    "MAX_AUTO_REPLAN_ATTEMPTS",
    "WORKER_TERMINAL_REPORT_TYPES",
    "_WORKSPACE_TASK_ID_PATTERN",
    "TaskDecomposerProtocol",
    "_build_attempt_service",
    "_build_execution_state",
    "_build_worker_report_fingerprint",
    "_decompose_root_goal",
    "_extract_workspace_task_id",
    "_parse_worker_report_payload",
    "_select_existing_root_candidate",
    "ensure_execution_attempt",
    "ensure_root_task_started",
    "kickoff_v2_plan",
    "reset_orchestrator_singleton_for_testing",
    "should_activate_workspace_authority",
]
