from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from acp.exceptions import RequestError
from acp.schema import ImageContentBlock, TextContentBlock

import src.infrastructure.acp.server as acp_server_module
from src.infrastructure.acp.server import MemStackACPAgent
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    OPERATION_PLUGIN_DISTRIBUTION_SERVICE_V2,
    clear_process_generation_host_v2,
    current_operation_context_v2,
    install_process_generation_host_v2,
    pin_agent_turn_operation_v2 as real_pin_agent_turn_operation_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

_ROOT = Path(__file__).resolve().parents[4]


@asynccontextmanager
async def _noop_agent_turn_operation(**_kwargs: object) -> AsyncIterator[None]:
    yield None


@pytest.fixture(autouse=True)
def _isolate_legacy_acp_tests_from_generation_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        acp_server_module,
        "pin_agent_turn_operation_v2",
        _noop_agent_turn_operation,
        raising=False,
    )


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


async def test_new_session_creates_conversation_with_project_meta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = FakeAgentService()
    session_factory = DummySessionFactory()
    agent = MemStackACPAgent(
        container=object(),  # type: ignore[arg-type]
        session_factory=session_factory,  # type: ignore[arg-type]
        user_id="user-1",
        tenant_id="tenant-1",
    )
    monkeypatch.setattr(agent, "_agent_service", _agent_service_factory(service))

    response = await agent.new_session(
        cwd="/tmp/project", mcp_servers=[], memstack={"projectId": "p1"}
    )

    assert response.session_id == "conversation-1"
    assert service.created[0]["project_id"] == "p1"
    assert service.created[0]["agent_config"]["source"] == "acp"
    assert session_factory.commits == 1


async def test_prompt_streams_memstack_events_as_acp_updates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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


async def test_prompt_pins_acp_turn_with_complete_operation_services(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    class GenerationAwareAgentService(FakeAgentService):
        async def stream_chat_v2(self, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
            operation = current_operation_context_v2()
            observed["operation_id"] = operation.operation_id
            observed["db"] = operation.require(OPERATION_DB_SESSION_SERVICE_V2)
            observed["identity"] = operation.require(OPERATION_IDENTITY_SERVICE_V2)
            observed["metadata"] = operation.require(OPERATION_METADATA_SERVICE_V2)
            observed["distribution"] = operation.require(OPERATION_PLUGIN_DISTRIBUTION_SERVICE_V2)
            async for event in super().stream_chat_v2(**kwargs):
                yield event

    service = GenerationAwareAgentService()
    session_factory = DummySessionFactory()
    agent = MemStackACPAgent(
        container=object(),  # type: ignore[arg-type]
        session_factory=session_factory,  # type: ignore[arg-type]
        user_id="user-1",
        tenant_id="tenant-1",
    )
    monkeypatch.setattr(agent, "_agent_service", _agent_service_factory(service))
    monkeypatch.setattr(
        acp_server_module,
        "pin_agent_turn_operation_v2",
        real_pin_agent_turn_operation_v2,
    )
    await agent.new_session(cwd="/tmp/project", mcp_servers=[], memstack={"projectId": "p1"})
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
        nonce="acp-agent-turn",
    )
    install_process_generation_host_v2(host)

    try:
        response = await agent.prompt(
            session_id="conversation-1",
            prompt=[TextContentBlock(type="text", text="hello")],
            message_id="message-1",
        )

        assert response.stop_reason == "end_turn"
        assert observed["operation_id"] == "acp-turn:message-1"
        assert observed["db"] is session_factory
        assert observed["identity"] == {
            "tenant_id": "tenant-1",
            "user_id": "user-1",
            "project_id": "p1",
        }
        assert observed["metadata"] == {
            "kind": "agent-turn",
            "channel": "acp",
            "conversation_id": "conversation-1",
            "message_id": "message-1",
        }
        distribution = observed["distribution"]
        assert isinstance(distribution, dict)
        assert distribution["descriptor"]["generation"] == 1
    finally:
        clear_process_generation_host_v2(host)
        await host.close()


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


async def test_prompt_closes_terminal_stream_before_operation_and_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []

    class ClosingService(FakeAgentService):
        async def stream_chat_v2(self, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
            self.streamed.append(kwargs)
            try:
                yield {"type": "complete", "data": {"message_id": "message-1"}}
                yield {"type": "text_delta", "data": {"delta": "late"}}
            finally:
                order.append("stream-closed")

    class OrderedSessionFactory(DummySessionFactory):
        async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
            order.append("db-closed")

    @asynccontextmanager
    async def ordered_operation(**_kwargs: object) -> AsyncIterator[None]:
        try:
            yield None
        finally:
            order.append("operation-closed")

    service = ClosingService()
    session_factory = OrderedSessionFactory()
    agent = MemStackACPAgent(
        container=object(),  # type: ignore[arg-type]
        session_factory=session_factory,  # type: ignore[arg-type]
        user_id="user-1",
        tenant_id="tenant-1",
    )
    monkeypatch.setattr(agent, "_agent_service", _agent_service_factory(service))
    monkeypatch.setattr(acp_server_module, "pin_agent_turn_operation_v2", ordered_operation)
    await agent.new_session(cwd="/tmp/project", mcp_servers=[], memstack={"projectId": "p1"})
    order.clear()

    _ = await agent.prompt(
        session_id="conversation-1",
        prompt=[TextContentBlock(type="text", text="hello")],
        message_id="message-1",
    )

    assert order == ["stream-closed", "operation-closed", "db-closed"]


async def test_cancel_underlying_execution_uses_shared_runtime_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.application.services.agent.runtime_cancellation as runtime_cancellation
    import src.infrastructure.adapters.secondary.persistence.sql_conversation_repository as conversation_repository_module

    conversation = SimpleNamespace(
        id="conversation-1",
        tenant_id="tenant-1",
        project_id="project-1",
    )
    cancelled: list[object] = []

    class ConversationRepository:
        def __init__(self, _db: object) -> None:
            pass

        async def find_by_id(self, conversation_id: str) -> object:
            assert conversation_id == "conversation-1"
            return conversation

    async def cancel_conversation_runtime(value: object) -> None:
        cancelled.append(value)

    monkeypatch.setattr(
        conversation_repository_module,
        "SqlConversationRepository",
        ConversationRepository,
    )
    monkeypatch.setattr(
        runtime_cancellation,
        "cancel_conversation_runtime",
        cancel_conversation_runtime,
    )
    agent = MemStackACPAgent(
        container=object(),  # type: ignore[arg-type]
        session_factory=DummySessionFactory(),  # type: ignore[arg-type]
        user_id="user-1",
        tenant_id="tenant-1",
    )

    await agent._cancel_underlying_execution("conversation-1")

    assert cancelled == [conversation]


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
