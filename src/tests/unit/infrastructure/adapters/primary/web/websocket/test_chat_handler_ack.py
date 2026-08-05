"""WebSocket acknowledgment contract tests for chat messages."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.agent_service import canonical_agent_client_turn_payload_hash
from src.domain.model.agent import AgentClientTurnStatus
from src.infrastructure.adapters.primary.web.websocket.handlers import chat_handler
from src.infrastructure.adapters.primary.web.websocket.handlers.chat_handler import (
    SendMessageHandler,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Conversation,
    Project,
    User,
    UserProject,
    UserTenant,
)
from src.infrastructure.adapters.secondary.persistence.sql_agent_client_turn_repository import (
    SqlAgentClientTurnRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_agent_run_authority import (
    ensure_chat_run_authority,
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

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


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
        data = {"message": message}
        code = kwargs.get("code")
        if code is not None:
            data["code"] = code
        extra = kwargs.get("extra")
        if isinstance(extra, dict):
            data.update(extra)
        error = {"type": "error", "data": data}
        conversation_id = kwargs.get("conversation_id")
        if conversation_id is not None:
            error["conversation_id"] = conversation_id
        self.sent.append(error)


class _EmptyHitlRepository:
    def __init__(self, _db: object) -> None:
        pass

    async def get_pending_by_conversation(self, **_kwargs: Any) -> list[Any]:
        return []


class _AlwaysNewClientTurnRepository:
    def __init__(self, _db: object) -> None:
        pass

    async def find(self, _conversation_id: str, _client_message_id: str) -> None:
        return None

    async def claim_and_commit(self, **kwargs: str) -> Any:
        client_message_id = kwargs["client_message_id"]
        return SimpleNamespace(
            created=True,
            turn=SimpleNamespace(
                client_message_id=client_message_id,
                execution_message_id=client_message_id,
                payload_hash=kwargs["payload_hash"],
                status=AgentClientTurnStatus.ACCEPTED,
            ),
        )


class _ExistingStartedClientTurnRepository:
    def __init__(self, _db: object) -> None:
        pass

    async def find(self, _conversation_id: str, client_message_id: str) -> Any:
        return SimpleNamespace(
            client_message_id=client_message_id,
            execution_message_id=client_message_id,
            payload_hash=_message_payload_hash(),
            status=AgentClientTurnStatus.STARTED,
        )


class _ExistingAcceptedClientTurnRepository(_ExistingStartedClientTurnRepository):
    async def find(self, _conversation_id: str, client_message_id: str) -> Any:
        turn = await super().find(_conversation_id, client_message_id)
        turn.status = AgentClientTurnStatus.ACCEPTED
        return turn


class _PendingHitlRepository:
    def __init__(self, _db: object) -> None:
        pass

    async def get_pending_by_conversation(self, **_kwargs: Any) -> list[Any]:
        return [
            SimpleNamespace(
                id="hitl-1",
                request_type=SimpleNamespace(value="decision"),
                question="Approve the pending decision?",
                metadata={},
            )
        ]


class _ScopeThenMissingEventDb(_AuthorizedScopeDb):
    def __init__(self) -> None:
        self.execution_count = 0

    async def execute(self, *_args: Any, **_kwargs: Any) -> _ScalarResult:
        self.execution_count += 1
        return _ScalarResult("project-1" if self.execution_count == 1 else None)


class _ExplodingMessageContext(_MessageContext):
    def get_scoped_container(self) -> _Container:
        raise RuntimeError("simulated permanent send failure")


@pytest.fixture
def successful_chat_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_stream_agent_to_websocket_with_fresh_session(**_kwargs: Any) -> None:
        return None

    import src.infrastructure.adapters.secondary.persistence.sql_agent_client_turn_repository as turns
    import src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository as hitl

    monkeypatch.setattr(hitl, "SqlHITLRequestRepository", _EmptyHitlRepository)
    monkeypatch.setattr(
        turns,
        "SqlAgentClientTurnRepository",
        _AlwaysNewClientTurnRepository,
    )
    monkeypatch.setattr(
        chat_handler,
        "stream_agent_to_websocket_with_fresh_session",
        fake_stream_agent_to_websocket_with_fresh_session,
    )

    async def fake_ensure_chat_run_authority(_db: object, **kwargs: Any) -> Any:
        return SimpleNamespace(
            id=kwargs["run_id"],
            revision=1,
        )

    monkeypatch.setattr(
        chat_handler,
        "ensure_chat_run_authority",
        fake_ensure_chat_run_authority,
    )


def _message(
    *,
    message_id: str | None = None,
    permission_mode: str | None = None,
) -> dict[str, Any]:
    message: dict[str, Any] = {
        "conversation_id": "conversation-1",
        "message": "Plan the requested change",
        "project_id": "project-1",
        "preferred_language": "en-US",
    }
    if message_id is not None:
        message["message_id"] = message_id
    if permission_mode is not None:
        message["permission_mode"] = permission_mode
    return message


def _message_payload_hash(*, permission_mode: str | None = None) -> str:
    return canonical_agent_client_turn_payload_hash(
        {
            "agent_id": None,
            "app_model_context": None,
            "attachment_ids": None,
            "file_metadata": None,
            "forced_skill_name": None,
            "image_attachments": None,
            "mentions": None,
            "message": "Plan the requested change",
            "permission_mode": permission_mode,
            "preferred_language": "en-US",
            "project_id": "project-1",
        }
    )


def _assert_error_message_id(context: _MessageContext, message_id: str) -> None:
    assert context.sent[0]["type"] == "error"
    assert context.sent[0]["data"]["message_id"] == message_id


def _assert_error_code(context: _MessageContext, code: str) -> None:
    assert context.sent[0]["type"] == "error"
    assert context.sent[0]["data"]["code"] == code


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
        assert isinstance(acknowledgment["run_id"], str)
        assert acknowledgment["run_id"]
    else:
        assert acknowledgment["message_id"] == message_id
        assert acknowledgment["run_id"] == message_id
    assert acknowledgment["run_revision"] == 1


async def test_send_message_passes_permission_mode_to_run_authority(
    successful_chat_dependencies: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def capture_run_authority(_db: object, **kwargs: Any) -> Any:
        captured.update(kwargs)
        return SimpleNamespace(id=kwargs["run_id"], revision=1)

    monkeypatch.setattr(
        chat_handler,
        "ensure_chat_run_authority",
        capture_run_authority,
    )
    context = _MessageContext()

    await SendMessageHandler().handle(
        context,
        _message(
            message_id="desktop-turn-permission-mode",
            permission_mode="automatic",
        ),
    )  # type: ignore[arg-type]
    await asyncio.gather(*context.connection_manager.tasks)

    assert captured["permission_mode"] == "automatic"
    assert context.sent[0]["action"] == "send_message"


async def test_send_message_rejects_unknown_permission_mode_before_ack() -> None:
    context = _MessageContext()

    await SendMessageHandler().handle(
        context,
        _message(
            message_id="desktop-turn-invalid-permission-mode",
            permission_mode="unrestricted",
        ),
    )  # type: ignore[arg-type]

    assert context.connection_manager.subscriptions == []
    assert context.connection_manager.tasks == []
    _assert_error_message_id(context, "desktop-turn-invalid-permission-mode")
    _assert_error_code(context, "INVALID_PERMISSION_MODE")


async def test_started_duplicate_replays_authoritative_ack_without_new_task(
    successful_chat_dependencies: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.infrastructure.adapters.secondary.persistence.sql_agent_client_turn_repository as turns

    monkeypatch.setattr(
        turns,
        "SqlAgentClientTurnRepository",
        _ExistingStartedClientTurnRepository,
    )
    context = _MessageContext()

    await SendMessageHandler().handle(
        context,
        _message(message_id="desktop-turn-started"),
    )  # type: ignore[arg-type]

    assert context.connection_manager.tasks == []
    assert context.sent == [
        {
            "type": "ack",
            "action": "send_message",
            "conversation_id": "conversation-1",
            "message_id": "desktop-turn-started",
            "outcome": "accepted",
            "replayed": True,
            "turn_status": "started",
            "execution_message_id": "desktop-turn-started",
            "run_id": "desktop-turn-started",
            "run_revision": 1,
        }
    ]


async def test_started_duplicate_without_user_event_fails_closed(
    successful_chat_dependencies: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.infrastructure.adapters.secondary.persistence.sql_agent_client_turn_repository as turns

    monkeypatch.setattr(
        turns,
        "SqlAgentClientTurnRepository",
        _ExistingStartedClientTurnRepository,
    )
    context = _MessageContext(db=_ScopeThenMissingEventDb())

    await SendMessageHandler().handle(
        context,
        _message(message_id="desktop-turn-unconfirmed"),
    )  # type: ignore[arg-type]

    assert context.connection_manager.subscriptions == []
    assert context.connection_manager.tasks == []
    assert context.sent[0]["type"] == "error"
    assert context.sent[0]["data"]["code"] == "TURN_START_UNCONFIRMED"
    assert context.sent[0]["data"]["turn_status"] == "started"
    _assert_error_message_id(context, "desktop-turn-unconfirmed")


async def test_accepted_replay_still_respects_pending_hitl(
    successful_chat_dependencies: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.infrastructure.adapters.secondary.persistence.sql_agent_client_turn_repository as turns
    import src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository as hitl

    monkeypatch.setattr(
        turns,
        "SqlAgentClientTurnRepository",
        _ExistingAcceptedClientTurnRepository,
    )
    monkeypatch.setattr(hitl, "SqlHITLRequestRepository", _PendingHitlRepository)
    context = _MessageContext()

    await SendMessageHandler().handle(
        context,
        _message(message_id="desktop-turn-accepted"),
    )  # type: ignore[arg-type]

    assert context.connection_manager.subscriptions == []
    assert context.connection_manager.tasks == []
    assert context.sent[0]["type"] == "error"
    assert context.sent[0]["data"]["code"] == "HITL_PENDING"
    _assert_error_message_id(context, "desktop-turn-accepted")


async def test_accepted_replay_preserves_loaded_conversation_authority(
    successful_chat_dependencies: None,
    monkeypatch: pytest.MonkeyPatch,
    test_db: AsyncSession,
    test_user: User,
    test_project_db: Project,
) -> None:
    import src.infrastructure.adapters.secondary.persistence.sql_agent_client_turn_repository as turns

    conversation = Conversation(
        id="conversation-accepted-replay",
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        user_id=test_user.id,
        title="Accepted replay",
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

    execution_payload = {
        "agent_id": None,
        "app_model_context": None,
        "attachment_ids": None,
        "file_metadata": None,
        "forced_skill_name": None,
        "image_attachments": None,
        "mentions": None,
        "message": "Resume the accepted turn",
        "preferred_language": "en-US",
        "project_id": test_project_db.id,
    }
    payload_hash = canonical_agent_client_turn_payload_hash(execution_payload)
    repository = SqlAgentClientTurnRepository(test_db)
    await repository.claim_and_commit(
        conversation_id=conversation.id,
        client_message_id="desktop-turn-accepted-replay",
        payload_hash=payload_hash,
    )
    monkeypatch.setattr(turns, "SqlAgentClientTurnRepository", SqlAgentClientTurnRepository)

    context = _MessageContext(
        conversation=conversation,
        db=test_db,
        user_id=test_user.id,
        tenant_id=test_project_db.tenant_id,
    )

    admission = await chat_handler._admit_client_turn(
        context,  # type: ignore[arg-type]
        conversation_id=conversation.id,
        project_id=test_project_db.id,
        message_id="desktop-turn-accepted-replay",
        execution_payload=execution_payload,
    )

    assert admission is not None
    assert admission.should_start is True
    assert conversation.project_id == test_project_db.id


async def test_existing_chat_run_authority_remains_readable_after_replay(
    test_db: AsyncSession,
    test_user: User,
    test_project_db: Project,
) -> None:
    conversation = Conversation(
        id="conversation-run-authority-replay",
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        user_id=test_user.id,
        title="Run authority replay",
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
    arguments = {
        "conversation": conversation,
        "run_id": "chat-run-authority-replay",
        "request_message": "Resume the accepted turn",
        "client_message_id": "desktop-turn-run-authority-replay",
        "app_model_context": None,
    }
    await ensure_chat_run_authority(test_db, **arguments)

    replay = await ensure_chat_run_authority(test_db, **arguments)

    assert replay.id == "chat-run-authority-replay"
    assert replay.revision == 1


async def test_chat_run_authority_persists_requested_permission_snapshot(
    test_db: AsyncSession,
    test_user: User,
    test_project_db: Project,
) -> None:
    conversation = Conversation(
        id="conversation-run-authority-permission",
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        user_id=test_user.id,
        title="Run authority permission",
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

    run = await ensure_chat_run_authority(
        test_db,
        conversation=conversation,
        run_id="chat-run-authority-permission",
        request_message="Use relaxed authorization",
        client_message_id="desktop-turn-run-authority-permission",
        app_model_context=None,
        permission_mode="automatic",
    )

    assert run.permission_profile == "workspace_write"
    assert run.authorization_snapshot["effective_permission_mode"] == "automatic"
    assert run.authorization_snapshot["requested_permission_mode"] == "automatic"
    assert run.authorization_snapshot["policy"]["permission_mode"] == "ask"


async def test_missing_conversation_error_echoes_valid_message_id(
    successful_chat_dependencies: None,
) -> None:
    context = _MessageContext()
    context.conversation = None

    await SendMessageHandler().handle(
        context,
        _message(message_id="desktop-turn-missing"),
    )  # type: ignore[arg-type]

    assert context.connection_manager.subscriptions == []
    assert context.connection_manager.tasks == []
    _assert_error_message_id(context, "desktop-turn-missing")
    _assert_error_code(context, "CONVERSATION_NOT_FOUND")


async def test_unexpected_send_error_echoes_valid_message_id(
    successful_chat_dependencies: None,
) -> None:
    context = _ExplodingMessageContext()

    await SendMessageHandler().handle(
        context,
        _message(message_id="desktop-turn-error"),
    )  # type: ignore[arg-type]

    assert context.connection_manager.subscriptions == []
    assert context.connection_manager.tasks == []
    _assert_error_message_id(context, "desktop-turn-error")


async def test_missing_required_field_error_echoes_valid_message_id(
    successful_chat_dependencies: None,
) -> None:
    context = _MessageContext()

    await SendMessageHandler().handle(
        context,
        {
            "conversation_id": "conversation-1",
            "message_id": "desktop-turn-invalid-payload",
            "project_id": "project-1",
        },
    )  # type: ignore[arg-type]

    assert context.connection_manager.subscriptions == []
    assert context.connection_manager.tasks == []
    _assert_error_message_id(context, "desktop-turn-invalid-payload")
    _assert_error_code(context, "INVALID_SEND_MESSAGE")


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

    await SendMessageHandler().handle(
        context,
        _message(message_id="desktop-turn-scope-denied"),
    )  # type: ignore[arg-type]

    assert context.connection_manager.subscriptions == []
    assert context.connection_manager.tasks == []
    assert len(context.sent) == 1
    assert context.sent[0]["type"] == "error"
    _assert_error_message_id(context, "desktop-turn-scope-denied")
    _assert_error_code(context, "CONVERSATION_ACCESS_DENIED")


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
            **_message(message_id="desktop-turn-membership-revoked"),
            "project_id": test_project_db.id,
        },
    )

    assert context.connection_manager.subscriptions == []
    assert context.connection_manager.tasks == []
    assert len(context.sent) == 1
    assert context.sent[0]["type"] == "error"
    _assert_error_message_id(context, "desktop-turn-membership-revoked")
    _assert_error_code(context, "CONVERSATION_ACCESS_DENIED")
