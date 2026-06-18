"""Tests for conversation route hardening."""

import inspect
from datetime import UTC, datetime, timedelta
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
    AgentExecutionEvent as DBAgentExecutionEvent,
    Conversation as DBConversation,
    Project,
    UserProject,
    WorkspaceMemberModel,
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


def _db_with_project_access(
    *, allowed: bool = True, tenant_id: str = "tenant-1"
) -> SimpleNamespace:
    return SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(scalar_one_or_none=lambda: tenant_id if allowed else None)
        ),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )


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
    db = _db_with_project_access()

    route_calls: dict[str, Any] = {
        "list": lambda: conversations_router.list_conversations(
            request=request,
            project_id="project-1",
            status=None,
            limit=50,
            offset=0,
            current_user=current_user,
            tenant_id="tenant-1",
            db=db,
        ),
        "get": lambda: conversations_router.get_conversation(
            conversation_id="conversation-1",
            request=request,
            project_id="project-1",
            current_user=current_user,
            tenant_id="tenant-1",
            db=db,
        ),
        "context_status": lambda: conversations_router.get_context_status(
            conversation_id="conversation-1",
            request=request,
            project_id="project-1",
            current_user=current_user,
            tenant_id="tenant-1",
            db=db,
        ),
        "delete": lambda: conversations_router.delete_conversation(
            conversation_id="conversation-1",
            request=request,
            project_id="project-1",
            current_user=current_user,
            tenant_id="tenant-1",
            db=db,
        ),
        "title": lambda: conversations_router.update_conversation_title(
            conversation_id="conversation-1",
            data=UpdateConversationTitleRequest(title="New title"),
            request=request,
            project_id="project-1",
            current_user=current_user,
            tenant_id="tenant-1",
            db=db,
        ),
        "config": lambda: conversations_router.update_conversation_config(
            conversation_id="conversation-1",
            data=UpdateConversationConfigRequest(llm_model_override="gpt-test"),
            request=request,
            project_id="project-1",
            current_user=current_user,
            tenant_id="tenant-1",
            db=db,
        ),
        "mode": lambda: conversations_router.update_conversation_mode(
            conversation_id="conversation-1",
            data=UpdateConversationModeRequest(conversation_mode="single_agent"),
            request=request,
            project_id="project-1",
            current_user=current_user,
            tenant_id="tenant-1",
            db=db,
        ),
        "generate_title": lambda: conversations_router.generate_conversation_title(
            conversation_id="conversation-1",
            request=request,
            project_id="project-1",
            current_user=current_user,
            tenant_id="tenant-1",
            db=db,
        ),
        "summary": lambda: conversations_router.generate_summary(
            conversation_id="conversation-1",
            request=request,
            project_id="project-1",
            current_user=current_user,
            tenant_id="tenant-1",
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
    db_session.add(
        WorkspaceMemberModel(
            id="wm-ws-group-user-1",
            workspace_id="ws-group",
            user_id="user-1",
            role="viewer",
            invited_by="user-1",
        )
    )
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
    monkeypatch.setattr(
        conversations_router, "_ensure_project_access", AsyncMock(return_value="tenant-1")
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


@pytest.mark.unit
@pytest.mark.asyncio
async def test_grouped_workspace_conversations_use_stable_activity_order(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = WorkspaceModel(
        id="ws-stable-order",
        tenant_id="tenant-1",
        project_id="project-1",
        name="Stable Workspace",
        created_by="user-1",
    )
    old_time = datetime.now(UTC) - timedelta(days=2)
    base_time = datetime.now(UTC)
    rows = [
        DBConversation(
            id="workspace-worker:ws-stable-order:task-old:agent-1:attempt-1",
            project_id="project-1",
            tenant_id="tenant-1",
            user_id="user-1",
            title="Old created but active",
            status=ConversationStatus.ACTIVE.value,
            agent_config={},
            meta={},
            message_count=0,
            created_at=old_time,
            updated_at=old_time,
            current_mode="build",
            participant_agents=[],
        ),
        DBConversation(
            id="workspace-worker:ws-stable-order:task-b:agent-1:attempt-1",
            project_id="project-1",
            tenant_id="tenant-1",
            user_id="user-1",
            title="Tie B",
            status=ConversationStatus.ACTIVE.value,
            agent_config={},
            meta={},
            message_count=0,
            created_at=old_time,
            updated_at=base_time,
            current_mode="build",
            participant_agents=[],
        ),
        DBConversation(
            id="workspace-worker:ws-stable-order:task-a:agent-1:attempt-1",
            project_id="project-1",
            tenant_id="tenant-1",
            user_id="user-1",
            title="Tie A",
            status=ConversationStatus.ACTIVE.value,
            agent_config={},
            meta={},
            message_count=0,
            created_at=old_time,
            updated_at=base_time,
            current_mode="build",
            participant_agents=[],
        ),
    ]
    db_session.add_all([workspace, *rows])
    db_session.add(
        WorkspaceMemberModel(
            id="wm-ws-stable-order-user-1",
            workspace_id="ws-stable-order",
            user_id="user-1",
            role="viewer",
            invited_by="user-1",
        )
    )
    db_session.add_all(
        [
            DBAgentExecutionEvent(
                id="event-router-stable-old-newer",
                conversation_id="workspace-worker:ws-stable-order:task-old:agent-1:attempt-1",
                message_id="message-router-stable-old-newer",
                event_type="assistant_message",
                event_data={},
                event_time_us=2_000_000,
                event_counter=0,
            ),
            DBAgentExecutionEvent(
                id="event-router-stable-a",
                conversation_id="workspace-worker:ws-stable-order:task-a:agent-1:attempt-1",
                message_id="message-router-stable-a",
                event_type="assistant_message",
                event_data={},
                event_time_us=1_000_000,
                event_counter=0,
            ),
            DBAgentExecutionEvent(
                id="event-router-stable-b",
                conversation_id="workspace-worker:ws-stable-order:task-b:agent-1:attempt-1",
                message_id="message-router-stable-b",
                event_type="assistant_message",
                event_data={},
                event_time_us=1_000_000,
                event_counter=0,
            ),
        ]
    )
    await db_session.flush()

    container = SimpleNamespace(list_conversations_use_case=lambda _llm: ListUseCase([], total=3))
    monkeypatch.setattr(
        conversations_router, "get_container_with_db", lambda _request, _db: container
    )
    monkeypatch.setattr(
        conversations_router, "_ensure_project_access", AsyncMock(return_value="tenant-1")
    )

    response = await conversations_router.list_conversations(
        request=_request_with_container(container),
        project_id="project-1",
        status="active",
        limit=10,
        offset=0,
        workspace_id="ws-stable-order",
        group_by_workspace=True,
        current_user=SimpleNamespace(id="user-1"),
        tenant_id="tenant-1",
        db=db_session,
    )

    assert [item.id for item in response.items] == [
        "workspace-worker:ws-stable-order:task-old:agent-1:attempt-1",
        "workspace-worker:ws-stable-order:task-b:agent-1:attempt-1",
        "workspace-worker:ws-stable-order:task-a:agent-1:attempt-1",
    ]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_workspace_conversations_requires_workspace_membership(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = Project(
        id="project-workspace-list",
        tenant_id="tenant-workspace-list",
        name="Workspace list project",
        description="Conversation list membership test",
        owner_id="owner-user",
        memory_rules={},
        graph_config={},
    )
    workspace = WorkspaceModel(
        id="ws-list-private",
        tenant_id="tenant-workspace-list",
        project_id="project-workspace-list",
        name="Private Workspace",
        created_by="owner-user",
    )
    db_session.add_all(
        [
            project,
            workspace,
            UserProject(
                id="up-workspace-list-viewer",
                user_id="user-1",
                project_id="project-workspace-list",
                role="viewer",
            ),
        ]
    )
    await db_session.flush()

    container = SimpleNamespace(list_conversations_use_case=lambda _llm: ListUseCase([], total=0))
    monkeypatch.setattr(
        conversations_router, "get_container_with_db", lambda _request, _db: container
    )

    with pytest.raises(HTTPException) as exc_info:
        await conversations_router.list_conversations(
            request=_request_with_container(container),
            project_id="project-workspace-list",
            status=None,
            limit=10,
            offset=0,
            workspace_id="ws-list-private",
            group_by_workspace=False,
            current_user=SimpleNamespace(id="user-1"),
            tenant_id="tenant-workspace-list",
            db=db_session,
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Workspace access required"


def test_list_conversations_accepts_large_workspace_refresh_pages() -> None:
    limit_param = (
        inspect.signature(conversations_router.list_conversations).parameters["limit"].default
    )

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
            tenant_id="tenant-1",
            db=db,
        ),
        "edit_message": lambda: conversations_router.edit_message(
            conversation_id="conversation-1",
            message_id="message-1",
            data={"content": "updated"},
            current_user=current_user,
            tenant_id="tenant-1",
            db=db,
        ),
        "tool_undo": lambda: conversations_router.request_tool_undo(
            conversation_id="conversation-1",
            execution_id="execution-1",
            current_user=current_user,
            tenant_id="tenant-1",
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
@pytest.mark.parametrize("route_name", ["fork", "edit_message", "tool_undo"])
async def test_db_backed_conversation_routes_reject_non_owner(
    route_name: str,
    db_session: AsyncSession,
) -> None:
    db_session.add(
        DBConversation(
            id="conversation-owned-elsewhere",
            project_id="project-1",
            tenant_id="tenant-1",
            user_id="other-user",
            title="Private conversation",
            status=ConversationStatus.ACTIVE.value,
            agent_config={},
            meta={},
            message_count=0,
            created_at=datetime.now(UTC),
            current_mode="build",
            participant_agents=[],
        )
    )
    await db_session.flush()

    current_user = SimpleNamespace(id="user-1")
    route_calls: dict[str, Any] = {
        "fork": lambda: conversations_router.fork_conversation(
            conversation_id="conversation-owned-elsewhere",
            message_id="message-1",
            current_user=current_user,
            tenant_id="tenant-1",
            db=db_session,
        ),
        "edit_message": lambda: conversations_router.edit_message(
            conversation_id="conversation-owned-elsewhere",
            message_id="message-1",
            data={"content": "updated"},
            current_user=current_user,
            tenant_id="tenant-1",
            db=db_session,
        ),
        "tool_undo": lambda: conversations_router.request_tool_undo(
            conversation_id="conversation-owned-elsewhere",
            execution_id="execution-1",
            current_user=current_user,
            tenant_id="tenant-1",
            db=db_session,
        ),
    }

    with pytest.raises(HTTPException) as exc_info:
        await route_calls[route_name]()

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Access denied"


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("route_name", ["fork", "edit_message", "tool_undo"])
async def test_db_backed_conversation_routes_require_project_access_for_owner(
    route_name: str,
    db_session: AsyncSession,
) -> None:
    db_session.add(
        Project(
            id="project-private",
            tenant_id="tenant-1",
            name="Private project",
            description="Project without current user membership",
            owner_id="other-user",
            memory_rules={},
            graph_config={},
        )
    )
    db_session.add(
        DBConversation(
            id="conversation-owned-without-project",
            project_id="project-private",
            tenant_id="tenant-1",
            user_id="user-1",
            title="Former project conversation",
            status=ConversationStatus.ACTIVE.value,
            agent_config={},
            meta={},
            message_count=0,
            created_at=datetime.now(UTC),
            current_mode="build",
            participant_agents=[],
        )
    )
    await db_session.flush()

    current_user = SimpleNamespace(id="user-1")
    route_calls: dict[str, Any] = {
        "fork": lambda: conversations_router.fork_conversation(
            conversation_id="conversation-owned-without-project",
            message_id="message-1",
            current_user=current_user,
            tenant_id="tenant-1",
            db=db_session,
        ),
        "edit_message": lambda: conversations_router.edit_message(
            conversation_id="conversation-owned-without-project",
            message_id="message-1",
            data={"content": "updated"},
            current_user=current_user,
            tenant_id="tenant-1",
            db=db_session,
        ),
        "tool_undo": lambda: conversations_router.request_tool_undo(
            conversation_id="conversation-owned-without-project",
            execution_id="execution-1",
            current_user=current_user,
            tenant_id="tenant-1",
            db=db_session,
        ),
    }

    with pytest.raises(HTTPException) as exc_info:
        await route_calls[route_name]()

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Access denied"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_conversation_validation_errors_are_sanitized() -> None:
    class FailingCreateUseCase:
        async def execute(self, **_kwargs: Any) -> Any:
            raise ValueError("internal project validation secret")

    container = SimpleNamespace(
        create_conversation_use_case=lambda _llm: FailingCreateUseCase(),
    )
    db = _db_with_project_access()

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
async def test_create_conversation_requires_project_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = SimpleNamespace(create_conversation_use_case=lambda _llm: object())
    get_container = MagicMock(return_value=container)
    monkeypatch.setattr(conversations_router, "get_container_with_db", get_container)
    db = _db_with_project_access(allowed=False)

    with pytest.raises(HTTPException) as exc_info:
        await conversations_router.create_conversation(
            data=CreateConversationRequest(project_id="project-1"),
            request=_request_with_container(container),
            current_user=SimpleNamespace(id="user-1"),
            tenant_id="tenant-1",
            db=db,
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Access denied"
    get_container.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_conversation_rejects_inaccessible_selected_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_use_case = SimpleNamespace(execute=AsyncMock())
    registry = SimpleNamespace(get_by_id=AsyncMock(return_value=None))
    container = SimpleNamespace(
        agent_registry=lambda: registry,
        create_conversation_use_case=lambda _llm: create_use_case,
    )
    monkeypatch.setattr(
        conversations_router, "get_container_with_db", lambda _request, _db: container
    )
    db = _db_with_project_access()

    with pytest.raises(HTTPException) as exc_info:
        await conversations_router.create_conversation(
            data=CreateConversationRequest(
                project_id="project-1",
                agent_config={"selected_agent_id": "agent-from-another-project"},
            ),
            request=_request_with_container(container),
            current_user=SimpleNamespace(id="user-1"),
            tenant_id="tenant-1",
            db=db,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid agent selection"
    registry.get_by_id.assert_awaited_once_with(
        "agent-from-another-project",
        tenant_id="tenant-1",
        project_id="project-1",
    )
    create_use_case.execute.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_conversation_uses_authorized_project_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CapturingCreateUseCase:
        def __init__(self) -> None:
            self.kwargs: dict[str, Any] | None = None

        async def execute(self, **kwargs: Any) -> Conversation:
            self.kwargs = kwargs
            return Conversation(
                id="conversation-cross-tenant",
                project_id=kwargs["project_id"],
                tenant_id=kwargs["tenant_id"],
                user_id=kwargs["user_id"],
                title=kwargs["title"] or "Cross tenant",
                status=ConversationStatus.ACTIVE,
                created_at=datetime.now(UTC),
            )

    create_use_case = CapturingCreateUseCase()
    container = SimpleNamespace(
        create_conversation_use_case=lambda _llm: create_use_case,
        redis=lambda: None,
    )
    monkeypatch.setattr(
        conversations_router, "get_container_with_db", lambda _request, _db: container
    )
    db = _db_with_project_access(tenant_id="tenant-project")

    response = await conversations_router.create_conversation(
        data=CreateConversationRequest(project_id="project-1", title="Cross tenant"),
        request=_request_with_container(container),
        current_user=SimpleNamespace(id="user-1"),
        tenant_id="tenant-fallback",
        db=db,
    )

    conversations_router.create_llm_client.assert_awaited_once_with("tenant-project")
    assert create_use_case.kwargs is not None
    assert create_use_case.kwargs["tenant_id"] == "tenant-project"
    assert response.tenant_id == "tenant-project"
    db.commit.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_conversations_requires_project_access() -> None:
    db = _db_with_project_access(allowed=False)
    container = SimpleNamespace(list_conversations_use_case=lambda _llm: object())

    with pytest.raises(HTTPException) as exc_info:
        await conversations_router.list_conversations(
            request=_request_with_container(container),
            project_id="project-1",
            status=None,
            limit=50,
            offset=0,
            workspace_id=None,
            group_by_workspace=False,
            current_user=SimpleNamespace(id="user-1"),
            tenant_id="tenant-1",
            db=db,
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Access denied"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_conversations_uses_authorized_project_tenant(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CapturingListUseCase:
        def __init__(self) -> None:
            self.execute_kwargs: dict[str, Any] | None = None
            self.count_kwargs: dict[str, Any] | None = None

        async def execute(self, **kwargs: Any) -> list[Conversation]:
            self.execute_kwargs = kwargs
            return []

        async def count(self, **kwargs: Any) -> int:
            self.count_kwargs = kwargs
            return 0

    project = Project(
        id="project-cross-tenant-list",
        tenant_id="tenant-project",
        name="Cross tenant list project",
        description="Conversation list tenant resolution test",
        owner_id="owner-user",
        memory_rules={},
        graph_config={},
    )
    db_session.add_all(
        [
            project,
            UserProject(
                id="up-cross-tenant-list",
                user_id="user-1",
                project_id=project.id,
                role="viewer",
            ),
        ]
    )
    await db_session.flush()

    list_use_case = CapturingListUseCase()
    container = SimpleNamespace(list_conversations_use_case=lambda _llm: list_use_case)
    monkeypatch.setattr(
        conversations_router, "get_container_with_db", lambda _request, _db: container
    )

    response = await conversations_router.list_conversations(
        request=_request_with_container(container),
        project_id=project.id,
        status=None,
        limit=50,
        offset=0,
        workspace_id=None,
        group_by_workspace=False,
        current_user=SimpleNamespace(id="user-1"),
        tenant_id="tenant-fallback",
        db=db_session,
    )

    conversations_router.create_llm_client.assert_awaited_once_with("tenant-project")
    assert list_use_case.execute_kwargs == {
        "project_id": project.id,
        "user_id": "user-1",
        "limit": 50,
        "offset": 0,
        "status": None,
    }
    assert list_use_case.count_kwargs == {
        "project_id": project.id,
        "user_id": "user-1",
        "status": None,
    }
    assert response.items == []
    assert response.total == 0


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "route_name",
    [
        "get",
        "context_status",
        "delete",
        "title",
        "config",
        "mode",
        "generate_title",
        "summary",
    ],
)
async def test_project_scoped_conversation_routes_require_project_access(
    route_name: str,
) -> None:
    container = SimpleNamespace(
        get_conversation_use_case=lambda _llm: object(),
        agent_service=lambda _llm: object(),
    )
    request = _request_with_container(container)
    db = _db_with_project_access(allowed=False)
    current_user = SimpleNamespace(id="user-1")
    route_calls: dict[str, Any] = {
        "get": lambda: conversations_router.get_conversation(
            conversation_id="conversation-1",
            request=request,
            project_id="project-1",
            current_user=current_user,
            tenant_id="tenant-1",
            db=db,
        ),
        "context_status": lambda: conversations_router.get_context_status(
            conversation_id="conversation-1",
            request=request,
            project_id="project-1",
            current_user=current_user,
            tenant_id="tenant-1",
            db=db,
        ),
        "delete": lambda: conversations_router.delete_conversation(
            conversation_id="conversation-1",
            request=request,
            project_id="project-1",
            current_user=current_user,
            tenant_id="tenant-1",
            db=db,
        ),
        "title": lambda: conversations_router.update_conversation_title(
            conversation_id="conversation-1",
            data=UpdateConversationTitleRequest(title="New title"),
            request=request,
            project_id="project-1",
            current_user=current_user,
            tenant_id="tenant-1",
            db=db,
        ),
        "config": lambda: conversations_router.update_conversation_config(
            conversation_id="conversation-1",
            data=UpdateConversationConfigRequest(llm_model_override="gpt-test"),
            request=request,
            project_id="project-1",
            current_user=current_user,
            tenant_id="tenant-1",
            db=db,
        ),
        "mode": lambda: conversations_router.update_conversation_mode(
            conversation_id="conversation-1",
            data=UpdateConversationModeRequest(conversation_mode="single_agent"),
            request=request,
            project_id="project-1",
            current_user=current_user,
            tenant_id="tenant-1",
            db=db,
        ),
        "generate_title": lambda: conversations_router.generate_conversation_title(
            conversation_id="conversation-1",
            request=request,
            project_id="project-1",
            current_user=current_user,
            tenant_id="tenant-1",
            db=db,
        ),
        "summary": lambda: conversations_router.generate_summary(
            conversation_id="conversation-1",
            request=request,
            project_id="project-1",
            current_user=current_user,
            tenant_id="tenant-1",
            db=db,
        ),
    }

    with pytest.raises(HTTPException) as exc_info:
        await route_calls[route_name]()

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Access denied"
    request.app.state.container.with_db.assert_not_called()


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
    db = _db_with_project_access()
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
