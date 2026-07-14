"""WebSocket acknowledgment contract tests for chat messages."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.websocket.handlers import chat_handler
from src.infrastructure.adapters.primary.web.websocket.handlers.chat_handler import (
    SendMessageHandler,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Project,
    User,
    UserProject,
    UserTenant,
)

pytestmark = pytest.mark.unit


class _ConversationRepository:
    def __init__(self, conversation: Any) -> None:
        self.conversation = conversation

    async def find_by_id(self, conversation_id: str) -> Any:
        assert conversation_id == "conversation-1"
        return self.conversation


class _Container:
    def __init__(self, conversation: Any) -> None:
        self.conversation = conversation

    def conversation_repository(self) -> _ConversationRepository:
        return _ConversationRepository(self.conversation)


class _ScalarResult:
    def __init__(self, value: str | None) -> None:
        self.value = value

    def scalar_one_or_none(self) -> str | None:
        return self.value


class _AuthorizedScopeDb:
    async def execute(self, *_args: Any, **_kwargs: Any) -> _ScalarResult:
        return _ScalarResult("project-1")


class _ConnectionManager:
    def __init__(self) -> None:
        self.subscriptions: list[tuple[str, str]] = []
        self.tasks: list[asyncio.Task[None]] = []

    async def subscribe(self, session_id: str, conversation_id: str) -> None:
        self.subscriptions.append((session_id, conversation_id))

    def add_bridge_task(
        self,
        session_id: str,
        conversation_id: str,
        task: asyncio.Task[None],
    ) -> None:
        assert session_id == "session-1"
        assert conversation_id == "conversation-1"
        self.tasks.append(task)


class _MessageContext:
    session_id = "session-1"

    def __init__(
        self,
        *,
        conversation: Any | None = None,
        db: Any | None = None,
        user_id: str = "user-1",
        tenant_id: str = "tenant-1",
    ) -> None:
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.db = db or _AuthorizedScopeDb()
        self.conversation = conversation or SimpleNamespace(
            user_id=user_id,
            tenant_id=tenant_id,
            project_id="project-1",
        )
        self.connection_manager = _ConnectionManager()
        self.sent: list[dict[str, Any]] = []

    def get_scoped_container(self) -> _Container:
        return _Container(self.conversation)

    async def send_ack(self, action: str, **kwargs: Any) -> None:
        self.sent.append({"type": "ack", "action": action, **kwargs})

    async def send_error(self, message: str, **kwargs: Any) -> None:
        self.sent.append({"type": "error", "message": message, **kwargs})


class _EmptyHitlRepository:
    def __init__(self, _db: object) -> None:
        pass

    async def get_pending_by_conversation(self, **_kwargs: Any) -> list[Any]:
        return []


@pytest.fixture
def successful_chat_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_stream_agent_to_websocket_with_fresh_session(**_kwargs: Any) -> None:
        return None

    import src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository as hitl

    monkeypatch.setattr(hitl, "SqlHITLRequestRepository", _EmptyHitlRepository)
    monkeypatch.setattr(
        chat_handler,
        "stream_agent_to_websocket_with_fresh_session",
        fake_stream_agent_to_websocket_with_fresh_session,
    )


def _message(*, message_id: str | None = None) -> dict[str, Any]:
    message: dict[str, Any] = {
        "conversation_id": "conversation-1",
        "message": "Plan the requested change",
        "project_id": "project-1",
        "preferred_language": "en-US",
    }
    if message_id is not None:
        message["message_id"] = message_id
    return message


@pytest.mark.parametrize("message_id", ["desktop-turn-123", None])
async def test_send_message_ack_echoes_optional_message_id(
    successful_chat_dependencies: None,
    message_id: str | None,
) -> None:
    context = _MessageContext()

    await SendMessageHandler().handle(context, _message(message_id=message_id))  # type: ignore[arg-type]
    await asyncio.gather(*context.connection_manager.tasks)

    assert context.connection_manager.subscriptions == [("session-1", "conversation-1")]
    assert len(context.sent) == 1
    acknowledgment = context.sent[0]
    assert acknowledgment["type"] == "ack"
    assert acknowledgment["action"] == "send_message"
    assert acknowledgment["conversation_id"] == "conversation-1"
    if message_id is None:
        assert "message_id" not in acknowledgment
    else:
        assert acknowledgment["message_id"] == message_id


@pytest.mark.parametrize(
    ("tenant_id", "project_id"),
    [
        ("other-tenant", "project-1"),
        ("tenant-1", "other-project"),
    ],
)
async def test_send_message_rejects_conversation_scope_mismatch_before_ack(
    successful_chat_dependencies: None,
    tenant_id: str,
    project_id: str,
) -> None:
    context = _MessageContext(
        conversation=SimpleNamespace(
            user_id="user-1",
            tenant_id=tenant_id,
            project_id=project_id,
        )
    )

    await SendMessageHandler().handle(context, _message())  # type: ignore[arg-type]

    assert context.connection_manager.subscriptions == []
    assert context.connection_manager.tasks == []
    assert len(context.sent) == 1
    assert context.sent[0]["type"] == "error"


@pytest.mark.parametrize("revoked_membership", ["project", "tenant"])
async def test_send_message_rejects_revoked_scope_membership_before_ack(
    successful_chat_dependencies: None,
    test_db: AsyncSession,
    test_user: User,
    test_project_db: Project,
    revoked_membership: str,
) -> None:
    if revoked_membership == "project":
        statement = delete(UserProject).where(
            UserProject.user_id == test_user.id,
            UserProject.project_id == test_project_db.id,
        )
    else:
        statement = delete(UserTenant).where(
            UserTenant.user_id == test_user.id,
            UserTenant.tenant_id == test_project_db.tenant_id,
        )
    await test_db.execute(statement)
    await test_db.commit()

    context = _MessageContext(
        conversation=SimpleNamespace(
            user_id=test_user.id,
            tenant_id=test_project_db.tenant_id,
            project_id=test_project_db.id,
        ),
        db=test_db,
        user_id=test_user.id,
        tenant_id=test_project_db.tenant_id,
    )

    await SendMessageHandler().handle(
        context,  # type: ignore[arg-type]
        {
            **_message(),
            "project_id": test_project_db.id,
        },
    )

    assert context.connection_manager.subscriptions == []
    assert context.connection_manager.tasks == []
    assert len(context.sent) == 1
    assert context.sent[0]["type"] == "error"
