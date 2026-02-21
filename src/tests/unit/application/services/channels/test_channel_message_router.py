"""Unit tests for ChannelMessageRouter."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.application.services.channels.channel_message_router import ChannelMessageRouter
from src.domain.model.channels.message import (
    ChatType,
    Message,
    MessageContent,
    MessageType,
    SenderInfo,
)


def _build_message(*, text: str, raw_data: dict | None = None) -> Message:
    """Build a minimal channel message for tests."""
    return Message(
        channel="feishu",
        chat_type=ChatType.P2P,
        chat_id="chat-1",
        sender=SenderInfo(id="sender-1", name="Test User"),
        content=MessageContent(type=MessageType.TEXT, text=text),
        project_id="project-1",
        raw_data=raw_data,
    )


@pytest.mark.unit
def test_extract_channel_config_id_rejects_untrusted_top_level_payload() -> None:
    """Router should trust only internally injected _routing metadata."""
    router = ChannelMessageRouter()
    message = _build_message(
        text="hello",
        raw_data={"channel_config_id": "untrusted-config-id"},
    )

    assert router._extract_channel_config_id(message) is None


@pytest.mark.unit
def test_build_session_key_includes_topic_and_thread() -> None:
    """Session key should deterministically include topic/thread when present."""
    router = ChannelMessageRouter()
    message = _build_message(
        text="hello",
        raw_data={
            "_routing": {
                "channel_config_id": "cfg-1",
                "topic_id": "topic-42",
                "thread_id": "thread-99",
            }
        },
    )

    session_key = router._build_session_key(message, "cfg-1")
    assert "config:cfg-1" in session_key
    assert ":topic:topic-42" in session_key
    assert ":thread:thread-99" in session_key


@pytest.mark.unit
@pytest.mark.asyncio
async def test_route_message_skips_bot_echo_messages() -> None:
    """Router should skip app/bot sender messages to avoid echo loops."""
    router = ChannelMessageRouter()
    router._get_or_create_conversation = AsyncMock()
    router._store_message_history = AsyncMock()
    router._invoke_agent = AsyncMock()

    message = _build_message(
        text="hello",
        raw_data={"event": {"sender": {"sender_type": "app"}}},
    )

    await router.route_message(message)

    router._get_or_create_conversation.assert_not_called()
    router._store_message_history.assert_not_called()
    router._invoke_agent.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_route_message_broadcasts_inbound_user_message_to_workspace() -> None:
    """Router should emit realtime inbound user message event for workspace."""
    router = ChannelMessageRouter()
    router._get_or_create_conversation = AsyncMock(return_value="conv-1")
    router._store_message_history = AsyncMock()
    router._broadcast_workspace_event = AsyncMock()
    router._invoke_agent = AsyncMock()

    message = _build_message(
        text="hello from feishu",
        raw_data={
            "_routing": {"channel_config_id": "cfg-1", "channel_message_id": "om_1"},
            "event": {"sender": {"sender_type": "user"}},
        },
    )

    await router.route_message(message)

    message_calls = [
        call.kwargs
        for call in router._broadcast_workspace_event.await_args_list
        if call.kwargs.get("event_type") == "message"
    ]
    assert len(message_calls) == 1
    broadcast_call = message_calls[0]
    assert broadcast_call["event_data"]["metadata"]["source"] == "channel_inbound"
    assert broadcast_call["event_data"]["content"] == "hello from feishu"
    router._invoke_agent.assert_awaited_once_with(message, "conv-1")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_invoke_agent_streams_and_sends_final_response() -> None:
    """Router should invoke AgentService stream and forward complete response to channel."""
    router = ChannelMessageRouter()
    router._send_response = AsyncMock()
    router._broadcast_workspace_event = AsyncMock()

    message = _build_message(
        text="What is the status?",
        raw_data={
            "_routing": {"channel_config_id": "cfg-1", "channel_message_id": "msg-1"},
            "event": {"sender": {"sender_type": "user"}},
        },
    )

    conversation = SimpleNamespace(
        id="conv-1",
        project_id="project-1",
        user_id="user-1",
        tenant_id="tenant-1",
    )

    session = MagicMock()
    session.get = AsyncMock(return_value=conversation)

    session_ctx = AsyncMock()
    session_ctx.__aenter__.return_value = session
    session_ctx.__aexit__.return_value = None

    async def fake_stream_chat_v2(**_: dict):
        yield {"type": "text_delta", "data": {"delta": "partial "}}
        yield {"type": "complete", "data": {"content": "final answer"}}

    agent_service = MagicMock()
    agent_service.stream_chat_v2 = fake_stream_chat_v2

    scoped_container = MagicMock()
    scoped_container.agent_service.return_value = agent_service

    app_container = MagicMock()
    app_container.with_db.return_value = scoped_container

    with (
        patch(
            "src.infrastructure.adapters.secondary.persistence.database.async_session_factory",
            return_value=session_ctx,
        ),
        patch(
            "src.configuration.factories.create_llm_client",
            new=AsyncMock(return_value=object()),
        ) as mock_create_llm_client,
        patch(
            "src.infrastructure.adapters.primary.web.startup.container.get_app_container",
            return_value=app_container,
        ),
    ):
        await router._invoke_agent(message, "conv-1")

    mock_create_llm_client.assert_awaited_once_with("tenant-1")
    # Only text_delta is broadcast; complete is filtered to prevent duplicate messages
    assert router._broadcast_workspace_event.await_count == 1
    router._send_response.assert_awaited_once_with(message, "conv-1", "final answer")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_invoke_agent_sends_response_text_on_no_progress_error() -> None:
    """When agent errors with 'no-progress' but has accumulated text, send that text."""
    router = ChannelMessageRouter()
    router._send_response = AsyncMock()
    router._send_error_feedback = AsyncMock()
    router._broadcast_workspace_event = AsyncMock()

    message = _build_message(
        text="hi",
        raw_data={
            "_routing": {"channel_config_id": "cfg-1", "channel_message_id": "msg-1"},
            "event": {"sender": {"sender_type": "user"}},
        },
    )

    conversation = SimpleNamespace(
        id="conv-1",
        project_id="project-1",
        user_id="user-1",
        tenant_id="tenant-1",
    )

    session = MagicMock()
    session.get = AsyncMock(return_value=conversation)

    session_ctx = AsyncMock()
    session_ctx.__aenter__.return_value = session
    session_ctx.__aexit__.return_value = None

    async def fake_stream(**_):
        yield {"type": "text_delta", "data": {"delta": "Hello! How can I help?"}}
        yield {"type": "text_end", "data": {"full_text": "Hello! How can I help?"}}
        yield {"type": "error", "data": {"message": "Goal not achieved after 3 no-progress turns."}}

    agent_service = MagicMock()
    agent_service.stream_chat_v2 = fake_stream

    scoped_container = MagicMock()
    scoped_container.agent_service.return_value = agent_service

    app_container = MagicMock()
    app_container.with_db.return_value = scoped_container

    with (
        patch(
            "src.infrastructure.adapters.secondary.persistence.database.async_session_factory",
            return_value=session_ctx,
        ),
        patch(
            "src.configuration.factories.create_llm_client",
            new=AsyncMock(return_value=object()),
        ),
        patch(
            "src.infrastructure.adapters.primary.web.startup.container.get_app_container",
            return_value=app_container,
        ),
    ):
        await router._invoke_agent(message, "conv-1")

    # Should send the accumulated response, NOT the generic error feedback
    router._send_response.assert_awaited_once_with(message, "conv-1", "Hello! How can I help?")
    router._send_error_feedback.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_invoke_agent_streams_via_card_when_adapter_supports_it() -> None:
    """Background card updater sends initial card and patches with content."""
    router = ChannelMessageRouter()
    router._send_response = AsyncMock()
    router._send_error_feedback = AsyncMock()
    router._broadcast_workspace_event = AsyncMock()
    router._record_streaming_outbox = AsyncMock()

    fake_adapter = MagicMock()
    fake_adapter.send_streaming_card = AsyncMock(return_value="om_stream_1")
    fake_adapter.patch_card = AsyncMock(return_value=True)
    fake_adapter._build_streaming_card = MagicMock(return_value='{"elements":[]}')

    message = _build_message(
        text="Tell me a story",
        raw_data={
            "_routing": {"channel_config_id": "cfg-1", "channel_message_id": "msg-1"},
            "event": {"sender": {"sender_type": "user"}},
        },
    )

    conversation = SimpleNamespace(
        id="conv-1", project_id="project-1", user_id="user-1", tenant_id="tenant-1",
    )

    session = MagicMock()
    session.get = AsyncMock(return_value=conversation)
    session_ctx = AsyncMock()
    session_ctx.__aenter__.return_value = session
    session_ctx.__aexit__.return_value = None

    async def fake_stream(**_):
        yield {"type": "text_delta", "data": {"delta": "Once "}}
        yield {"type": "text_delta", "data": {"delta": "upon a time"}}
        yield {"type": "complete", "data": {"content": "Once upon a time"}}

    agent_service = MagicMock()
    agent_service.stream_chat_v2 = fake_stream
    scoped_container = MagicMock()
    scoped_container.agent_service.return_value = agent_service
    app_container = MagicMock()
    app_container.with_db.return_value = scoped_container

    router._get_streaming_adapter = MagicMock(return_value=fake_adapter)

    with (
        patch(
            "src.infrastructure.adapters.secondary.persistence.database.async_session_factory",
            return_value=session_ctx,
        ),
        patch(
            "src.configuration.factories.create_llm_client",
            new=AsyncMock(return_value=object()),
        ),
        patch(
            "src.infrastructure.adapters.primary.web.startup.container.get_app_container",
            return_value=app_container,
        ),
    ):
        await router._invoke_agent(message, "conv-1")

    # Background task sent initial streaming card
    fake_adapter.send_streaming_card.assert_awaited_once()
    # Streaming path handled response -- _send_response NOT called
    router._send_response.assert_not_awaited()
    router._record_streaming_outbox.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_invoke_agent_falls_back_when_initial_card_fails() -> None:
    """When send_streaming_card returns None, falls through to _send_response."""
    router = ChannelMessageRouter()
    router._send_response = AsyncMock()
    router._send_error_feedback = AsyncMock()
    router._broadcast_workspace_event = AsyncMock()
    router._record_streaming_outbox = AsyncMock()

    fake_adapter = MagicMock()
    fake_adapter.send_streaming_card = AsyncMock(return_value=None)  # card send fails
    fake_adapter.patch_card = AsyncMock(return_value=True)
    fake_adapter._build_streaming_card = MagicMock(return_value='{"elements":[]}')

    message = _build_message(
        text="hello",
        raw_data={
            "_routing": {"channel_config_id": "cfg-1", "channel_message_id": "msg-1"},
            "event": {"sender": {"sender_type": "user"}},
        },
    )

    conversation = SimpleNamespace(
        id="conv-1", project_id="project-1", user_id="user-1", tenant_id="tenant-1",
    )

    session = MagicMock()
    session.get = AsyncMock(return_value=conversation)
    session_ctx = AsyncMock()
    session_ctx.__aenter__.return_value = session
    session_ctx.__aexit__.return_value = None

    async def fake_stream(**_):
        yield {"type": "text_delta", "data": {"delta": "Hello world"}}
        yield {"type": "complete", "data": {"content": "Hello world"}}

    agent_service = MagicMock()
    agent_service.stream_chat_v2 = fake_stream
    scoped_container = MagicMock()
    scoped_container.agent_service.return_value = agent_service
    app_container = MagicMock()
    app_container.with_db.return_value = scoped_container

    router._get_streaming_adapter = MagicMock(return_value=fake_adapter)

    with (
        patch(
            "src.infrastructure.adapters.secondary.persistence.database.async_session_factory",
            return_value=session_ctx,
        ),
        patch(
            "src.configuration.factories.create_llm_client",
            new=AsyncMock(return_value=object()),
        ),
        patch(
            "src.infrastructure.adapters.primary.web.startup.container.get_app_container",
            return_value=app_container,
        ),
    ):
        await router._invoke_agent(message, "conv-1")

    # Initial card failed (_card_msg_id=None) → falls through to regular send
    router._send_response.assert_awaited_once_with(message, "conv-1", "Hello world")
    router._record_streaming_outbox.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_response_marks_outbox_failed_when_connection_missing() -> None:
    """Router should persist failed outbox state if channel connection is unavailable."""
    router = ChannelMessageRouter()
    router._create_outbox_record = AsyncMock(return_value="outbox-1")
    router._mark_outbox_failed = AsyncMock()

    message = _build_message(
        text="hello",
        raw_data={"_routing": {"channel_config_id": "cfg-1", "channel_message_id": "msg-1"}},
    )

    channel_manager = SimpleNamespace(connections={})
    with patch(
        "src.infrastructure.adapters.primary.web.startup.get_channel_manager",
        return_value=channel_manager,
    ):
        await router._send_response(message, "conv-1", "reply")

    router._mark_outbox_failed.assert_awaited_once_with("outbox-1", "no active connection")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_response_marks_outbox_failed_when_manager_missing() -> None:
    """Router should mark outbox failed when channel manager is unavailable."""
    router = ChannelMessageRouter()
    router._create_outbox_record = AsyncMock(return_value="outbox-1")
    router._mark_outbox_failed = AsyncMock()

    message = _build_message(
        text="hello",
        raw_data={"_routing": {"channel_config_id": "cfg-1", "channel_message_id": "msg-1"}},
    )

    with patch(
        "src.infrastructure.adapters.primary.web.startup.get_channel_manager",
        return_value=None,
    ):
        await router._send_response(message, "conv-1", "reply")

    router._mark_outbox_failed.assert_awaited_once_with("outbox-1", "channel manager unavailable")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_broadcast_workspace_event_sanitizes_payload() -> None:
    """Workspace broadcast payload should be JSON-safe."""
    router = ChannelMessageRouter()

    class _SenderId:
        def __init__(self, open_id: str) -> None:
            self.open_id = open_id

    manager = SimpleNamespace(broadcast_to_conversation=AsyncMock(return_value=1))
    with patch(
        "src.infrastructure.adapters.primary.web.websocket.connection_manager.get_connection_manager",
        return_value=manager,
    ):
        await router._broadcast_workspace_event(
            conversation_id="conv-1",
            event_type="text_delta",
            event_data={"sender_id": _SenderId("ou_123")},
            raw_event={},
        )

    sent_event = manager.broadcast_to_conversation.await_args.args[1]
    assert sent_event["data"]["sender_id"]["open_id"] == "ou_123"


@pytest.mark.unit
def test_to_json_safe_converts_sdk_objects_to_dicts() -> None:
    """Router should sanitize SDK objects before JSON persistence."""
    router = ChannelMessageRouter()

    class _UserId:
        def __init__(self, open_id: str) -> None:
            self.open_id = open_id

    payload = {
        "_routing": {"channel_config_id": "cfg-1", "channel_message_id": "msg-1"},
        "event": {"sender": {"sender_id": _UserId("ou_x"), "sender_type": "user"}},
    }
    safe_payload = router._to_json_safe(payload)

    assert safe_payload["event"]["sender"]["sender_id"]["open_id"] == "ou_x"
    json.dumps(safe_payload, allow_nan=False)


@pytest.mark.unit
def test_to_json_safe_sanitizes_non_finite_floats() -> None:
    """Router should sanitize non-finite floats for strict JSON safety."""
    router = ChannelMessageRouter()
    safe_payload = router._to_json_safe({"nan": float("nan"), "inf": float("inf"), "ok": 1.25})

    assert safe_payload["nan"] is None
    assert safe_payload["inf"] is None
    assert safe_payload["ok"] == 1.25
    json.dumps(safe_payload, allow_nan=False)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_store_message_history_sanitizes_non_serializable_raw_data() -> None:
    """Storing history should sanitize raw_data to avoid JSON serialization errors."""
    router = ChannelMessageRouter()
    router._resolve_channel_config_id = AsyncMock(return_value="cfg-1")

    class _UserId:
        def __init__(self, open_id: str) -> None:
            self.open_id = open_id

    message = _build_message(
        text="hello",
        raw_data={
            "_routing": {"channel_config_id": "cfg-1", "channel_message_id": "msg-1"},
            "event": {"sender": {"sender_id": _UserId("ou_x"), "sender_type": "user"}},
        },
    )

    mock_dedupe_result = MagicMock()
    mock_dedupe_result.scalar_one_or_none.return_value = None
    session = MagicMock()
    session.execute = AsyncMock(return_value=mock_dedupe_result)
    session.commit = AsyncMock()

    session_ctx = AsyncMock()
    session_ctx.__aenter__.return_value = session
    session_ctx.__aexit__.return_value = None

    mock_repo = MagicMock()
    mock_repo.create = AsyncMock()

    with (
        patch(
            "src.infrastructure.adapters.secondary.persistence.database.async_session_factory",
            return_value=session_ctx,
        ),
        patch(
            "src.infrastructure.adapters.secondary.persistence.channel_repository.ChannelMessageRepository",
            return_value=mock_repo,
        ),
    ):
        await router._store_message_history(message, "conv-1")

    saved_message = mock_repo.create.await_args.args[0]
    assert saved_message.raw_data["event"]["sender"]["sender_id"]["open_id"] == "ou_x"
    json.dumps(saved_message.raw_data, allow_nan=False)
