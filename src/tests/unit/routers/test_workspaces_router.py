"""Unit tests for workspace lifecycle/member/agent router."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI, status
from fastapi.testclient import TestClient

from src.domain.model.workspace.workspace import Workspace
from src.domain.model.workspace.workspace_agent import WorkspaceAgent
from src.domain.model.workspace.workspace_member import WorkspaceMember
from src.domain.model.workspace.workspace_role import WorkspaceRole


def _make_workspace(workspace_id: str = "ws-1") -> Workspace:
    return Workspace(
        id=workspace_id,
        tenant_id="tenant-1",
        project_id="project-1",
        name="Team Workspace",
        created_by="user-1",
        description="Workspace description",
        metadata={"source": "test"},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_member(
    user_id: str = "user-2", role: WorkspaceRole = WorkspaceRole.EDITOR
) -> WorkspaceMember:
    return WorkspaceMember(
        id=f"wm-{user_id}",
        workspace_id="ws-1",
        user_id=user_id,
        role=role,
        invited_by="user-1",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_workspace_agent(binding_id: str = "wa-1") -> WorkspaceAgent:
    return WorkspaceAgent(
        id=binding_id,
        workspace_id="ws-1",
        agent_id="agent-1",
        display_name="Helper Agent",
        description="Assists workspace operations",
        config={"temperature": 0.2},
        is_active=True,
        hex_q=1,
        hex_r=-1,
        theme_color="#52d685",
        label="relay",
        status="running",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.fixture
def mock_workspace_service() -> AsyncMock:
    service = AsyncMock()
    service.create_workspace = AsyncMock(return_value=_make_workspace())
    service.list_workspaces = AsyncMock(return_value=[_make_workspace()])
    service.get_workspace = AsyncMock(return_value=_make_workspace())
    service.update_workspace = AsyncMock(return_value=_make_workspace())
    service.delete_workspace = AsyncMock(return_value=True)
    service.list_members = AsyncMock(return_value=[_make_member()])
    service.add_member = AsyncMock(return_value=_make_member())
    service.update_member_role = AsyncMock(return_value=_make_member(role=WorkspaceRole.VIEWER))
    service.remove_member = AsyncMock(return_value=True)
    service.list_workspace_agents = AsyncMock(return_value=[_make_workspace_agent()])
    service.bind_agent = AsyncMock(return_value=_make_workspace_agent())
    service.update_agent_binding = AsyncMock(return_value=_make_workspace_agent())
    service.unbind_agent = AsyncMock(return_value=True)
    service.publish_pending_events = AsyncMock(return_value=None)
    return service


@pytest.fixture
def workspaces_client(mock_workspace_service: AsyncMock) -> TestClient:
    from src.infrastructure.adapters.primary.web.dependencies import get_current_user
    from src.infrastructure.adapters.primary.web.routers.workspaces import (
        get_workspace_service,
        router,
    )
    from src.infrastructure.adapters.secondary.persistence.database import get_db

    app = FastAPI()
    app.include_router(router)

    mock_db = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()

    async def override_get_db():
        yield mock_db

    user = Mock()
    user.id = "user-1"

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_workspace_service] = lambda: mock_workspace_service
    client = TestClient(app)
    client.mock_db = mock_db  # type: ignore[attr-defined]
    return client


@pytest.mark.unit
class TestWorkspacesRouter:
    def test_create_workspace_success(
        self, workspaces_client: TestClient, mock_workspace_service: AsyncMock
    ) -> None:
        response = workspaces_client.post(
            "/api/v1/tenants/tenant-1/projects/project-1/workspaces",
            json={"name": "Team Workspace", "description": "Workspace description"},
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["id"] == "ws-1"
        assert mock_workspace_service.create_workspace.await_count == 1
        metadata = mock_workspace_service.create_workspace.await_args.kwargs["metadata"]
        assert metadata["workspace_use_case"] == "general"
        assert metadata["workspace_type"] == "general"
        assert metadata["collaboration_mode"] == "single_agent"
        assert metadata["agent_conversation_mode"] == "single_agent"

    def test_create_workspace_forwards_scenario_and_collaboration_metadata(
        self, workspaces_client: TestClient, mock_workspace_service: AsyncMock
    ) -> None:
        response = workspaces_client.post(
            "/api/v1/tenants/tenant-1/projects/project-1/workspaces",
            json={
                "name": "Delivery Room",
                "use_case": "programming",
                "collaboration_mode": "autonomous",
                "sandbox_code_root": "my-evo",
                "metadata": {"source": "ui"},
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        metadata = mock_workspace_service.create_workspace.await_args.kwargs["metadata"]
        assert metadata["source"] == "ui"
        assert metadata["workspace_use_case"] == "programming"
        assert metadata["workspace_type"] == "software_development"
        assert metadata["collaboration_mode"] == "autonomous"
        assert metadata["agent_conversation_mode"] == "autonomous"
        assert metadata["autonomy_profile"] == {"workspace_type": "software_development"}
        assert metadata["sandbox_code_root"] == "/workspace/my-evo"
        assert metadata["code_context"]["sandbox_code_root"] == "/workspace/my-evo"

    def test_create_workspace_rejects_unscoped_programming_root(
        self, workspaces_client: TestClient, mock_workspace_service: AsyncMock
    ) -> None:
        response = workspaces_client.post(
            "/api/v1/tenants/tenant-1/projects/project-1/workspaces",
            json={
                "name": "Unsafe Delivery Room",
                "use_case": "programming",
                "sandbox_code_root": "/workspace",
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_workspace_service.create_workspace.assert_not_awaited()

    def test_list_workspaces_success(
        self, workspaces_client: TestClient, mock_workspace_service: AsyncMock
    ) -> None:
        response = workspaces_client.get("/api/v1/tenants/tenant-1/projects/project-1/workspaces")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()) == 1
        assert response.json()[0]["id"] == "ws-1"
        assert mock_workspace_service.list_workspaces.await_count == 1

    def test_get_workspace_maps_not_found(
        self, workspaces_client: TestClient, mock_workspace_service: AsyncMock
    ) -> None:
        mock_workspace_service.get_workspace.side_effect = ValueError("Workspace ws-404 not found")

        response = workspaces_client.get(
            "/api/v1/tenants/tenant-1/projects/project-1/workspaces/ws-404"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_update_workspace_maps_forbidden_and_rolls_back(
        self, workspaces_client: TestClient, mock_workspace_service: AsyncMock
    ) -> None:
        mock_workspace_service.update_workspace.side_effect = PermissionError(
            "Insufficient permission"
        )

        response = workspaces_client.patch(
            "/api/v1/tenants/tenant-1/projects/project-1/workspaces/ws-1",
            json={"name": "New Name"},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert workspaces_client.mock_db.rollback.await_count == 1  # type: ignore[attr-defined]

    def test_add_member_maps_bad_request(
        self, workspaces_client: TestClient, mock_workspace_service: AsyncMock
    ) -> None:
        mock_workspace_service.add_member.side_effect = ValueError("User already a member")

        response = workspaces_client.post(
            "/api/v1/tenants/tenant-1/projects/project-1/workspaces/ws-1/members",
            json={"user_id": "user-2", "role": "editor"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_list_agents_success(
        self, workspaces_client: TestClient, mock_workspace_service: AsyncMock
    ) -> None:
        response = workspaces_client.get(
            "/api/v1/tenants/tenant-1/projects/project-1/workspaces/ws-1/agents?active_only=true"
        )

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()) == 1
        assert mock_workspace_service.list_workspace_agents.await_count == 1

    def test_create_agent_forwards_layout_fields(
        self, workspaces_client: TestClient, mock_workspace_service: AsyncMock
    ) -> None:
        response = workspaces_client.post(
            "/api/v1/tenants/tenant-1/projects/project-1/workspaces/ws-1/agents",
            json={
                "agent_id": "agent-1",
                "display_name": "Planner",
                "hex_q": 3,
                "hex_r": -2,
                "theme_color": "#8b5cf6",
                "label": "planner",
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["hex_q"] == 1
        await_kwargs = mock_workspace_service.bind_agent.await_args.kwargs
        assert await_kwargs["hex_q"] == 3
        assert await_kwargs["hex_r"] == -2
        assert await_kwargs["theme_color"] == "#8b5cf6"
        assert await_kwargs["label"] == "planner"
        assert mock_workspace_service.publish_pending_events.await_count == 1

    def test_update_agent_forwards_layout_fields(
        self, workspaces_client: TestClient, mock_workspace_service: AsyncMock
    ) -> None:
        response = workspaces_client.patch(
            "/api/v1/tenants/tenant-1/projects/project-1/workspaces/ws-1/agents/wa-1",
            json={
                "hex_q": 4,
                "hex_r": 0,
                "theme_color": "#f59e0b",
                "label": "ops",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        await_kwargs = mock_workspace_service.update_agent_binding.await_args.kwargs
        assert await_kwargs["hex_q"] == 4
        assert await_kwargs["hex_r"] == 0
        assert await_kwargs["theme_color"] == "#f59e0b"
        assert await_kwargs["label"] == "ops"
        assert mock_workspace_service.publish_pending_events.await_count == 1

    def test_update_agent_still_succeeds_when_event_publish_fails(
        self, workspaces_client: TestClient, mock_workspace_service: AsyncMock
    ) -> None:
        mock_workspace_service.publish_pending_events.side_effect = RuntimeError("redis unavailable")

        response = workspaces_client.patch(
            "/api/v1/tenants/tenant-1/projects/project-1/workspaces/ws-1/agents/wa-1",
            json={"hex_q": 4, "hex_r": 0},
        )

        assert response.status_code == status.HTTP_200_OK
        assert workspaces_client.mock_db.commit.await_count == 1  # type: ignore[attr-defined]

    def test_update_agent_rejects_user_supplied_status_field(
        self, workspaces_client: TestClient, mock_workspace_service: AsyncMock
    ) -> None:
        response = workspaces_client.patch(
            "/api/v1/tenants/tenant-1/projects/project-1/workspaces/ws-1/agents/wa-1",
            json={"status": "busy"},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        mock_workspace_service.update_agent_binding.assert_not_awaited()

    def test_create_agent_rejects_out_of_bounds_hex(
        self, workspaces_client: TestClient, mock_workspace_service: AsyncMock
    ) -> None:
        response = workspaces_client.post(
            "/api/v1/tenants/tenant-1/projects/project-1/workspaces/ws-1/agents",
            json={
                "agent_id": "agent-1",
                "hex_q": 25,
                "hex_r": 0,
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        mock_workspace_service.bind_agent.assert_not_awaited()
