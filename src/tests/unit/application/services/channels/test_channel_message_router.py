"""Unit tests for ChannelMessageRouter."""

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
async def test_invoke_agent_streams_and_sends_final_response() -> None:
    """Router should invoke AgentService stream and forward complete response to channel."""
    router = ChannelMessageRouter()
    router._send_response = AsyncMock()

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
    router._send_response.assert_awaited_once_with(message, "conv-1", "final answer")
