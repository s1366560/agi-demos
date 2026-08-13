"""Unit tests for the workspace planner contract terminal tool."""

from __future__ import annotations

import json

import pytest

from src.infrastructure.agent.sisyphus.builtin_agent import BUILTIN_WORKSPACE_PLANNER_ID
from src.infrastructure.agent.tools import workspace_planning_contract as planning_contract
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.workspace.runtime_role_contract import (
    WORKSPACE_ROLE_CONTRACT,
    WORKSPACE_ROLE_WORKER,
)

pytestmark = pytest.mark.unit


def _ctx(
    *,
    selected_agent_id: str = BUILTIN_WORKSPACE_PLANNER_ID,
    workspace_session_role: str = WORKSPACE_ROLE_CONTRACT,
) -> ToolContext:
    return ToolContext(
        session_id="planner-session",
        message_id="msg-1",
        call_id="call-1",
        agent_name="workspace-planner",
        conversation_id="conv-1",
        project_id="project-1",
        tenant_id="tenant-1",
        user_id="user-1",
        runtime_context={
            "selected_agent_id": selected_agent_id,
            "workspace_id": "ws-planner-1",
            "workspace_session_role": workspace_session_role,
            "user_id": "user-1",
        },
    )


def _task_graph() -> dict[str, object]:
    return {
        "subtasks": [
            {"id": "frontend", "description": "Implement frontend", "priority": 10},
            {
                "id": "backend",
                "description": "Implement backend",
                "depends_on": ["frontend"],
                "priority": 5,
            },
        ]
    }


def _delivery_cicd(*, port: int = 5173) -> dict[str, object]:
    return {
        "auto_deploy": True,
        "services": [
            {
                "service_id": "frontend",
                "name": "Frontend",
                "start_command": "npm run dev -- --host 0.0.0.0 --port 5173",
                "internal_port": port,
                "health_path": "/",
                "required": True,
                "auto_open": True,
            }
        ],
    }


async def test_non_planner_runtime_call_is_rejected() -> None:
    result = await planning_contract.workspace_submit_planning_contract_tool.execute(
        _ctx(selected_agent_id="worker-agent"),
        task_graph=_task_graph(),
        delivery_cicd=_delivery_cicd(),
        reasoning="Read code evidence.",
        evidence_refs=["read:package.json"],
        confidence=0.9,
    )

    assert result.is_error is True
    assert "builtin:workspace-planner" in json.loads(result.output)["error"]


async def test_legacy_worker_runtime_call_is_rejected() -> None:
    result = await planning_contract.workspace_submit_planning_contract_tool.execute(
        _ctx(workspace_session_role=WORKSPACE_ROLE_WORKER),
        task_graph=_task_graph(),
        delivery_cicd=_delivery_cicd(),
        reasoning="Read code evidence.",
        evidence_refs=["read:package.json"],
        confidence=0.9,
    )

    assert result.is_error is True
    assert "workspace contract session" in json.loads(result.output)["error"]


async def test_missing_evidence_is_rejected() -> None:
    result = await planning_contract.workspace_submit_planning_contract_tool.execute(
        _ctx(),
        task_graph=_task_graph(),
        delivery_cicd=_delivery_cicd(),
        reasoning="Read code evidence.",
        evidence_refs=[],
        confidence=0.9,
    )

    assert result.is_error is True
    assert "evidence_ref" in json.loads(result.output)["error"]


async def test_invalid_service_port_is_rejected() -> None:
    result = await planning_contract.workspace_submit_planning_contract_tool.execute(
        _ctx(),
        task_graph=_task_graph(),
        delivery_cicd=_delivery_cicd(port=70000),
        reasoning="Read code evidence.",
        evidence_refs=["read:package.json"],
        confidence=0.9,
    )

    assert result.is_error is True
    assert "internal_port" in json.loads(result.output)["error"]


async def test_valid_delivery_contract_is_captured_without_platform_mutation() -> None:
    result = await planning_contract.workspace_submit_planning_contract_tool.execute(
        _ctx(),
        task_graph=_task_graph(),
        delivery_cicd=_delivery_cicd(),
        reasoning="Read package.json and route definitions.",
        evidence_refs=["read:package.json", "grep:health route"],
        confidence=0.93,
    )

    assert result.is_error is False
    output = json.loads(result.output)
    payload = result.metadata["planning_contract"]
    delivery = payload["delivery_cicd"]
    assert output["captured"] is True
    assert output["metadata_written"] is False
    assert payload["metadata_written"] is False
    assert delivery["contract_source"] == "planner_agent_code_analysis"
    assert delivery["contract_confidence"] == 0.93
    assert delivery["services"][0]["service_id"] == "frontend"


async def test_capture_does_not_use_a_supplied_legacy_session() -> None:
    class _ExplodingSession:
        def __getattr__(self, name: str) -> object:
            raise AssertionError(f"legacy session accessed: {name}")

    payload = await planning_contract.persist_workspace_planning_contract(
        workspace_id="ws-planner-1",
        task_graph=_task_graph(),
        delivery_cicd=_delivery_cicd(),
        reasoning="Read package.json and route definitions.",
        evidence_refs=["read:package.json"],
        confidence=0.91,
        session=_ExplodingSession(),  # type: ignore[arg-type]
        commit=True,
        publish=True,
    )

    assert payload["metadata_written"] is False
    assert payload["delivery_cicd"]["services"][0]["service_id"] == "frontend"
