"""Tests for agent event and workflow-status endpoints."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from src.infrastructure.adapters.primary.web.routers.agent.events import (
    get_conversation_events,
    get_execution_status,
    get_workflow_status,
    resume_execution,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Conversation,
    UserProject,
    UserTenant,
    WorkspaceMemberModel,
    WorkspaceModel,
)


@pytest.mark.unit
class TestAgentEventsRouter:
    @pytest.fixture(autouse=True)
    def _router_monkeypatch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.monkeypatch = monkeypatch

    async def _seed_conversation(self, test_db, test_project_db, test_tenant_db, test_user) -> str:
        conversation_id = "conversation-events-router"
        conversation = Conversation(
            id=conversation_id,
            project_id=test_project_db.id,
            tenant_id=test_tenant_db.id,
            user_id=test_user.id,
            title="Events router",
            status="active",
            agent_config={},
            meta={},
            message_count=0,
            current_mode="build",
            merge_strategy="result_only",
            participant_agents=[],
        )
        test_db.add(conversation)
        await test_db.commit()
        return conversation_id

    def _request_with_container(self, container: object) -> MagicMock:
        request = MagicMock()
        request.app.state.container.with_db.return_value = container
        return request

    @pytest.mark.asyncio
    async def test_get_workflow_status_rejects_user_outside_conversation_tenant(
        self,
        test_db,
        test_project_db,
        test_tenant_db,
        test_user,
        another_user,
    ) -> None:
        conversation_id = await self._seed_conversation(
            test_db, test_project_db, test_tenant_db, test_user
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_workflow_status(
                conversation_id,
                request=MagicMock(),
                current_user=another_user,
                db=test_db,
            )

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Access denied to this conversation"

    @pytest.mark.asyncio
    async def test_get_conversation_events_rejects_before_event_repo_access(
        self,
        test_db,
        test_project_db,
        test_tenant_db,
        test_user,
        another_user,
    ) -> None:
        conversation_id = await self._seed_conversation(
            test_db, test_project_db, test_tenant_db, test_user
        )
        container = SimpleNamespace(agent_execution_event_repository=MagicMock())

        with pytest.raises(HTTPException) as exc_info:
            await get_conversation_events(
                conversation_id,
                request=self._request_with_container(container),
                current_user=another_user,
                db=test_db,
            )

        assert exc_info.value.status_code == 403
        container.agent_execution_event_repository.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_conversation_events_rejects_same_tenant_non_owner_private_conversation(
        self,
        test_db,
        test_project_db,
        test_tenant_db,
        test_user,
        another_user,
    ) -> None:
        conversation_id = await self._seed_conversation(
            test_db, test_project_db, test_tenant_db, test_user
        )
        test_db.add(
            UserTenant(
                id="ut-events-router-other",
                user_id=another_user.id,
                tenant_id=test_tenant_db.id,
                role="member",
                permissions={"read": True},
            )
        )
        await test_db.commit()
        container = SimpleNamespace(agent_execution_event_repository=MagicMock())

        with pytest.raises(HTTPException) as exc_info:
            await get_conversation_events(
                conversation_id,
                request=self._request_with_container(container),
                current_user=another_user,
                db=test_db,
            )

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Access denied to this conversation"
        container.agent_execution_event_repository.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_conversation_events_rejects_project_member_without_workspace_membership(
        self,
        test_db,
        test_project_db,
        test_tenant_db,
        test_user,
        another_user,
    ) -> None:
        conversation_id = "workspace-chat:workspace-events-router"
        test_db.add(
            Conversation(
                id=conversation_id,
                project_id=test_project_db.id,
                tenant_id=test_tenant_db.id,
                user_id=test_user.id,
                title="Workspace events router",
                status="active",
                agent_config={},
                meta={},
                message_count=0,
                current_mode="build",
                merge_strategy="result_only",
                participant_agents=[],
                workspace_id="workspace-events-router",
            )
        )
        test_db.add(
            UserTenant(
                id="ut-events-router-project-member",
                user_id=another_user.id,
                tenant_id=test_tenant_db.id,
                role="member",
                permissions={"read": True},
            )
        )
        test_db.add(
            UserProject(
                id="up-events-router-project-member",
                user_id=another_user.id,
                project_id=test_project_db.id,
                role="viewer",
            )
        )
        await test_db.commit()
        container = SimpleNamespace(agent_execution_event_repository=MagicMock())

        with pytest.raises(HTTPException) as exc_info:
            await get_conversation_events(
                conversation_id,
                request=self._request_with_container(container),
                from_time_us=0,
                from_counter=0,
                limit=1000,
                current_user=another_user,
                db=test_db,
            )

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Access denied to this conversation"
        container.agent_execution_event_repository.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_conversation_events_allows_workspace_member_for_workspace_conversation(
        self,
        test_db,
        test_project_db,
        test_tenant_db,
        test_user,
        another_user,
    ) -> None:
        conversation_id = "workspace-chat:workspace-events-member"
        workspace_id = "workspace-events-member"
        test_db.add(
            Conversation(
                id=conversation_id,
                project_id=test_project_db.id,
                tenant_id=test_tenant_db.id,
                user_id=test_user.id,
                title="Workspace events router",
                status="active",
                agent_config={},
                meta={},
                message_count=0,
                current_mode="build",
                merge_strategy="result_only",
                participant_agents=[],
                workspace_id=workspace_id,
            )
        )
        test_db.add(
            WorkspaceModel(
                id=workspace_id,
                tenant_id=test_tenant_db.id,
                project_id=test_project_db.id,
                name="Workspace Events Member",
                created_by=test_user.id,
            )
        )
        test_db.add(
            UserTenant(
                id="ut-events-router-workspace-member",
                user_id=another_user.id,
                tenant_id=test_tenant_db.id,
                role="member",
                permissions={"read": True},
            )
        )
        test_db.add(
            WorkspaceMemberModel(
                id="wm-events-router-workspace-member",
                user_id=another_user.id,
                workspace_id=workspace_id,
                role="viewer",
                invited_by=test_user.id,
            )
        )
        await test_db.commit()
        event_repo = SimpleNamespace(get_events=AsyncMock(return_value=[]))
        container = SimpleNamespace(agent_execution_event_repository=lambda: event_repo)
        self.monkeypatch.setattr(
            "src.infrastructure.adapters.primary.web.routers.agent.events.get_container_with_db",
            lambda _request, _db: container,
        )

        response = await get_conversation_events(
            conversation_id,
            request=self._request_with_container(container),
            from_time_us=0,
            from_counter=0,
            limit=1000,
            current_user=another_user,
            db=test_db,
        )

        assert response.events == []
        event_repo.get_events.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_execution_status_rejects_before_event_repo_access(
        self,
        test_db,
        test_project_db,
        test_tenant_db,
        test_user,
        another_user,
    ) -> None:
        conversation_id = await self._seed_conversation(
            test_db, test_project_db, test_tenant_db, test_user
        )
        container = SimpleNamespace(agent_execution_event_repository=MagicMock(), redis=MagicMock())

        with pytest.raises(HTTPException) as exc_info:
            await get_execution_status(
                conversation_id,
                request=self._request_with_container(container),
                current_user=another_user,
                db=test_db,
            )

        assert exc_info.value.status_code == 403
        container.agent_execution_event_repository.assert_not_called()
        container.redis.assert_not_called()

    @pytest.mark.asyncio
    async def test_resume_execution_rejects_before_resume_service_access(
        self,
        test_db,
        test_project_db,
        test_tenant_db,
        test_user,
        another_user,
        monkeypatch,
    ) -> None:
        conversation_id = await self._seed_conversation(
            test_db, test_project_db, test_tenant_db, test_user
        )
        get_resume_service = MagicMock()
        monkeypatch.setattr(
            "src.infrastructure.adapters.primary.web.routers.agent.events._get_resume_service",
            get_resume_service,
        )

        with pytest.raises(HTTPException) as exc_info:
            await resume_execution(
                conversation_id,
                request=MagicMock(),
                current_user=another_user,
                db=test_db,
            )

        assert exc_info.value.status_code == 403
        get_resume_service.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_conversation_events_sanitizes_internal_errors(
        self,
        test_db,
        test_user,
    ) -> None:
        async def accessible_conversation(*_args, **_kwargs):
            return SimpleNamespace(tenant_id="tenant-1", project_id="project-1")

        container = SimpleNamespace(
            agent_execution_event_repository=lambda: SimpleNamespace(
                get_events=AsyncMock(side_effect=RuntimeError("internal event secret"))
            )
        )
        self.monkeypatch.setattr(
            "src.infrastructure.adapters.primary.web.routers.agent.events._get_accessible_conversation",
            accessible_conversation,
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_conversation_events(
                "conversation-secret",
                request=self._request_with_container(container),
                current_user=test_user,
                db=test_db,
            )

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Failed to get events"
        assert "internal" not in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_get_execution_status_sanitizes_internal_errors(
        self,
        test_db,
        test_user,
    ) -> None:
        async def accessible_conversation(*_args, **_kwargs):
            return SimpleNamespace(tenant_id="tenant-1", project_id="project-1")

        container = SimpleNamespace(
            agent_execution_event_repository=lambda: SimpleNamespace(
                get_last_event_time=AsyncMock(side_effect=RuntimeError("internal status secret"))
            ),
            redis=lambda: None,
        )
        self.monkeypatch.setattr(
            "src.infrastructure.adapters.primary.web.routers.agent.events._get_accessible_conversation",
            accessible_conversation,
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_execution_status(
                "conversation-secret",
                request=self._request_with_container(container),
                current_user=test_user,
                db=test_db,
            )

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Failed to get execution status"
        assert "internal" not in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_resume_execution_sanitizes_internal_errors(
        self,
        test_db,
        test_user,
    ) -> None:
        async def accessible_conversation(*_args, **_kwargs):
            return SimpleNamespace(tenant_id="tenant-1", project_id="project-1")

        async def failing_resume_service(_db):
            raise RuntimeError("internal checkpoint secret")

        self.monkeypatch.setattr(
            "src.infrastructure.adapters.primary.web.routers.agent.events._get_accessible_conversation",
            accessible_conversation,
        )
        self.monkeypatch.setattr(
            "src.infrastructure.adapters.primary.web.routers.agent.events._get_resume_service",
            failing_resume_service,
        )

        with pytest.raises(HTTPException) as exc_info:
            await resume_execution(
                "conversation-secret",
                request=MagicMock(),
                current_user=test_user,
                db=test_db,
            )

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Failed to resume execution"
        assert "internal" not in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_get_workflow_status_sanitizes_internal_errors(
        self,
        test_db,
        test_user,
    ) -> None:
        async def accessible_conversation(*_args, **_kwargs):
            return SimpleNamespace(tenant_id="tenant-1", project_id="project-1")

        async def failing_actor_lookup(*_args, **_kwargs):
            raise RuntimeError("internal actor secret")

        self.monkeypatch.setattr(
            "src.infrastructure.adapters.primary.web.routers.agent.events._get_accessible_conversation",
            accessible_conversation,
        )
        self.monkeypatch.setattr(
            "src.infrastructure.agent.actor.actor_manager.get_actor_if_exists",
            failing_actor_lookup,
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_workflow_status(
                "conversation-secret",
                request=MagicMock(),
                current_user=test_user,
                db=test_db,
            )

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Failed to get workflow status"
        assert "internal" not in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_get_workflow_status_actor_not_found_is_sanitized(
        self,
        test_db,
        test_user,
    ) -> None:
        async def accessible_conversation(*_args, **_kwargs):
            return SimpleNamespace(
                tenant_id="tenant-1",
                project_id="project-1",
            )

        async def missing_actor(*_args, **_kwargs):
            return None

        self.monkeypatch.setattr(
            "src.infrastructure.adapters.primary.web.routers.agent.events._get_accessible_conversation",
            accessible_conversation,
        )
        self.monkeypatch.setattr(
            "src.infrastructure.agent.actor.actor_manager.get_actor_if_exists",
            missing_actor,
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_workflow_status(
                "conversation-secret",
                request=MagicMock(),
                current_user=test_user,
                db=test_db,
            )

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Actor not found"
        assert "conversation-secret" not in str(exc_info.value.detail)
