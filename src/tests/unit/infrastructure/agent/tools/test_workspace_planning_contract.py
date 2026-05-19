"""Unit tests for the workspace planner contract terminal tool."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.models import (
    Project as DBProject,
    Tenant as DBTenant,
    User as DBUser,
    WorkspaceModel,
)
from src.infrastructure.agent.sisyphus.builtin_agent import BUILTIN_WORKSPACE_PLANNER_ID
from src.infrastructure.agent.tools import workspace_planning_contract as planning_contract
from src.infrastructure.agent.tools.context import ToolContext

pytestmark = pytest.mark.unit


def _ctx(*, selected_agent_id: str = BUILTIN_WORKSPACE_PLANNER_ID) -> ToolContext:
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
            "workspace_session_role": "worker",
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


async def _seed_workspace(db_session: AsyncSession) -> None:
    db_session.add_all(
        [
            DBUser(
                id="user-1",
                email="planner-user@example.com",
                full_name="Planner User",
                hashed_password="hash",
                is_active=True,
            ),
            DBTenant(
                id="tenant-1",
                name="Tenant",
                slug="tenant",
                description="",
                owner_id="user-1",
                plan="free",
                max_projects=10,
                max_users=10,
                max_storage=1,
            ),
            DBProject(
                id="project-1",
                tenant_id="tenant-1",
                name="Project",
                description="",
                owner_id="user-1",
                memory_rules={},
                graph_config={},
                sandbox_type="cloud",
                sandbox_config={},
                is_public=False,
            ),
            WorkspaceModel(
                id="ws-planner-1",
                tenant_id="tenant-1",
                project_id="project-1",
                name="Planner Workspace",
                description="",
                created_by="user-1",
                is_archived=False,
                metadata_json={},
            ),
        ]
    )
    await db_session.flush()


def _patch_session_factory(db_session: AsyncSession):
    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        yield db_session

    return patch.object(planning_contract, "async_session_factory", factory)


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


async def test_valid_delivery_contract_persists_metadata_and_publishes(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_workspace(db_session)
    publish = AsyncMock()
    monkeypatch.setattr(planning_contract, "_publish_workspace_updated_event", publish)

    with _patch_session_factory(db_session):
        result = await planning_contract.workspace_submit_planning_contract_tool.execute(
            _ctx(),
            task_graph=_task_graph(),
            delivery_cicd=_delivery_cicd(),
            reasoning="Read package.json and route definitions.",
            evidence_refs=["read:package.json", "grep:health route"],
            confidence=0.93,
        )

    assert result.is_error is False
    workspace = await db_session.get(WorkspaceModel, "ws-planner-1")
    assert workspace is not None
    delivery = dict((workspace.metadata_json or {}).get("delivery_cicd") or {})
    assert delivery["contract_source"] == "planner_agent_code_analysis"
    assert delivery["contract_confidence"] == 0.93
    assert delivery["services"][0]["service_id"] == "frontend"
    publish.assert_awaited_once()


async def test_planner_contract_preserves_existing_drone_provider_config(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_workspace(db_session)
    workspace = await db_session.get(WorkspaceModel, "ws-planner-1")
    assert workspace is not None
    workspace.metadata_json = {
        "delivery_cicd": {
            "provider": "drone",
            "code_root": "/workspace/app",
            "auto_deploy": True,
            "drone": {
                "repo": "memstack/demo",
                "branch": "main",
                "server_url_env": "DRONE_SERVER_URL",
                "token_env": "DRONE_TOKEN",
            },
        }
    }
    await db_session.flush()
    monkeypatch.setattr(planning_contract, "_publish_workspace_updated_event", AsyncMock())

    with _patch_session_factory(db_session):
        result = await planning_contract.workspace_submit_planning_contract_tool.execute(
            _ctx(),
            task_graph=_task_graph(),
            delivery_cicd={
                "provider": "drone",
                "auto_deploy": True,
                "services": _delivery_cicd()["services"],
            },
            reasoning="Read package.json and existing deployment config.",
            evidence_refs=["read:package.json", "workspace_metadata.delivery_cicd:drone"],
            confidence=0.88,
        )

    assert result.is_error is False
    workspace = await db_session.get(WorkspaceModel, "ws-planner-1")
    assert workspace is not None
    delivery = dict((workspace.metadata_json or {}).get("delivery_cicd") or {})
    assert delivery["provider"] == "drone"
    assert delivery["contract_source"] == "planner_agent_code_analysis"
    assert delivery["services"][0]["service_id"] == "frontend"
    assert delivery["drone"] == {
        "repo": "memstack/demo",
        "branch": "main",
        "server_url_env": "DRONE_SERVER_URL",
        "token_env": "DRONE_TOKEN",
    }


async def test_planner_contract_cannot_downgrade_existing_drone_docker_deploy_to_cli(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_workspace(db_session)
    workspace = await db_session.get(WorkspaceModel, "ws-planner-1")
    assert workspace is not None
    workspace.metadata_json = {
        "delivery_cicd": {
            "provider": "drone",
            "code_root": "/workspace/my-evo",
            "auto_deploy": True,
            "drone": {
                "repo": "s1366560/my-evo",
                "branch": "main",
                "deploy": {
                    "enabled": True,
                    "mode": "docker",
                    "stage": "deploy",
                    "docker": {
                        "image": "localhost:5001/my-evo",
                        "registry": "localhost:5001",
                        "tags": ["drone-docker-e2e"],
                    },
                },
            },
        }
    }
    await db_session.flush()
    monkeypatch.setattr(planning_contract, "_publish_workspace_updated_event", AsyncMock())

    with _patch_session_factory(db_session):
        result = await planning_contract.workspace_submit_planning_contract_tool.execute(
            _ctx(),
            task_graph=_task_graph(),
            delivery_cicd={
                "provider": "sandbox_native",
                "auto_deploy": True,
                "services": _delivery_cicd()["services"],
                "drone": {
                    "poll_interval_seconds": 10,
                    "deploy": {
                        "enabled": True,
                        "mode": "cli",
                        "stage": "deploy",
                        "cli": {
                            "image": "alpine:3.20",
                            "commands": ["echo smoke"],
                        },
                    },
                },
            },
            reasoning="Read package.json and inferred a generic CLI smoke deploy.",
            evidence_refs=["read:package.json", "workspace_metadata.delivery_cicd:drone"],
            confidence=0.84,
        )

    assert result.is_error is False
    workspace = await db_session.get(WorkspaceModel, "ws-planner-1")
    assert workspace is not None
    delivery = dict((workspace.metadata_json or {}).get("delivery_cicd") or {})
    assert delivery["provider"] == "drone"
    assert delivery["services"][0]["service_id"] == "frontend"
    drone = delivery["drone"]
    assert drone["poll_interval_seconds"] == 10
    assert drone["deploy"]["mode"] == "docker"
    assert drone["deploy"]["docker"]["image"] == "localhost:5001/my-evo"
    assert drone["deploy"]["cli"]["commands"] == ["echo smoke"]
