"""E2E-style tests for workspace WebSocket event delivery system."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from src.domain.events.envelope import EventEnvelope
from src.domain.ports.services.unified_event_bus_port import (
    EventWithMetadata,
    SubscriptionOptions,
)
from src.infrastructure.adapters.primary.web.websocket.handlers.workspace_handler import (
    SubscribeWorkspaceHandler,
    UnsubscribeWorkspaceHandler,
    WorkspaceHeartbeatHandler,
)
from src.infrastructure.adapters.primary.web.websocket.message_context import MessageContext
from src.infrastructure.adapters.primary.web.websocket.topics import TopicManager

_HANDLER_MODULE = "src.infrastructure.adapters.primary.web.websocket.handlers.workspace_handler"


@pytest.fixture()
def topic_manager() -> TopicManager:
    return TopicManager()


@pytest.fixture()
def mock_websocket() -> AsyncMock:
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    return ws


@pytest.fixture()
def mock_redis() -> AsyncMock:
    redis = AsyncMock()
    redis.hset = AsyncMock()
    redis.expire = AsyncMock()
    redis.sadd = AsyncMock()
    redis.srem = AsyncMock()
    redis.delete = AsyncMock()
    redis.smembers = AsyncMock(return_value=set())
    redis.hgetall = AsyncMock(return_value={})
    redis.xadd = AsyncMock(return_value=b"1234567890-0")
    return redis


@pytest.fixture()
def mock_container(mock_redis: AsyncMock) -> MagicMock:
    container = MagicMock()
    scoped = MagicMock()
    member_repo = MagicMock()
    member_repo.find_by_workspace_and_user = AsyncMock(return_value=Mock(id="wm-1"))
    scoped.redis.return_value = mock_redis
    scoped.workspace_member_repository.return_value = member_repo
    container.with_db.return_value = scoped
    container.mock_member_repo = member_repo
    return container


@pytest.fixture()
def mock_connection_manager() -> MagicMock:
    manager = MagicMock()
    manager.status_tasks = {}
    return manager


@pytest.fixture()
def context(
    mock_websocket: AsyncMock,
    mock_container: MagicMock,
    mock_connection_manager: MagicMock,
) -> MessageContext:
    return MessageContext(
        websocket=mock_websocket,
        user_id="test-user-id",
        tenant_id="test-tenant-id",
        session_id="test-session-id",
        db=AsyncMock(),
        container=mock_container,
        _connection_manager=mock_connection_manager,
    )


@pytest.mark.integration
class TestWorkspaceWebSocket:
    async def test_subscribe_registers_workspace(
        self,
        context: MessageContext,
        topic_manager: TopicManager,
    ) -> None:
        handler = SubscribeWorkspaceHandler()
        workspace_id = "ws-001"

        with patch(
            f"{_HANDLER_MODULE}.get_topic_manager",
            return_value=topic_manager,
        ):
            await handler.handle(context, {"workspace_id": workspace_id})

        assert topic_manager.is_subscribed("test-session-id", f"workspace:{workspace_id}")

        context.websocket.send_json.assert_called_once()
        ack_msg = context.websocket.send_json.call_args[0][0]
        assert ack_msg["type"] == "ack"
        assert ack_msg["action"] == "subscribe_workspace"
        assert ack_msg["workspace_id"] == workspace_id

    async def test_subscribe_rejects_non_member(
        self,
        context: MessageContext,
        topic_manager: TopicManager,
        mock_container: MagicMock,
    ) -> None:
        handler = SubscribeWorkspaceHandler()
        workspace_id = "ws-denied"
        mock_container.mock_member_repo.find_by_workspace_and_user.return_value = None

        with patch(
            f"{_HANDLER_MODULE}.get_topic_manager",
            return_value=topic_manager,
        ):
            await handler.handle(context, {"workspace_id": workspace_id})

        assert not topic_manager.is_subscribed("test-session-id", f"workspace:{workspace_id}")
        sent = context.websocket.send_json.call_args[0][0]
        assert sent["type"] == "error"
        assert sent["data"]["code"] == "workspace_access_denied"

    async def test_unsubscribe_removes_workspace(
        self,
        context: MessageContext,
        topic_manager: TopicManager,
        mock_connection_manager: MagicMock,
    ) -> None:
        workspace_id = "ws-002"
        session_id = context.session_id

        await topic_manager.subscribe(session_id, f"workspace:{workspace_id}")
        mock_task = MagicMock()
        mock_connection_manager.status_tasks[session_id] = {
            f"workspace:{workspace_id}": mock_task,
        }

        handler = UnsubscribeWorkspaceHandler()

        with patch(
            f"{_HANDLER_MODULE}.get_topic_manager",
            return_value=topic_manager,
        ):
            await handler.handle(context, {"workspace_id": workspace_id})

        assert not topic_manager.is_subscribed(session_id, f"workspace:{workspace_id}")

        mock_task.cancel.assert_called_once()
        assert f"workspace:{workspace_id}" not in mock_connection_manager.status_tasks.get(
            session_id, {}
        )

        context.websocket.send_json.assert_called_once()
        ack_msg = context.websocket.send_json.call_args[0][0]
        assert ack_msg["type"] == "ack"
        assert ack_msg["action"] == "unsubscribe_workspace"

    async def test_presence_heartbeat_updates_timestamp(
        self,
        context: MessageContext,
        mock_redis: AsyncMock,
    ) -> None:
        handler = WorkspaceHeartbeatHandler()
        workspace_id = "ws-003"

        await handler.handle(context, {"workspace_id": workspace_id})

        expected_hash_key = f"workspace:{workspace_id}:presence:user:{context.user_id}"
        mock_redis.hset.assert_called_once()
        call_args = mock_redis.hset.call_args
        assert call_args[0][0] == expected_hash_key
        assert call_args[0][1] == "last_heartbeat"
        ts_value = call_args[0][2]
        assert isinstance(ts_value, str)
        datetime.fromisoformat(ts_value)

        mock_redis.expire.assert_called_once_with(expected_hash_key, 300)

        context.websocket.send_json.assert_called_once()
        ack_msg = context.websocket.send_json.call_args[0][0]
        assert ack_msg["type"] == "ack"
        assert ack_msg["action"] == "workspace_heartbeat"

    async def test_chat_event_broadcast_to_subscribers(
        self,
        context: MessageContext,
        topic_manager: TopicManager,
    ) -> None:
        handler = SubscribeWorkspaceHandler()
        workspace_id = "ws-004"

        chat_envelope = EventEnvelope(
            event_type="workspace.chat.new_message",
            payload={"content": "Hello workspace!"},
            event_id="evt_chat001",
            timestamp=datetime.now(UTC).isoformat(),
        )
        chat_event = EventWithMetadata(
            envelope=chat_envelope,
            routing_key=f"workspace:{workspace_id}:chat",
            sequence_id="1234-0",
        )

        async def fake_subscribe(pattern: str, options: SubscriptionOptions | None = None) -> Any:
            yield chat_event

        with patch(
            f"{_HANDLER_MODULE}.RedisUnifiedEventBusAdapter",
        ) as MockBusClass:
            mock_bus = MagicMock()
            mock_bus.subscribe = fake_subscribe
            MockBusClass.return_value = mock_bus

            await handler._workspace_bridge_loop(context, workspace_id, AsyncMock())

        context.websocket.send_json.assert_called_once()
        sent = context.websocket.send_json.call_args[0][0]
        assert sent["type"] == "workspace.chat.new_message"
        assert sent["routing_key"] == f"workspace:{workspace_id}:chat"
        assert sent["workspace_id"] == workspace_id
        assert sent["data"] == {"content": "Hello workspace!"}
        assert sent["event_id"] == "evt_chat001"

    async def test_agent_status_event_delivered(
        self,
        context: MessageContext,
    ) -> None:
        handler = SubscribeWorkspaceHandler()
        workspace_id = "ws-005"

        status_envelope = EventEnvelope(
            event_type="workspace.agent_status.changed",
            payload={
                "agent_id": "agent-42",
                "status": "busy",
                "display_name": "ResearchBot",
            },
            event_id="evt_agent001",
            timestamp=datetime.now(UTC).isoformat(),
        )
        status_event = EventWithMetadata(
            envelope=status_envelope,
            routing_key=f"workspace:{workspace_id}:agent_status",
            sequence_id="5678-0",
        )

        async def fake_subscribe(pattern: str, options: SubscriptionOptions | None = None) -> Any:
            yield status_event

        with patch(
            f"{_HANDLER_MODULE}.RedisUnifiedEventBusAdapter",
        ) as MockBusClass:
            mock_bus = MagicMock()
            mock_bus.subscribe = fake_subscribe
            MockBusClass.return_value = mock_bus

            await handler._workspace_bridge_loop(context, workspace_id, AsyncMock())

        context.websocket.send_json.assert_called_once()
        sent = context.websocket.send_json.call_args[0][0]
        assert sent["type"] == "workspace.agent_status.changed"
        assert sent["routing_key"] == f"workspace:{workspace_id}:agent_status"
        assert sent["workspace_id"] == workspace_id
        assert sent["data"]["agent_id"] == "agent-42"
        assert sent["data"]["status"] == "busy"
        assert sent["data"]["display_name"] == "ResearchBot"
        assert sent["event_id"] == "evt_agent001"

    async def test_workspace_bridge_stops_forwarding_after_membership_revoked(
        self,
        context: MessageContext,
        topic_manager: TopicManager,
        mock_container: MagicMock,
    ) -> None:
        handler = SubscribeWorkspaceHandler()
        workspace_id = "ws-006"
        mock_container.mock_member_repo.find_by_workspace_and_user.return_value = None

        chat_envelope = EventEnvelope(
            event_type="workspace.chat.new_message",
            payload={"content": "Should not deliver"},
            event_id="evt_chat_revoke",
            timestamp=datetime.now(UTC).isoformat(),
        )
        chat_event = EventWithMetadata(
            envelope=chat_envelope,
            routing_key=f"workspace:{workspace_id}:chat",
            sequence_id="9999-0",
        )

        async def fake_subscribe(pattern: str, options: SubscriptionOptions | None = None) -> Any:
            yield chat_event

        with (
            patch(f"{_HANDLER_MODULE}.get_topic_manager", return_value=topic_manager),
            patch(f"{_HANDLER_MODULE}.RedisUnifiedEventBusAdapter") as mock_bus_class,
        ):
            mock_bus = MagicMock()
            mock_bus.subscribe = fake_subscribe
            mock_bus_class.return_value = mock_bus

            await handler._workspace_bridge_loop(context, workspace_id, AsyncMock())

        sent = context.websocket.send_json.call_args[0][0]
        assert sent["type"] == "error"
        assert sent["data"]["code"] == "workspace_access_denied"
