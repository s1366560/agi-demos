from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from src.domain.events.agent_events import AgentCompletedEvent, AgentMessageReceivedEvent
from src.domain.ports.services.agent_message_bus_port import AgentMessage, AgentMessageType
from src.infrastructure.agent.processor.processor import SessionProcessor


@pytest.mark.unit
class TestAgentAnnouncements:
    async def test_check_agent_announcements_uses_stream_cursor_and_emits_events(self) -> None:
        processor = object.__new__(SessionProcessor)
        processor._announce_session_id = "parent-session"
        processor._last_announce_id = None
        processor._message_bus = AsyncMock()
        payload = {
            "agent_id": "child-agent",
            "session_id": "child-session",
            "result": "done",
            "artifacts": ["artifact-1"],
            "success": True,
            "metadata": {},
        }
        processor._message_bus.receive_messages = AsyncMock(
            return_value=[
                AgentMessage(
                    message_id="msg-1",
                    stream_id="20-0",
                    from_agent_id="child-agent",
                    to_agent_id="parent-agent",
                    session_id="parent-session",
                    content=json.dumps(payload),
                    message_type=AgentMessageType.ANNOUNCE,
                )
            ]
        )
        messages: list[dict[str, object]] = []

        events = await processor._check_agent_announcements(messages)

        processor._message_bus.receive_messages.assert_awaited_once_with(
            agent_id="",
            session_id="parent-session",
            since_id=None,
            limit=10,
        )
        assert processor._last_announce_id == "20-0"
        assert messages == [
            {
                "role": "system",
                "content": (
                    "[Agent Announce] Agent 'child-agent' "
                    "(session child-session) completed successfully: done"
                ),
            }
        ]
        assert [type(event) for event in events] == [
            AgentMessageReceivedEvent,
            AgentCompletedEvent,
        ]
        completed = events[1]
        assert isinstance(completed, AgentCompletedEvent)
        assert completed.session_id == "child-session"
        assert completed.result == "done"
