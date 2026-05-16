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
from src.infrastructure.adapters.secondary.persistence.models import Conversation


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
