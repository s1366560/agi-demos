from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from acp.exceptions import RequestError
from acp.schema import ImageContentBlock, TextContentBlock

from src.infrastructure.acp.server import MemStackACPAgent


class DummySessionFactory:
    def __init__(self) -> None:
        self.commits = 0

    def __call__(self) -> DummySessionFactory:
        return self

    async def __aenter__(self) -> DummySessionFactory:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1


class FakeAgentService:
    def __init__(self, events: list[dict[str, Any]] | None = None) -> None:
        self.created: list[dict[str, Any]] = []
        self.streamed: list[dict[str, Any]] = []
        self.events = events or [{"type": "text_delta", "data": {"delta": "assistant response"}}]

    async def create_conversation(self, **kwargs: Any) -> SimpleNamespace:
        self.created.append(kwargs)
        return SimpleNamespace(id="conversation-1")

    async def stream_chat_v2(self, **kwargs: Any) -> Any:
        self.streamed.append(kwargs)
        for event in self.events:
            yield event


async def test_new_session_creates_conversation_with_project_meta(monkeypatch: pytest.MonkeyPatch) -> None:
    service = FakeAgentService()
    session_factory = DummySessionFactory()
    agent = MemStackACPAgent(
        container=object(),  # type: ignore[arg-type]
        session_factory=session_factory,  # type: ignore[arg-type]
        user_id="user-1",
        tenant_id="tenant-1",
    )
    monkeypatch.setattr(agent, "_agent_service", _agent_service_factory(service))

    response = await agent.new_session(cwd="/tmp/project", mcp_servers=[], memstack={"projectId": "p1"})

    assert response.session_id == "conversation-1"
    assert service.created[0]["project_id"] == "p1"
    assert service.created[0]["agent_config"]["source"] == "acp"
    assert session_factory.commits == 1


async def test_prompt_streams_memstack_events_as_acp_updates(monkeypatch: pytest.MonkeyPatch) -> None:
    service = FakeAgentService()
    emitted: list[dict[str, Any]] = []

    async def emit_update(session_id: str, update: Any) -> None:
        emitted.append({"session_id": session_id, "update": update})

    agent = MemStackACPAgent(
        container=object(),  # type: ignore[arg-type]
        session_factory=DummySessionFactory(),  # type: ignore[arg-type]
        user_id="user-1",
        tenant_id="tenant-1",
        api_key="ms_sk_test",
        emit_update=emit_update,
    )
    monkeypatch.setattr(agent, "_agent_service", _agent_service_factory(service))
    await agent.new_session(cwd="/tmp/project", mcp_servers=[], memstack={"projectId": "p1"})

    response = await agent.prompt(
        session_id="conversation-1",
        prompt=[TextContentBlock(type="text", text="hello")],
        message_id="message-1",
    )

    assert response.stop_reason == "end_turn"
    assert service.streamed[0]["user_message"] == "hello"
    assert service.streamed[0]["api_auth_token"] == "ms_sk_test"
    assert emitted[0]["session_id"] == "conversation-1"
    assert emitted[0]["update"].session_update == "agent_message_chunk"


async def test_prompt_rejects_non_text_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    service = FakeAgentService()
    agent = MemStackACPAgent(
        container=object(),  # type: ignore[arg-type]
        session_factory=DummySessionFactory(),  # type: ignore[arg-type]
        user_id="user-1",
        tenant_id="tenant-1",
    )
    monkeypatch.setattr(agent, "_agent_service", _agent_service_factory(service))
    await agent.new_session(cwd="/tmp/project", mcp_servers=[], memstack={"projectId": "p1"})

    with pytest.raises(RequestError) as exc_info:
        await agent.prompt(
            session_id="conversation-1",
            prompt=[
                ImageContentBlock(
                    type="image",
                    data="abc",
                    mimeType="image/png",
                )
            ],
        )

    assert exc_info.value.code == -32602


async def test_prompt_returns_after_terminal_memstack_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = FakeAgentService(
        events=[
            {"type": "text_delta", "data": {"delta": "PONG"}},
            {"type": "complete", "data": {"message_id": "message-1"}},
            {"type": "text_delta", "data": {"delta": "late"}},
        ]
    )
    emitted: list[Any] = []

    async def emit_update(session_id: str, update: Any) -> None:
        del session_id
        emitted.append(update)

    agent = MemStackACPAgent(
        container=object(),  # type: ignore[arg-type]
        session_factory=DummySessionFactory(),  # type: ignore[arg-type]
        user_id="user-1",
        tenant_id="tenant-1",
        emit_update=emit_update,
    )
    monkeypatch.setattr(agent, "_agent_service", _agent_service_factory(service))
    await agent.new_session(cwd="/tmp/project", mcp_servers=[], memstack={"projectId": "p1"})

    response = await agent.prompt(
        session_id="conversation-1",
        prompt=[TextContentBlock(type="text", text="hello")],
        message_id="message-1",
    )

    assert response.stop_reason == "end_turn"
    assert [update.session_update for update in emitted] == [
        "agent_message_chunk",
        "session_info_update",
    ]


async def test_close_idle_session_does_not_cancel_underlying_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = FakeAgentService()
    cancel_calls = 0

    async def cancel_underlying_execution(conversation_id: str) -> None:
        nonlocal cancel_calls
        cancel_calls += 1
        assert conversation_id == "conversation-1"

    agent = MemStackACPAgent(
        container=object(),  # type: ignore[arg-type]
        session_factory=DummySessionFactory(),  # type: ignore[arg-type]
        user_id="user-1",
        tenant_id="tenant-1",
    )
    monkeypatch.setattr(agent, "_agent_service", _agent_service_factory(service))
    monkeypatch.setattr(agent, "_cancel_underlying_execution", cancel_underlying_execution)
    await agent.new_session(cwd="/tmp/project", mcp_servers=[], memstack={"projectId": "p1"})

    await agent.close_session("conversation-1")

    assert cancel_calls == 0
    with pytest.raises(RequestError):
        await agent.prompt(
            session_id="conversation-1",
            prompt=[TextContentBlock(type="text", text="hello")],
        )


def _agent_service_factory(service: FakeAgentService) -> Any:
    async def _factory(db: object) -> FakeAgentService:
        del db
        return service

    return _factory
