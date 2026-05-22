"""Tests for conversation route hardening."""

import inspect
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent import Conversation, ConversationStatus
from src.domain.model.agent.conversation.errors import (
    ConversationDomainError,
    ParticipantNotPresentError,
)
from src.infrastructure.adapters.primary.web.routers.agent import (
    conversations as conversations_router,
)
from src.infrastructure.adapters.primary.web.routers.agent.schemas import (
    CreateConversationRequest,
    UpdateConversationConfigRequest,
    UpdateConversationModeRequest,
    UpdateConversationTitleRequest,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Conversation as DBConversation,
    WorkspaceModel,
)


class FailingListUseCase:
    execute = AsyncMock(side_effect=RuntimeError("internal conversation list secret"))


class FailingGetUseCase:
    execute = AsyncMock(side_effect=RuntimeError("internal conversation get secret"))


class FailingAgentService:
    get_conversation = AsyncMock(side_effect=RuntimeError("internal conversation service secret"))


class FailingDb:
    get = AsyncMock(side_effect=RuntimeError("internal direct db secret"))
    rollback = AsyncMock()


class ListUseCase:
    def __init__(self, conversations: list[Conversation], total: int) -> None:
        self._conversations = conversations
        self._total = total

    async def execute(self, **_kwargs: Any) -> list[Conversation]:
        return self._conversations

    async def count(self, **_kwargs: Any) -> int:
        return self._total


def _request_with_container(container: object) -> MagicMock:
    request = MagicMock()
    request.app.state.container.with_db.return_value = container
    return request


@pytest.fixture(autouse=True)
def _patch_llm_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        conversations_router,
        "create_llm_client",
        AsyncMock(return_value=object()),
    )


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("route_name", "expected_detail"),
    [
        ("list", "Failed to list conversations"),
        ("get", "Failed to get conversation"),
        ("context_status", "Failed to get context status"),
        ("delete", "Failed to delete conversation"),
        ("title", "Failed to update conversation title"),
        ("config", "Failed to update conversation config"),
        ("mode", "Failed to update conversation mode"),
        ("generate_title", "Failed to generate conversation title"),
        ("summary", "Failed to generate conversation summary"),
    ],
)
async def test_service_backed_conversation_routes_sanitize_internal_errors(
    route_name: str,
    expected_detail: str,
) -> None:
    container = SimpleNamespace(
        list_conversations_use_case=lambda _llm: FailingListUseCase(),
        get_conversation_use_case=lambda _llm: FailingGetUseCase(),
        agent_service=lambda _llm: FailingAgentService(),
    )
    request = _request_with_container(container)
    current_user = SimpleNamespace(id="user-1")

    route_calls: dict[str, Any] = {
        "list": lambda: conversations_router.list_conversations(
            request=request,
            project_id="project-1",
            status=None,
            limit=50,
            offset=0,
            current_user=current_user,
            tenant_id="tenant-1",
            db=SimpleNamespace(),
        ),
        "get": lambda: conversations_router.get_conversation(
            conversation_id="conversation-1",
            request=request,
            project_id="project-1",
            current_user=current_user,
            tenant_id="tenant-1",
            db=SimpleNamespace(),
        ),
        "context_status": lambda: conversations_router.get_context_status(
            conversation_id="conversation-1",
            request=request,
            project_id="project-1",
            current_user=current_user,
            tenant_id="tenant-1",
            db=SimpleNamespace(),
        ),
        "delete": lambda: conversations_router.delete_conversation(
            conversation_id="conversation-1",
            request=request,
            project_id="project-1",
            current_user=current_user,
            tenant_id="tenant-1",
            db=SimpleNamespace(),
        ),
        "title": lambda: conversations_router.update_conversation_title(
            conversation_id="conversation-1",
            data=UpdateConversationTitleRequest(title="New title"),
            request=request,
            project_id="project-1",
            current_user=current_user,
            tenant_id="tenant-1",
            db=SimpleNamespace(),
        ),
        "config": lambda: conversations_router.update_conversation_config(
            conversation_id="conversation-1",
            data=UpdateConversationConfigRequest(llm_model_override="gpt-test"),
            request=request,
            project_id="project-1",
            current_user=current_user,
            tenant_id="tenant-1",
            db=SimpleNamespace(rollback=AsyncMock()),
        ),
        "mode": lambda: conversations_router.update_conversation_mode(
            conversation_id="conversation-1",
            data=UpdateConversationModeRequest(conversation_mode="single_agent"),
            request=request,
            project_id="project-1",
            current_user=current_user,
            tenant_id="tenant-1",
            db=SimpleNamespace(rollback=AsyncMock()),
        ),
        "generate_title": lambda: conversations_router.generate_conversation_title(
            conversation_id="conversation-1",
            request=request,
            project_id="project-1",
            current_user=current_user,
            tenant_id="tenant-1",
            db=SimpleNamespace(),
        ),
        "summary": lambda: conversations_router.generate_summary(
            conversation_id="conversation-1",
            request=request,
            project_id="project-1",
            current_user=current_user,
            tenant_id="tenant-1",
            db=SimpleNamespace(),
        ),
    }

    with pytest.raises(HTTPException) as exc_info:
        await route_calls[route_name]()

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == expected_detail
    assert "internal" not in exc_info.value.detail


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_conversations_expands_workspace_group_and_names(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = WorkspaceModel(
        id="ws-group",
        tenant_id="tenant-1",
        project_id="project-1",
        name="Grouped Workspace",
        created_by="user-1",
    )
    grouped_row = DBConversation(
        id="workspace-worker:ws-group:task-2:agent-1:attempt-1",
        project_id="project-1",
        tenant_id="tenant-1",
        user_id="user-1",
        title="Workspace Worker - task-2",
        status=ConversationStatus.ACTIVE.value,
        agent_config={},
        meta={},
        message_count=0,
        created_at=datetime.now(UTC),
        current_mode="build",
        participant_agents=[],
    )
    db_session.add_all([workspace, grouped_row])
    await db_session.flush()

    base_conversation = Conversation(
        id="workspace-verifier:ws-group:task-1:agent-1:attempt-1",
        project_id="project-1",
        tenant_id="tenant-1",
        user_id="user-1",
        title="Workspace Verification Gate - task-1",
        status=ConversationStatus.ACTIVE,
        created_at=datetime.now(UTC),
    )
    use_case = ListUseCase([base_conversation], total=2)
    container = SimpleNamespace(list_conversations_use_case=lambda _llm: use_case)
    request = _request_with_container(container)
    monkeypatch.setattr(
        conversations_router, "get_container_with_db", lambda _request, _db: container
    )

    response = await conversations_router.list_conversations(
        request=request,
        project_id="project-1",
        status="active",
        limit=1,
        offset=0,
        workspace_id=None,
        group_by_workspace=True,
        current_user=SimpleNamespace(id="user-1"),
        tenant_id="tenant-1",
        db=db_session,
    )

    assert [item.id for item in response.items] == [
        "workspace-verifier:ws-group:task-1:agent-1:attempt-1",
        "workspace-worker:ws-group:task-2:agent-1:attempt-1",
    ]
    assert {item.workspace_name for item in response.items} == {"Grouped Workspace"}
    assert {item.workspace_id for item in response.items} == {"ws-group"}
    assert response.next_offset == 1
    assert response.has_more is False


def test_list_conversations_accepts_large_workspace_refresh_pages() -> None:
    limit_param = inspect.signature(conversations_router.list_conversations).parameters[
        "limit"
    ].default

    assert any(getattr(metadata, "le", None) == 500 for metadata in limit_param.metadata)


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("route_name", "expected_detail"),
    [
        ("fork", "Failed to fork conversation"),
        ("edit_message", "Failed to edit message"),
        ("tool_undo", "Failed to request tool undo"),
    ],
)
async def test_db_backed_conversation_routes_sanitize_internal_errors(
    route_name: str,
    expected_detail: str,
) -> None:
    current_user = SimpleNamespace(id="user-1")
    db = FailingDb()
    route_calls: dict[str, Any] = {
        "fork": lambda: conversations_router.fork_conversation(
            conversation_id="conversation-1",
            message_id="message-1",
            current_user=current_user,
            db=db,
        ),
        "edit_message": lambda: conversations_router.edit_message(
            conversation_id="conversation-1",
            message_id="message-1",
            data={"content": "updated"},
            current_user=current_user,
            db=db,
        ),
        "tool_undo": lambda: conversations_router.request_tool_undo(
            conversation_id="conversation-1",
            execution_id="execution-1",
            current_user=current_user,
            db=db,
        ),
    }

    with pytest.raises(HTTPException) as exc_info:
        await route_calls[route_name]()

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == expected_detail
    assert "internal" not in exc_info.value.detail


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_conversation_validation_errors_are_sanitized() -> None:
    class FailingCreateUseCase:
        async def execute(self, **_kwargs: Any) -> Any:
            raise ValueError("internal project validation secret")

    container = SimpleNamespace(
        create_conversation_use_case=lambda _llm: FailingCreateUseCase(),
    )
    db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())

    with pytest.raises(HTTPException) as exc_info:
        await conversations_router.create_conversation(
            data=CreateConversationRequest(project_id="project-1"),
            request=_request_with_container(container),
            current_user=SimpleNamespace(id="user-1"),
            tenant_id="tenant-1",
            db=db,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid request"
    assert "internal" not in exc_info.value.detail
    db.rollback.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_conversation_invariant_errors_are_sanitized() -> None:
    conversation = SimpleNamespace(
        conversation_mode="autonomous",
        workspace_id=None,
        participant_agents=[],
        assert_autonomous_invariants=MagicMock(
            side_effect=ConversationDomainError("secret autonomous invariant")
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        await conversations_router._enforce_conversation_invariants(
            conversation,
            container=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "Invalid conversation state"
    assert "secret" not in exc_info.value.detail


@pytest.mark.unit
@pytest.mark.asyncio
async def test_workspace_roster_invariant_errors_are_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingValidator:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        async def assert_valid(self, _conversation: object) -> None:
            raise ParticipantNotPresentError("secret workspace roster mismatch")

    monkeypatch.setattr(
        "src.application.services.agent.workspace_roster_validator.WorkspaceRosterValidator",
        FailingValidator,
    )
    conversation = SimpleNamespace(
        conversation_mode=None,
        workspace_id="workspace-1",
        participant_agents=["secret-agent"],
    )

    with pytest.raises(HTTPException) as exc_info:
        await conversations_router._enforce_conversation_invariants(
            conversation,
            container=SimpleNamespace(workspace_agent_repository=lambda: object()),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "Invalid workspace roster"
    assert "secret" not in exc_info.value.detail


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_conversation_mode_value_errors_are_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation = SimpleNamespace(
        conversation_mode=None,
        workspace_id=None,
        linked_workspace_task_id=None,
        participant_agents=[],
        updated_at=None,
        assert_autonomous_invariants=MagicMock(),
    )
    agent_service = SimpleNamespace(
        get_conversation=AsyncMock(return_value=conversation),
        _conversation_repo=SimpleNamespace(
            save=AsyncMock(side_effect=ValueError("secret persistence validation"))
        ),
    )
    container = SimpleNamespace(agent_service=lambda _llm: agent_service)
    db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    monkeypatch.setattr(
        conversations_router,
        "get_container_with_db",
        lambda _request, _db: container,
    )

    with pytest.raises(HTTPException) as exc_info:
        await conversations_router.update_conversation_mode(
            conversation_id="conversation-1",
            data=UpdateConversationModeRequest(conversation_mode="single_agent"),
            request=MagicMock(),
            project_id="project-1",
            current_user=SimpleNamespace(id="user-1"),
            tenant_id="tenant-1",
            db=db,
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "Invalid conversation mode update"
    assert "secret" not in exc_info.value.detail
    db.rollback.assert_awaited_once()
