"""Tests for agent event and workflow-status endpoints."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from src.application.services.agent.execution_resume_service import ResumeContext
from src.domain.model.agent.execution.execution_checkpoint import ExecutionCheckpoint
from src.domain.ports.services.workspace_authority_port import (
    WorkspaceAuthorityAccessDeniedError,
    WorkspaceAuthorityUnavailableError,
)
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
)
from src.infrastructure.plugins.v2.agent_event_query_services import (
    AgentEventExecutionStatusV2,
)
from src.infrastructure.plugins.v2.agent_workflow_status_services import (
    AgentWorkflowStatusStateV2,
)
from src.infrastructure.plugins.v2.workspace_core_runtime import WorkspaceCoreRuntimeServiceV2


class _WorkspaceAuthority:
    def __init__(self, role: str | None = None, *, unavailable: bool = False) -> None:
        self.role = role
        self.unavailable = unavailable

    async def get_membership_role(self, _scope: object) -> str:
        if self.unavailable:
            raise WorkspaceAuthorityUnavailableError
        if self.role is None:
            raise WorkspaceAuthorityAccessDeniedError
        return self.role


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

    def _request_with_container(
        self,
        container: object,
        *,
        workspace_role: str | None = None,
        workspace_unavailable: bool = False,
    ) -> MagicMock:
        request = MagicMock()
        request.app.state.container.with_db.return_value = container
        request.app.state.workspace_authority = _WorkspaceAuthority(
            workspace_role,
            unavailable=workspace_unavailable,
        )
        request.app.state.workspace_core_runtime_service_v2 = WorkspaceCoreRuntimeServiceV2(
            settings=SimpleNamespace(),
            client=SimpleNamespace(),
            authority=request.app.state.workspace_authority,
            context_judge=SimpleNamespace(),
            plan_judge=SimpleNamespace(),
            autonomy_judge=SimpleNamespace(),
            access_verifier=SimpleNamespace(),
            event_sink=SimpleNamespace(),
            agent_runtime_provider=SimpleNamespace(),
            provider_adapter=SimpleNamespace(),
        )
        return request

    def _event_query(
        self,
        *,
        events: list[object] | None = None,
        event_error: Exception | None = None,
        status_error: Exception | None = None,
    ) -> tuple[SimpleNamespace, SimpleNamespace]:
        service = SimpleNamespace(
            get_events=AsyncMock(
                return_value=list(events or []),
                side_effect=event_error,
            ),
            get_execution_status=AsyncMock(
                return_value=AgentEventExecutionStatusV2(
                    is_running=False,
                    last_event_time_us=0,
                    last_event_counter=0,
                    current_message_id=None,
                ),
                side_effect=status_error,
            ),
        )
        return SimpleNamespace(service=service), service

    def _resume_authority(
        self,
        *,
        db: object | None = None,
        can_resume_error: Exception | None = None,
    ) -> tuple[SimpleNamespace, SimpleNamespace]:
        checkpoint = ExecutionCheckpoint(
            id="checkpoint-resume",
            conversation_id="conversation-resume",
            message_id="message-resume",
            checkpoint_type="step_complete",
            execution_state={},
            step_number=7,
        )
        context = ResumeContext(
            conversation_id="conversation-resume",
            project_id="project-1",
            tenant_id="tenant-1",
            user_id="user-1",
            checkpoint=checkpoint,
            pending_message="continue",
        )
        service = SimpleNamespace(
            can_resume=AsyncMock(return_value=True, side_effect=can_resume_error),
            get_resume_context=AsyncMock(return_value=context),
            prepare_resume_request=AsyncMock(return_value={"resume": True}),
            mark_resumed=AsyncMock(),
        )
        selected_db = db if db is not None else SimpleNamespace(commit=AsyncMock())
        return SimpleNamespace(db=selected_db, service=service), service

    def _workflow_status_authority(
        self,
        *,
        db: object | None = None,
        absent: bool = False,
        status_error: Exception | None = None,
    ) -> tuple[SimpleNamespace, SimpleNamespace]:
        status = None
        if not absent:
            status = AgentWorkflowStatusStateV2(
                workflow_id="actor-a",
                status="RUNNING",
                started_at=None,
            )
        service = SimpleNamespace(
            get_status=AsyncMock(return_value=status, side_effect=status_error),
        )
        selected_db = db if db is not None else SimpleNamespace()
        return SimpleNamespace(db=selected_db, service=service), service

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
        workflow_authority, workflow_service = self._workflow_status_authority(db=test_db)

        with pytest.raises(HTTPException) as exc_info:
            await get_workflow_status(
                conversation_id,
                request=MagicMock(),
                current_user=another_user,
                workflow_status_authority=workflow_authority,
            )

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Access denied to this conversation"
        workflow_service.get_status.assert_not_awaited()

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
        event_query, event_service = self._event_query()

        with pytest.raises(HTTPException) as exc_info:
            await get_conversation_events(
                conversation_id,
                request=self._request_with_container(container),
                current_user=another_user,
                db=test_db,
                event_query=event_query,
            )

        assert exc_info.value.status_code == 403
        event_service.get_events.assert_not_awaited()

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
        event_query, event_service = self._event_query()

        with pytest.raises(HTTPException) as exc_info:
            await get_conversation_events(
                conversation_id,
                request=self._request_with_container(container),
                current_user=another_user,
                db=test_db,
                event_query=event_query,
            )

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Access denied to this conversation"
        event_service.get_events.assert_not_awaited()

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
        event_query, event_service = self._event_query()

        with pytest.raises(HTTPException) as exc_info:
            await get_conversation_events(
                conversation_id,
                request=self._request_with_container(container),
                from_time_us=0,
                from_counter=0,
                limit=1000,
                current_user=another_user,
                db=test_db,
                event_query=event_query,
            )

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Access denied to this conversation"
        event_service.get_events.assert_not_awaited()

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
            UserTenant(
                id="ut-events-router-workspace-member",
                user_id=another_user.id,
                tenant_id=test_tenant_db.id,
                role="member",
                permissions={"read": True},
            )
        )
        await test_db.commit()
        container = SimpleNamespace()
        event_query, event_service = self._event_query()

        response = await get_conversation_events(
            conversation_id,
            request=self._request_with_container(container, workspace_role="viewer"),
            from_time_us=0,
            from_counter=0,
            limit=1000,
            current_user=another_user,
            db=test_db,
            event_query=event_query,
        )

        assert response.events == []
        event_service.get_events.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_workspace_conversation_fails_closed_when_core_is_unavailable(
        self,
        test_db,
        test_project_db,
        test_tenant_db,
        test_user,
        another_user,
    ) -> None:
        conversation_id = "workspace-chat:workspace-events-offline"
        test_db.add(
            Conversation(
                id=conversation_id,
                project_id=test_project_db.id,
                tenant_id=test_tenant_db.id,
                user_id=test_user.id,
                title="Workspace events offline",
                status="active",
                workspace_id="workspace-events-offline",
            )
        )
        test_db.add(
            UserTenant(
                id="ut-events-router-offline",
                user_id=another_user.id,
                tenant_id=test_tenant_db.id,
                role="member",
                permissions={"read": True},
            )
        )
        await test_db.commit()
        container = SimpleNamespace(agent_execution_event_repository=MagicMock())
        event_query, event_service = self._event_query()

        with pytest.raises(HTTPException) as exc_info:
            await get_conversation_events(
                conversation_id,
                request=self._request_with_container(container, workspace_unavailable=True),
                current_user=another_user,
                db=test_db,
                event_query=event_query,
            )

        assert exc_info.value.status_code == 503
        assert exc_info.value.detail["code"] == "WORKSPACE_CORE_UNAVAILABLE"
        event_service.get_events.assert_not_awaited()

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
        event_query, event_service = self._event_query()

        with pytest.raises(HTTPException) as exc_info:
            await get_execution_status(
                conversation_id,
                request=self._request_with_container(container),
                current_user=another_user,
                db=test_db,
                event_query=event_query,
            )

        assert exc_info.value.status_code == 403
        event_service.get_execution_status.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_resume_execution_rejects_before_resume_service_access(
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
        resume_authority, resume_service = self._resume_authority(db=test_db)

        with pytest.raises(HTTPException) as exc_info:
            await resume_execution(
                conversation_id,
                request=MagicMock(),
                current_user=another_user,
                resume_authority=resume_authority,
            )

        assert exc_info.value.status_code == 403
        resume_service.can_resume.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_conversation_events_sanitizes_internal_errors(
        self,
        test_db,
        test_user,
    ) -> None:
        async def accessible_conversation(*_args, **_kwargs):
            return SimpleNamespace(tenant_id="tenant-1", project_id="project-1")

        container = SimpleNamespace()
        event_query, _event_service = self._event_query(
            event_error=RuntimeError("internal event secret")
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
                event_query=event_query,
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

        container = SimpleNamespace()
        event_query, _event_service = self._event_query(
            status_error=RuntimeError("internal status secret")
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
                event_query=event_query,
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

        self.monkeypatch.setattr(
            "src.infrastructure.adapters.primary.web.routers.agent.events._get_accessible_conversation",
            accessible_conversation,
        )
        resume_authority, _resume_service = self._resume_authority(
            can_resume_error=RuntimeError("internal checkpoint secret")
        )

        with pytest.raises(HTTPException) as exc_info:
            await resume_execution(
                "conversation-secret",
                request=MagicMock(),
                current_user=test_user,
                resume_authority=resume_authority,
            )

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Failed to resume execution"
        assert "internal" not in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_resume_execution_uses_v2_authority_and_commits_resume_marker(
        self,
        test_user,
    ) -> None:
        async def accessible_conversation(*_args, **_kwargs):
            return SimpleNamespace(tenant_id="tenant-1", project_id="project-1")

        self.monkeypatch.setattr(
            "src.infrastructure.adapters.primary.web.routers.agent.events._get_accessible_conversation",
            accessible_conversation,
        )
        resume_authority, resume_service = self._resume_authority()

        response = await resume_execution(
            "conversation-resume",
            request=MagicMock(),
            override_message="resume now",
            current_user=test_user,
            resume_authority=resume_authority,
        )

        resume_service.can_resume.assert_awaited_once_with("conversation-resume")
        resume_service.get_resume_context.assert_awaited_once_with("conversation-resume")
        resume_service.prepare_resume_request.assert_awaited_once_with(
            "conversation-resume",
            override_message="resume now",
        )
        resume_service.mark_resumed.assert_awaited_once_with(
            "conversation-resume",
            "checkpoint-resume",
        )
        resume_authority.db.commit.assert_awaited_once_with()
        assert response["checkpoint_id"] == "checkpoint-resume"
        assert response["checkpoint_type"] == "step_complete"
        assert response["step_number"] == 7
        assert response["resume_request"] == {"resume": True}

    @pytest.mark.asyncio
    async def test_get_workflow_status_sanitizes_internal_errors(
        self,
        test_db,
        test_user,
    ) -> None:
        async def accessible_conversation(*_args, **_kwargs):
            return SimpleNamespace(tenant_id="tenant-1", project_id="project-1")

        self.monkeypatch.setattr(
            "src.infrastructure.adapters.primary.web.routers.agent.events._get_accessible_conversation",
            accessible_conversation,
        )
        workflow_authority, _workflow_service = self._workflow_status_authority(
            db=test_db,
            status_error=RuntimeError("internal actor secret"),
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_workflow_status(
                "conversation-secret",
                request=MagicMock(),
                current_user=test_user,
                workflow_status_authority=workflow_authority,
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

        self.monkeypatch.setattr(
            "src.infrastructure.adapters.primary.web.routers.agent.events._get_accessible_conversation",
            accessible_conversation,
        )
        workflow_authority, workflow_service = self._workflow_status_authority(
            db=test_db,
            absent=True,
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_workflow_status(
                "conversation-secret",
                request=MagicMock(),
                current_user=test_user,
                workflow_status_authority=workflow_authority,
            )

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Actor not found"
        assert "conversation-secret" not in str(exc_info.value.detail)
        workflow_service.get_status.assert_awaited_once_with(
            tenant_id="tenant-1",
            project_id="project-1",
            agent_mode="default",
        )

    @pytest.mark.asyncio
    async def test_get_workflow_status_uses_v2_authority(
        self,
        test_db,
        test_user,
    ) -> None:
        async def accessible_conversation(*_args, **_kwargs):
            return SimpleNamespace(tenant_id="tenant-1", project_id="project-1")

        self.monkeypatch.setattr(
            "src.infrastructure.adapters.primary.web.routers.agent.events._get_accessible_conversation",
            accessible_conversation,
        )
        workflow_authority, workflow_service = self._workflow_status_authority(db=test_db)

        response = await get_workflow_status(
            "conversation-status",
            request=MagicMock(),
            current_user=test_user,
            workflow_status_authority=workflow_authority,
        )

        workflow_service.get_status.assert_awaited_once_with(
            tenant_id="tenant-1",
            project_id="project-1",
            agent_mode="default",
        )
        assert response.workflow_id == "actor-a"
        assert response.status == "RUNNING"
        assert response.started_at is None
