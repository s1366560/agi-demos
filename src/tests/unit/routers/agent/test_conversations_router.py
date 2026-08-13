"""Tests for conversation route hardening."""

import inspect
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.configuration.workspace_core import WorkspaceCoreSettings
from src.domain.model.agent import Conversation, ConversationStatus
from src.domain.model.agent.conversation.errors import ConversationDomainError
from src.domain.ports.services.workspace_authority_port import (
    WorkspaceAuthorityAccessDeniedError,
    WorkspaceAuthorityProfile,
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
)
from src.infrastructure.workspace_core.authority import AvernetWorkspaceAuthority
from src.infrastructure.workspace_core.client import WorkspaceCoreClient


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


class FakeWorkspaceAuthority:
    def __init__(
        self,
        *,
        names: dict[str, str] | None = None,
        denied: bool = False,
        linked_tasks: bool = True,
    ) -> None:
        self._names = names or {}
        self._denied = denied
        self._linked_tasks = linked_tasks
        self.get_profile = AsyncMock(side_effect=self._get_profile)
        self.accessible_profiles = AsyncMock(side_effect=self._accessible_profiles)
        self.has_task = AsyncMock(return_value=linked_tasks)

    async def _get_profile(self, scope: object) -> WorkspaceAuthorityProfile:
        if self._denied:
            raise WorkspaceAuthorityAccessDeniedError
        workspace_id = str(scope.workspace_id)
        return WorkspaceAuthorityProfile(
            workspace_id=workspace_id,
            tenant_id=str(scope.tenant_id),
            project_id=str(scope.project_id),
            name=self._names.get(workspace_id, workspace_id),
            created_by="owner-1",
            is_archived=False,
            metadata={},
        )

    async def _accessible_profiles(
        self,
        *,
        tenant_id: str,
        project_id: str,
        workspace_ids: set[str],
        **_kwargs: object,
    ) -> dict[str, WorkspaceAuthorityProfile]:
        if self._denied:
            return {}
        return {
            workspace_id: WorkspaceAuthorityProfile(
                workspace_id=workspace_id,
                tenant_id=tenant_id,
                project_id=project_id,
                name=self._names.get(workspace_id, workspace_id),
                created_by="owner-1",
                is_archived=False,
                metadata={},
            )
            for workspace_id in workspace_ids
        }


def _request_with_container(
    container: object,
    *,
    authority: object | None = None,
) -> MagicMock:
    request = MagicMock()
    request.app.state.container.with_db.return_value = container
    request.app.state.workspace_authority = authority or FakeWorkspaceAuthority()
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
    db_session.add(grouped_row)
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
    request = _request_with_container(
        container,
        authority=FakeWorkspaceAuthority(names={"ws-group": "Grouped Workspace"}),
    )
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
async def test_create_conversation_persists_authorized_workspace_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = Conversation(
        id="conversation-workspace-linked",
        project_id="project-1",
        tenant_id="tenant-1",
        user_id="user-1",
        title="Workspace-linked conversation",
        status=ConversationStatus.ACTIVE,
        created_at=datetime.now(UTC),
        workspace_id="workspace-core-only",
    )
    use_case = SimpleNamespace(execute=AsyncMock(return_value=created))
    container = SimpleNamespace(
        create_conversation_use_case=lambda _llm: use_case, redis=lambda: None
    )
    request = MagicMock()
    monkeypatch.setattr(
        conversations_router, "get_container_with_db", lambda _request, _db: container
    )
    monkeypatch.setattr(
        conversations_router, "_ensure_project_access", AsyncMock(return_value="tenant-1")
    )
    membership = AsyncMock()
    monkeypatch.setattr(conversations_router, "_ensure_workspace_access", membership)
    db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())

    response = await conversations_router.create_conversation(
        data=CreateConversationRequest(
            project_id="project-1",
            title="Workspace-linked conversation",
            workspace_id="workspace-core-only",
        ),
        request=request,
        current_user=SimpleNamespace(id="user-1"),
        tenant_id="tenant-1",
        db=db,
    )

    membership.assert_awaited_once()
    use_case.execute.assert_awaited_once_with(
        project_id="project-1",
        user_id="user-1",
        tenant_id="tenant-1",
        title="Workspace-linked conversation",
        agent_config=None,
        workspace_id="workspace-core-only",
    )
    assert response.workspace_id == "workspace-core-only"
    db.commit.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_conversations_caps_workspace_group_expansion(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_session.add_all(
        [
            DBConversation(
                id=f"workspace-worker:ws-large-group:task-{index}:agent-1:attempt-1",
                project_id="project-1",
                tenant_id="tenant-1",
                user_id="user-1",
                title=f"Workspace Worker - task-{index}",
                status=ConversationStatus.ACTIVE.value,
                agent_config={},
                meta={},
                message_count=0,
                created_at=datetime.now(UTC) - timedelta(minutes=index),
                current_mode="build",
                participant_agents=[],
            )
            for index in range(80)
        ]
    )
    await db_session.flush()

    base_conversation = Conversation(
        id="workspace-verifier:ws-large-group:task-base:agent-1:attempt-1",
        project_id="project-1",
        tenant_id="tenant-1",
        user_id="user-1",
        title="Workspace Verification Gate - task-base",
        status=ConversationStatus.ACTIVE,
        created_at=datetime.now(UTC),
    )
    use_case = ListUseCase([base_conversation], total=81)
    container = SimpleNamespace(list_conversations_use_case=lambda _llm: use_case)
    monkeypatch.setattr(
        conversations_router, "get_container_with_db", lambda _request, _db: container
    )
    monkeypatch.setattr(
        conversations_router, "_ensure_project_access", AsyncMock(return_value="tenant-1")
    )

    response = await conversations_router.list_conversations(
        request=_request_with_container(
            container,
            authority=FakeWorkspaceAuthority(names={"ws-large-group": "Large Workspace"}),
        ),
        project_id="project-1",
        status="active",
        limit=5,
        offset=0,
        workspace_id=None,
        group_by_workspace=True,
        current_user=SimpleNamespace(id="user-1"),
        tenant_id="tenant-1",
        db=db_session,
    )

    assert conversations_router._workspace_group_expansion_limit(5) == 5
    assert len(response.items) == 1 + conversations_router._workspace_group_expansion_limit(5)
    assert len(response.items) < 81
    assert response.items[0].id == "workspace-verifier:ws-large-group:task-base:agent-1:attempt-1"
    assert {item.workspace_id for item in response.items} == {"ws-large-group"}
    assert response.has_more is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_conversations_filters_unbound_before_pagination(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    db_session.add_all(
        [
            DBConversation(
                id=f"conversation-unbound-{index}",
                project_id="project-1",
                tenant_id="tenant-1",
                user_id="user-1",
                title=f"Unbound {index}",
                status=ConversationStatus.ACTIVE.value,
                agent_config={},
                meta={},
                message_count=0,
                created_at=now - timedelta(minutes=index),
                current_mode="build",
                participant_agents=[],
            )
            for index in range(3)
        ]
    )
    db_session.add_all(
        [
            DBConversation(
                id="conversation-unbound-blank-metadata",
                project_id="project-1",
                tenant_id="tenant-1",
                user_id="user-1",
                title="Blank metadata is unbound",
                status=ConversationStatus.ACTIVE.value,
                agent_config={},
                meta={"workspace_id": "   "},
                message_count=0,
                created_at=now - timedelta(minutes=3),
                current_mode="build",
                participant_agents=[],
            ),
            DBConversation(
                id="workspace-orphan",
                project_id="project-1",
                tenant_id="tenant-1",
                user_id="user-1",
                title="Legacy prefix without delimiter is unbound",
                status=ConversationStatus.ACTIVE.value,
                agent_config={},
                meta={},
                message_count=0,
                created_at=now - timedelta(minutes=4),
                current_mode="build",
                participant_agents=[],
            ),
            DBConversation(
                id="conversation-bound-metadata",
                project_id="project-1",
                tenant_id="tenant-1",
                user_id="user-1",
                title="Metadata bound",
                status=ConversationStatus.ACTIVE.value,
                agent_config={},
                meta={"workspace_id": "ws-metadata"},
                message_count=0,
                created_at=now + timedelta(minutes=1),
                current_mode="build",
                participant_agents=[],
            ),
            DBConversation(
                id="workspace-worker:ws-legacy:task-1:agent-1:attempt-1",
                project_id="project-1",
                tenant_id="tenant-1",
                user_id="user-1",
                title="Legacy bound",
                status=ConversationStatus.ACTIVE.value,
                agent_config={},
                meta={},
                message_count=0,
                created_at=now + timedelta(minutes=2),
                current_mode="build",
                participant_agents=[],
            ),
            DBConversation(
                id="conversation-unbound-archived",
                project_id="project-1",
                tenant_id="tenant-1",
                user_id="user-1",
                title="Archived unbound",
                status=ConversationStatus.ARCHIVED.value,
                agent_config={},
                meta={},
                message_count=0,
                created_at=now + timedelta(minutes=3),
                current_mode="build",
                participant_agents=[],
            ),
            DBConversation(
                id="conversation-unbound-other-user",
                project_id="project-1",
                tenant_id="tenant-1",
                user_id="user-2",
                title="Another user's unbound conversation",
                status=ConversationStatus.ACTIVE.value,
                agent_config={},
                meta={},
                message_count=0,
                created_at=now + timedelta(minutes=4),
                current_mode="build",
                participant_agents=[],
            ),
        ]
    )
    await db_session.flush()

    use_case = ListUseCase([], total=6)
    container = SimpleNamespace(list_conversations_use_case=lambda _llm: use_case)
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
        limit=2,
        offset=1,
        workspace_id=None,
        unbound_only=True,
        group_by_workspace=False,
        current_user=SimpleNamespace(id="user-1"),
        tenant_id="tenant-1",
        db=db_session,
    )

    assert [item.id for item in response.items] == [
        "conversation-unbound-1",
        "conversation-unbound-2",
    ]
    assert {item.workspace_id for item in response.items} == {None}
    assert response.total == 5
    assert response.offset == 1
    assert response.limit == 2
    assert response.next_offset == 3
    assert response.has_more is True

    final_page = await conversations_router.list_conversations(
        request=_request_with_container(container),
        project_id="project-1",
        status="active",
        limit=2,
        offset=3,
        workspace_id=None,
        unbound_only=True,
        group_by_workspace=False,
        current_user=SimpleNamespace(id="user-1"),
        tenant_id="tenant-1",
        db=db_session,
    )

    assert [item.id for item in final_page.items] == [
        "conversation-unbound-blank-metadata",
        "workspace-orphan",
    ]
    assert final_page.total == 5
    assert final_page.next_offset == 5
    assert final_page.has_more is False
    conversations_router.create_llm_client.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unbound_filter_ignores_non_string_metadata_and_uses_legacy_fallback(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    malformed_metadata_values: list[object] = [
        7,
        {"nested": "ws-object"},
        ["ws-array"],
        True,
    ]
    db_session.add_all(
        [
            DBConversation(
                id=f"conversation-unbound-malformed-{index}",
                project_id="project-1",
                tenant_id="tenant-1",
                user_id="user-1",
                title=f"Malformed metadata {index}",
                status=ConversationStatus.ACTIVE.value,
                agent_config={},
                meta={"workspace_id": value},
                message_count=0,
                created_at=now - timedelta(minutes=index),
                current_mode="build",
                participant_agents=[],
            )
            for index, value in enumerate(malformed_metadata_values)
        ]
    )
    db_session.add(
        DBConversation(
            id="workspace-worker:ws-legacy-malformed:task-1:agent-1:attempt-1",
            project_id="project-1",
            tenant_id="tenant-1",
            user_id="user-1",
            title="Legacy fallback with malformed metadata",
            status=ConversationStatus.ACTIVE.value,
            agent_config={},
            meta={"workspace_id": {"not": "text"}},
            message_count=0,
            created_at=now + timedelta(minutes=1),
            current_mode="build",
            participant_agents=[],
        )
    )
    await db_session.flush()

    container = SimpleNamespace(list_conversations_use_case=lambda _llm: ListUseCase([], total=5))
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
        workspace_id=None,
        unbound_only=True,
        group_by_workspace=False,
        current_user=SimpleNamespace(id="user-1"),
        tenant_id="tenant-1",
        db=db_session,
    )

    assert {item.id for item in response.items} == {
        "conversation-unbound-malformed-0",
        "conversation-unbound-malformed-1",
        "conversation-unbound-malformed-2",
        "conversation-unbound-malformed-3",
    }
    assert {item.workspace_id for item in response.items} == {None}
    assert response.total == 4

    legacy_rows = await conversations_router._list_workspace_conversations(
        db_session,
        project_id="project-1",
        tenant_id="tenant-1",
        workspace_ids={"ws-legacy-malformed"},
        status=ConversationStatus.ACTIVE,
    )
    assert [conversation.id for conversation in legacy_rows] == [
        "workspace-worker:ws-legacy-malformed:task-1:agent-1:attempt-1"
    ]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_conversations_rejects_combined_workspace_and_unbound_filters(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        conversations_router, "_ensure_project_access", AsyncMock(return_value="tenant-1")
    )

    with pytest.raises(HTTPException) as exc_info:
        await conversations_router.list_conversations(
            request=MagicMock(),
            project_id="project-1",
            status=None,
            limit=10,
            offset=0,
            workspace_id="ws-1",
            unbound_only=True,
            group_by_workspace=False,
            current_user=SimpleNamespace(id="user-1"),
            tenant_id="tenant-1",
            db=db_session,
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "Workspace and unbound filters cannot be combined"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_workspace_filter_uses_same_precedence_as_response_projection(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    db_session.add_all(
        [
            DBConversation(
                id="conversation-column-wins",
                project_id="project-1",
                tenant_id="tenant-1",
                user_id="user-1",
                title="Column wins",
                status=ConversationStatus.ACTIVE.value,
                agent_config={},
                meta={"workspace_id": "ws-metadata"},
                message_count=0,
                created_at=now,
                current_mode="build",
                participant_agents=[],
                workspace_id="ws-column",
            ),
            DBConversation(
                id="workspace-worker:ws-legacy:task-1:agent-1:attempt-1",
                project_id="project-1",
                tenant_id="tenant-1",
                user_id="user-1",
                title="Metadata wins",
                status=ConversationStatus.ACTIVE.value,
                agent_config={},
                meta={"workspace_id": "ws-metadata"},
                message_count=0,
                created_at=now - timedelta(minutes=1),
                current_mode="build",
                participant_agents=[],
            ),
            DBConversation(
                id="workspace-chat:ws-legacy",
                project_id="project-1",
                tenant_id="tenant-1",
                user_id="user-1",
                title="Legacy fallback",
                status=ConversationStatus.ACTIVE.value,
                agent_config={},
                meta={},
                message_count=0,
                created_at=now - timedelta(minutes=2),
                current_mode="build",
                participant_agents=[],
            ),
        ]
    )
    await db_session.flush()

    column_rows = await conversations_router._list_workspace_conversations(
        db_session,
        project_id="project-1",
        tenant_id="tenant-1",
        workspace_ids={"ws-column"},
        status=ConversationStatus.ACTIVE,
    )
    metadata_rows = await conversations_router._list_workspace_conversations(
        db_session,
        project_id="project-1",
        tenant_id="tenant-1",
        workspace_ids={"ws-metadata"},
        status=ConversationStatus.ACTIVE,
    )
    legacy_rows = await conversations_router._list_workspace_conversations(
        db_session,
        project_id="project-1",
        tenant_id="tenant-1",
        workspace_ids={"ws-legacy"},
        status=ConversationStatus.ACTIVE,
    )

    assert [conversation.id for conversation in column_rows] == ["conversation-column-wins"]
    assert [conversation.id for conversation in metadata_rows] == [
        "workspace-worker:ws-legacy:task-1:agent-1:attempt-1"
    ]
    assert [conversation.id for conversation in legacy_rows] == ["workspace-chat:ws-legacy"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_grouped_workspace_conversations_use_stable_activity_order(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    db_session.add_all(rows)
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
        request=_request_with_container(
            container,
            authority=FakeWorkspaceAuthority(names={"ws-stable-order": "Stable Workspace"}),
        ),
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
    db_session.add_all(
        [
            project,
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
            request=_request_with_container(
                container,
                authority=FakeWorkspaceAuthority(denied=True),
            ),
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


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_workspace_conversations_uses_avernet_membership_authority(
    db_session: AsyncSession,
    test_project_db: Project,
    test_user: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def workspace_profile(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/workspaces/workspace-core-only")
        return httpx.Response(
            200,
            json={
                "id": "workspace-core-only",
                "tenant_id": test_project_db.tenant_id,
                "project_id": test_project_db.id,
                "name": "Core-only workspace",
                "created_by": str(test_user.id),
                "is_archived": False,
                "metadata": {},
            },
        )

    transport = httpx.MockTransport(workspace_profile)
    settings = WorkspaceCoreSettings.model_validate(
        {
            "WORKSPACE_CORE_BASE_URL": "http://workspace-core.test",
            "WORKSPACE_CORE_SERVICE_TOKEN": "service-token",
            "WORKSPACE_CORE_PROVIDER_WEBHOOK_TOKEN": "webhook-token",
            "WORKSPACE_CORE_PROVIDER_EVENT_TOKEN": "provider-token",
            "WORKSPACE_CORE_AGENT_REGISTRY_TOKEN": "registry-token",
        }
    )
    request = MagicMock()
    request.app.state.workspace_core_settings = settings
    client = WorkspaceCoreClient(settings, transport=transport)
    request.app.state.workspace_core_client = client
    request.app.state.workspace_authority = AvernetWorkspaceAuthority(client)
    container = SimpleNamespace(list_conversations_use_case=lambda _llm: ListUseCase([], total=0))
    monkeypatch.setattr(
        conversations_router, "get_container_with_db", lambda _request, _db: container
    )

    response = await conversations_router.list_conversations(
        request=request,
        project_id=test_project_db.id,
        status="active",
        limit=10,
        offset=0,
        workspace_id="workspace-core-only",
        group_by_workspace=False,
        current_user=test_user,
        tenant_id=test_project_db.tenant_id,
        db=db_session,
    )

    assert response.items == []
    assert response.total == 0


def test_list_conversations_accepts_large_workspace_refresh_pages() -> None:
    limit_param = (
        inspect.signature(conversations_router.list_conversations).parameters["limit"].default
    )

    assert any(getattr(metadata, "le", None) == 500 for metadata in limit_param.metadata)


def test_list_conversations_defaults_to_sidebar_sized_page() -> None:
    limit_param = (
        inspect.signature(conversations_router.list_conversations).parameters["limit"].default
    )

    assert limit_param.default == conversations_router.CONVERSATION_LIST_DEFAULT_LIMIT
    assert limit_param.default == 10


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
async def test_update_conversation_config_distinguishes_omitted_fields_from_explicit_null(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_config = {
        "selected_agent_id": "agent-1",
        "llm_model_override": "gpt-reasoning",
        "llm_overrides": {"temperature": 0.2, "max_tokens": 2048},
        "capability_mode": "code",
    }
    conversation = Conversation(
        id="conversation-config-clear",
        project_id="project-1",
        tenant_id="tenant-1",
        user_id="user-1",
        title="Config clear contract",
        agent_config=dict(original_config),
    )
    conversation_repo = SimpleNamespace(save=AsyncMock())
    agent_service = SimpleNamespace(
        get_conversation=AsyncMock(return_value=conversation),
        _conversation_repo=conversation_repo,
    )
    container = SimpleNamespace(agent_service=lambda _llm: agent_service)
    monkeypatch.setattr(
        conversations_router,
        "get_container_with_db",
        lambda _request, _db: container,
    )
    db = _db_with_project_access()
    omitted = UpdateConversationConfigRequest()
    explicit_clear = UpdateConversationConfigRequest(
        selected_agent_id=None,
        llm_model_override=None,
        llm_overrides=None,
    )

    assert omitted.model_fields_set == set()
    assert explicit_clear.model_fields_set == {
        "selected_agent_id",
        "llm_model_override",
        "llm_overrides",
    }

    omitted_response = await conversations_router.update_conversation_config(
        conversation_id=conversation.id,
        data=omitted,
        request=MagicMock(),
        project_id=conversation.project_id,
        current_user=SimpleNamespace(id=conversation.user_id),
        tenant_id=conversation.tenant_id,
        db=db,
    )

    assert conversation.agent_config == original_config
    assert omitted_response.agent_config == original_config

    cleared_response = await conversations_router.update_conversation_config(
        conversation_id=conversation.id,
        data=explicit_clear,
        request=MagicMock(),
        project_id=conversation.project_id,
        current_user=SimpleNamespace(id=conversation.user_id),
        tenant_id=conversation.tenant_id,
        db=db,
    )

    expected_cleared_config = {
        "selected_agent_id": None,
        "llm_model_override": None,
        "llm_overrides": None,
        "capability_mode": "code",
    }
    assert conversation.agent_config == expected_cleared_config
    assert cleared_response.agent_config == expected_cleared_config
    assert conversation_repo.save.await_args_list == [
        ((conversation,), {}),
        ((conversation,), {}),
    ]
    assert db.commit.await_count == 2


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
            request=MagicMock(),
            current_user=SimpleNamespace(id="user-1"),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "Invalid conversation state"
    assert "secret" not in exc_info.value.detail


@pytest.mark.unit
@pytest.mark.asyncio
async def test_workspace_roster_invariant_errors_are_sanitized(
) -> None:
    conversation = SimpleNamespace(
        conversation_mode=None,
        tenant_id="tenant-1",
        project_id="project-1",
        workspace_id="workspace-1",
        participant_agents=["secret-agent"],
    )
    request = MagicMock()
    request.app.state.workspace_authority = SimpleNamespace(
        list_agents=AsyncMock(return_value=()),
    )

    with pytest.raises(HTTPException) as exc_info:
        await conversations_router._enforce_conversation_invariants(
            conversation,
            request=request,
            current_user=SimpleNamespace(id="user-1"),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "Invalid workspace roster"
    assert "secret" not in exc_info.value.detail


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_conversation_mode_requires_workspace_membership(
    db_session: AsyncSession,
    test_project_db: Project,
    test_user: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation = Conversation(
        id="conversation-mode-private",
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        user_id=test_user.id,
        title="Private workspace patch",
        status=ConversationStatus.ACTIVE,
        created_at=datetime.now(UTC),
    )
    conversation_repo = SimpleNamespace(save=AsyncMock())
    agent_service = SimpleNamespace(
        get_conversation=AsyncMock(return_value=conversation),
        _conversation_repo=conversation_repo,
    )
    container = SimpleNamespace(agent_service=lambda _llm: agent_service)
    monkeypatch.setattr(
        conversations_router,
        "get_container_with_db",
        lambda _request, _db: container,
    )

    with pytest.raises(HTTPException) as exc_info:
        await conversations_router.update_conversation_mode(
            conversation_id=conversation.id,
            data=UpdateConversationModeRequest(workspace_id="workspace-mode-private"),
            request=_request_with_container(
                container,
                authority=FakeWorkspaceAuthority(denied=True),
            ),
            project_id=test_project_db.id,
            current_user=test_user,
            tenant_id=test_project_db.tenant_id,
            db=db_session,
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Workspace access required"
    conversation_repo.save.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_workspace_task_linkage_requires_matching_workspace_project_and_tenant(
    db_session: AsyncSession,
    test_project_db: Project,
    test_user: object,
) -> None:
    invalid_scopes = [
        {
            "workspace_id": "workspace-other",
            "project_id": test_project_db.id,
            "tenant_id": test_project_db.tenant_id,
        },
        {
            "workspace_id": "workspace-task-linkage",
            "project_id": "project-other",
            "tenant_id": test_project_db.tenant_id,
        },
        {
            "workspace_id": "workspace-task-linkage",
            "project_id": test_project_db.id,
            "tenant_id": "tenant-other",
        },
    ]

    for scope in invalid_scopes:
        with pytest.raises(HTTPException) as exc_info:
            await conversations_router._ensure_workspace_task_linkage(
                _request_with_container(
                    object(),
                    authority=FakeWorkspaceAuthority(linked_tasks=False),
                ),
                current_user=test_user,
                linked_workspace_task_id="workspace-task-linkage-task",
                **scope,
            )

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail == "Invalid workspace task linkage"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_conversation_mode_accepts_accessible_workspace_task_linkage(
    db_session: AsyncSession,
    test_project_db: Project,
    test_user: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation = Conversation(
        id="conversation-mode-linkage",
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        user_id=test_user.id,
        title="Workspace task patch",
        status=ConversationStatus.ACTIVE,
        created_at=datetime.now(UTC),
    )
    conversation_repo = SimpleNamespace(save=AsyncMock())
    agent_service = SimpleNamespace(
        get_conversation=AsyncMock(return_value=conversation),
        _conversation_repo=conversation_repo,
    )
    container = SimpleNamespace(agent_service=lambda _llm: agent_service)
    monkeypatch.setattr(
        conversations_router,
        "get_container_with_db",
        lambda _request, _db: container,
    )

    response = await conversations_router.update_conversation_mode(
        conversation_id=conversation.id,
        data=UpdateConversationModeRequest(
            workspace_id="workspace-mode-linkage",
            linked_workspace_task_id="workspace-mode-linkage-task",
        ),
        request=_request_with_container(
            container,
            authority=FakeWorkspaceAuthority(linked_tasks=True),
        ),
        project_id=test_project_db.id,
        current_user=test_user,
        tenant_id=test_project_db.tenant_id,
        db=db_session,
    )

    assert response.workspace_id == "workspace-mode-linkage"
    assert response.linked_workspace_task_id == "workspace-mode-linkage-task"
    conversation_repo.save.assert_awaited_once_with(conversation)


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
