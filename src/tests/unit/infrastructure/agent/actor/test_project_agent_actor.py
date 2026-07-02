"""Unit tests for ProjectAgentActor scheduling behavior."""

import asyncio
from typing import Any
from unittest.mock import patch

import pytest

from src.infrastructure.agent.actor.project_agent_actor import ProjectAgentActor
from src.infrastructure.agent.actor.types import ProjectChatRequest, ProjectChatResult


def _actor_instance() -> Any:
    actor_class = ProjectAgentActor.__ray_metadata__.modified_class
    return actor_class()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_chat_serializes_same_conversation_turns_fifo() -> None:
    """The Ray actor must not run multiple turns for one conversation concurrently."""
    actor = _actor_instance()
    actor._agent = object()
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    started: list[str] = []

    first = ProjectChatRequest(
        conversation_id="conv-1",
        message_id="msg-1",
        user_message="first",
        user_id="user-1",
    )
    second = ProjectChatRequest(
        conversation_id="conv-1",
        message_id="msg-2",
        user_message="second",
        user_id="user-1",
    )

    async def _execute_chat(
        _agent: object,
        request: ProjectChatRequest,
        abort_signal: asyncio.Event | None = None,
    ) -> ProjectChatResult:
        assert abort_signal is not None
        started.append(request.message_id)
        if request.message_id == "msg-1":
            first_started.set()
            await release_first.wait()
        return ProjectChatResult(
            conversation_id=request.conversation_id,
            message_id=request.message_id,
            content="done",
        )

    with patch(
        "src.infrastructure.agent.actor.project_agent_actor.execute_project_chat",
        side_effect=_execute_chat,
    ):
        first_result = await actor.chat(first)
        await first_started.wait()
        second_result = await actor.chat(second)
        await asyncio.sleep(0)

        assert first_result == {"status": "started", "message_id": "msg-1"}
        assert second_result == {"status": "started", "message_id": "msg-2"}
        assert started == ["msg-1"]

        release_first.set()
        for _ in range(20):
            if started == ["msg-1", "msg-2"]:
                break
            await asyncio.sleep(0.01)

    assert started == ["msg-1", "msg-2"]
