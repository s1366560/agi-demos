"""Smoke tests for :mod:`workspace_metadata_keys`.

These pin the string values — changing them silently would break compatibility
with persisted ``WorkspaceTask.metadata`` payloads.
"""

from __future__ import annotations

from src.infrastructure.agent.workspace import workspace_metadata_keys as mk


def test_key_values_are_stable() -> None:
    assert mk.ROOT_GOAL_TASK_ID == "root_goal_task_id"
    assert mk.TASK_ROLE == "task_role"
    assert mk.AUTONOMY_SCHEMA_VERSION_KEY == "autonomy_schema_version"
    assert mk.LINEAGE_SOURCE == "lineage_source"
    assert mk.DERIVED_FROM_INTERNAL_PLAN_STEP == "derived_from_internal_plan_step"
    assert mk.EXECUTION_STATE == "execution_state"
    assert mk.REMEDIATION_STATUS == "remediation_status"
    assert mk.CURRENT_ATTEMPT_ID == "current_attempt_id"
    assert mk.PENDING_LEADER_ADJUDICATION == "pending_leader_adjudication"
    assert mk.LAST_LEADER_ADJUDICATION_STATUS == "last_leader_adjudication_status"
    assert mk.LAST_WORKER_REPORT_SUMMARY == "last_worker_report_summary"


def test_all_exports_match_module_attrs() -> None:
    for name in mk.__all__:
        assert hasattr(mk, name), f"{name} listed in __all__ but not defined"
        assert isinstance(getattr(mk, name), str)
