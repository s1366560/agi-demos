"""Unit tests for workspace lifecycle/member/agent router."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI, status
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

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
    project_access_result = Mock()
    project_access_result.scalar_one_or_none.return_value = "project-1"
    mock_db.execute = AsyncMock(return_value=project_access_result)

    async def override_get_db():
        yield mock_db

    user = Mock()
    user.id = "user-1"

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_workspace_service] = lambda: mock_workspace_service
    client = TestClient(app)
    client.mock_db = mock_db  # type: ignore[attr-defined]
    client.mock_project_access_result = project_access_result  # type: ignore[attr-defined]
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

    def test_create_workspace_forwards_programming_metadata_without_delivery_defaults(
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
        assert "source_control" not in metadata
        assert "delivery_cicd" not in metadata

    def test_create_workspace_maps_duplicate_name_to_conflict(
        self, workspaces_client: TestClient, mock_workspace_service: AsyncMock
    ) -> None:
        mock_workspace_service.create_workspace.side_effect = IntegrityError(
            "secret insert statement",
            {"name": "secret-workspace"},
            Exception(
                'duplicate key value violates unique constraint "uq_workspaces_project_name"'
            ),
        )

        response = workspaces_client.post(
            "/api/v1/tenants/tenant-1/projects/project-1/workspaces",
            json={"name": "Team Workspace", "description": "Workspace description"},
        )

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.json()["detail"] == "Workspace already exists"
        assert "secret" not in response.text
        workspaces_client.mock_db.rollback.assert_awaited_once()  # type: ignore[attr-defined]

    def test_create_workspace_ignores_top_level_source_control_defaults(
        self, workspaces_client: TestClient, mock_workspace_service: AsyncMock
    ) -> None:
        response = workspaces_client.post(
            "/api/v1/tenants/tenant-1/projects/project-1/workspaces",
            json={
                "name": "GitLab Delivery",
                "use_case": "programming",
                "sandbox_code_root": "gitlab-delivery",
                "source_control": {
                    "provider": "gitlab",
                    "repo": "platform/gitlab-delivery",
                    "default_branch": "develop",
                    "server_url": "https://gitlab.example.com",
                    "auth_token_env": "GITLAB_TOKEN",
                },
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        metadata = mock_workspace_service.create_workspace.await_args.kwargs["metadata"]
        assert metadata["workspace_use_case"] == "programming"
        assert metadata["sandbox_code_root"] == "/workspace/gitlab-delivery"
        assert "source_control" not in metadata
        assert "delivery_cicd" not in metadata

    def test_create_workspace_preserves_explicit_programming_delivery_provider(
        self, workspaces_client: TestClient, mock_workspace_service: AsyncMock
    ) -> None:
        response = workspaces_client.post(
            "/api/v1/tenants/tenant-1/projects/project-1/workspaces",
            json={
                "name": "Sandbox Native Delivery",
                "use_case": "programming",
                "sandbox_code_root": "my-evo",
                "metadata": {
                    "delivery_cicd": {
                        "provider": "sandbox_native",
                        "install_command": "pnpm install",
                    }
                },
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        metadata = mock_workspace_service.create_workspace.await_args.kwargs["metadata"]
        delivery = metadata["delivery_cicd"]
        assert delivery["provider"] == "sandbox_native"
        assert delivery["install_command"] == "pnpm install"
        assert "drone" not in delivery

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

    def test_create_workspace_requires_project_membership(
        self, workspaces_client: TestClient, mock_workspace_service: AsyncMock
    ) -> None:
        workspaces_client.mock_project_access_result.scalar_one_or_none.return_value = None  # type: ignore[attr-defined]

        response = workspaces_client.post(
            "/api/v1/tenants/tenant-1/projects/project-1/workspaces",
            json={"name": "Unauthorized Workspace"},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["detail"] == "Access denied"
        mock_workspace_service.create_workspace.assert_not_awaited()
        workspaces_client.mock_db.rollback.assert_awaited_once()  # type: ignore[attr-defined]

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
        assert response.json()["detail"] == "Workspace not found"
        assert "ws-404" not in response.text

    def test_get_workspace_sanitizes_internal_errors(
        self, workspaces_client: TestClient, mock_workspace_service: AsyncMock
    ) -> None:
        mock_workspace_service.get_workspace.side_effect = RuntimeError(
            "internal workspace backend secret"
        )

        response = workspaces_client.get(
            "/api/v1/tenants/tenant-1/projects/project-1/workspaces/ws-1"
        )

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert response.json()["detail"] == "Internal server error"
        assert "internal" not in response.json()["detail"]

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
        assert response.json()["detail"] == "Access denied"
        assert "permission" not in response.text.lower()
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
        assert response.json()["detail"] == "Invalid workspace request"
        assert "already" not in response.text.lower()

    def test_add_member_requires_target_project_membership(
        self, workspaces_client: TestClient, mock_workspace_service: AsyncMock
    ) -> None:
        workspaces_client.mock_project_access_result.scalar_one_or_none.return_value = None  # type: ignore[attr-defined]

        response = workspaces_client.post(
            "/api/v1/tenants/tenant-1/projects/project-1/workspaces/ws-1/members",
            json={"user_id": "user-2", "role": "editor"},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["detail"] == "Access denied"
        mock_workspace_service.add_member.assert_not_awaited()
        workspaces_client.mock_db.rollback.assert_awaited_once()  # type: ignore[attr-defined]

    def test_list_members_batch_resolves_user_email(
        self, workspaces_client: TestClient, mock_workspace_service: AsyncMock
    ) -> None:
        mock_workspace_service.list_members.return_value = [
            _make_member("user-2"),
            _make_member("user-3", role=WorkspaceRole.VIEWER),
        ]
        user_email_result = Mock()
        user_email_result.all.return_value = [
            ("user-2", "editor@example.com"),
            ("user-3", "viewer@example.com"),
        ]
        workspaces_client.mock_db.execute.return_value = user_email_result  # type: ignore[attr-defined]

        response = workspaces_client.get(
            "/api/v1/tenants/tenant-1/projects/project-1/workspaces/ws-1/members"
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == [
            {
                "id": "wm-user-2",
                "workspace_id": "ws-1",
                "user_id": "user-2",
                "user_email": "editor@example.com",
                "role": "editor",
                "invited_by": "user-1",
                "created_at": response.json()[0]["created_at"],
                "updated_at": response.json()[0]["updated_at"],
            },
            {
                "id": "wm-user-3",
                "workspace_id": "ws-1",
                "user_id": "user-3",
                "user_email": "viewer@example.com",
                "role": "viewer",
                "invited_by": "user-1",
                "created_at": response.json()[1]["created_at"],
                "updated_at": response.json()[1]["updated_at"],
            },
        ]
        assert workspaces_client.mock_db.execute.await_count == 1  # type: ignore[attr-defined]

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
        mock_workspace_service.publish_pending_events.side_effect = [
            RuntimeError("redis unavailable"),
            None,
        ]

        response = workspaces_client.patch(
            "/api/v1/tenants/tenant-1/projects/project-1/workspaces/ws-1/agents/wa-1",
            json={"hex_q": 4, "hex_r": 0},
        )

        assert response.status_code == status.HTTP_200_OK
        assert workspaces_client.mock_db.commit.await_count == 1  # type: ignore[attr-defined]
        assert mock_workspace_service.publish_pending_events.await_count == 2

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
