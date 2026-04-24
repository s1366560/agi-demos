from __future__ import annotations

import pytest

from src.application.services.workspace_agent_autonomy import validate_autonomy_metadata


@pytest.mark.unit
def test_execution_task_metadata_accepts_delegation_binding_fields() -> None:
    metadata = validate_autonomy_metadata(
        {
            "autonomy_schema_version": 1,
            "task_role": "execution_task",
            "root_goal_task_id": "root-1",
            "lineage_source": "agent",
            "delegated_subagent_name": "worker-subagent",
            "delegated_subagent_id": "sa-1",
            "delegated_task_text": "Implement the bounded task",
        }
    )

    assert metadata["delegated_subagent_name"] == "worker-subagent"
    assert metadata["delegated_subagent_id"] == "sa-1"
    assert metadata["delegated_task_text"] == "Implement the bounded task"
