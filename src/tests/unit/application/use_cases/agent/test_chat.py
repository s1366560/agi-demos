import logging
from typing import Any

import pytest

from src.application.use_cases.agent.chat import ChatUseCase


class _FakeAgentService:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def stream_chat_v2(self, **kwargs: Any):
        self.calls.append(kwargs)
        yield {"type": "message", "data": {"content": "hello"}}


@pytest.mark.asyncio
async def test_execute_streams_events_without_logging_user_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    service = _FakeAgentService()
    use_case = ChatUseCase(agent_service=service)
    sensitive_message = "secret-token-should-not-appear in logs"

    with caplog.at_level(logging.INFO, logger="src.application.use_cases.agent.chat"):
        events = [
            event
            async for event in use_case.execute(
                conversation_id="conversation-1",
                user_message=sensitive_message,
                project_id="project-1",
                user_id="user-1",
                tenant_id="tenant-1",
                app_model_context={"surface": "unit-test"},
            )
        ]

    assert events == [{"type": "message", "data": {"content": "hello"}}]
    assert service.calls == [
        {
            "conversation_id": "conversation-1",
            "user_message": sensitive_message,
            "project_id": "project-1",
            "user_id": "user-1",
            "tenant_id": "tenant-1",
            "app_model_context": {"surface": "unit-test"},
        }
    ]
    assert sensitive_message not in caplog.text
    assert "secret-token-should-not-appear" not in caplog.text
