"""WebSocket client-turn generation boundary tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.adapters.primary.web.websocket.handlers import chat_handler
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    OPERATION_PLUGIN_DISTRIBUTION_SERVICE_V2,
    clear_process_generation_host_v2,
    current_operation_context_v2,
    install_process_generation_host_v2,
    pin_generation_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

_ROOT = Path(__file__).resolve().parents[8]


class _ConnectionManager:
    def __init__(self) -> None:
        self.broadcasts: list[tuple[str, dict[str, Any]]] = []
        self.errors: list[tuple[str, dict[str, Any]]] = []

    def is_subscribed(self, _session_id: str, _conversation_id: str) -> bool:
        return True

    async def broadcast_to_conversation(
        self,
        conversation_id: str,
        event: dict[str, Any],
    ) -> None:
        self.broadcasts.append((conversation_id, event))

    async def send_to_session(self, session_id: str, event: dict[str, Any]) -> None:
        self.errors.append((session_id, event))


class _TurnContext:
    tenant_id = "tenant-1"
    user_id = "user-1"
    session_id = "websocket-session-1"
    api_key = "redacted-test-token"
    db = object()

    def __init__(self) -> None:
        self.connection_manager = _ConnectionManager()


@pytest.mark.unit
async def test_websocket_agent_turn_reuses_outer_generation_and_publishes_complete_services(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
        nonce="websocket-turn-1",
    )
    install_process_generation_host_v2(host)
    context = _TurnContext()
    observed: dict[str, object] = {}

    class AgentService:
        async def stream_chat_v2(self, **_kwargs: Any):
            operation = current_operation_context_v2()
            observed["generation"] = operation.descriptor.generation
            observed["db"] = operation.require(OPERATION_DB_SESSION_SERVICE_V2)
            observed["identity"] = operation.require(OPERATION_IDENTITY_SERVICE_V2)
            observed["metadata"] = operation.require(OPERATION_METADATA_SERVICE_V2)
            observed["distribution"] = operation.require(OPERATION_PLUGIN_DISTRIBUTION_SERVICE_V2)
            yield {"type": "complete", "data": {"content": "done"}}

    monkeypatch.setattr(chat_handler, "_load_external_acp_backend", AsyncMock(return_value=None))

    try:
        async with pin_generation_v2(host) as outer_generation:
            await host.bootstrap(
                profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
                manifest_paths=(
                    _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",
                ),
                generation=2,
                version=2,
                nonce="websocket-turn-2",
            )
            await chat_handler.stream_agent_to_websocket(
                agent_service=AgentService(),  # type: ignore[arg-type]
                context=context,  # type: ignore[arg-type]
                conversation_id="conversation-1",
                user_message="hello",
                project_id="project-1",
                execution_message_id="turn-1",
            )

            assert observed["generation"] == outer_generation.generation == 1
        assert observed["db"] is context.db
        assert observed["identity"] == {
            "tenant_id": "tenant-1",
            "user_id": "user-1",
            "project_id": "project-1",
        }
        assert observed["metadata"] == {
            "kind": "agent-turn",
            "channel": "websocket",
            "conversation_id": "conversation-1",
            "execution_message_id": "turn-1",
        }
        distribution = observed["distribution"]
        assert isinstance(distribution, dict)
        assert distribution["descriptor"]["generation"] == 1
        assert context.connection_manager.errors == []
        assert len(context.connection_manager.broadcasts) == 1
    finally:
        clear_process_generation_host_v2(host)
        await host.close()


@pytest.mark.unit
async def test_websocket_agent_turn_fails_closed_without_process_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unconfigured_host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    install_process_generation_host_v2(unconfigured_host)
    clear_process_generation_host_v2(unconfigured_host)
    await unconfigured_host.close()
    context = _TurnContext()
    called = False

    class AgentService:
        async def stream_chat_v2(self, **_kwargs: Any):
            nonlocal called
            called = True
            yield {"type": "complete"}

    monkeypatch.setattr(chat_handler, "_load_external_acp_backend", AsyncMock(return_value=None))

    await chat_handler.stream_agent_to_websocket(
        agent_service=AgentService(),  # type: ignore[arg-type]
        context=context,  # type: ignore[arg-type]
        conversation_id="conversation-1",
        user_message="hello",
        project_id="project-1",
        execution_message_id="turn-1",
    )

    assert called is False
    assert context.connection_manager.broadcasts == []
    assert len(context.connection_manager.errors) == 1
    error = context.connection_manager.errors[0][1]
    assert error["data"]["message"] == "plugin generation host is not configured for this process"


@pytest.mark.unit
async def test_websocket_unsubscribe_closes_agent_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _TurnContext()
    context.connection_manager.is_subscribed = lambda *_args: False  # type: ignore[method-assign]
    closed = False

    class AgentService:
        async def stream_chat_v2(self, **_kwargs: Any):
            nonlocal closed
            try:
                yield {"type": "text_delta", "data": {"delta": "partial"}}
                yield {"type": "complete", "data": {"content": "late"}}
            finally:
                closed = True

    monkeypatch.setattr(chat_handler, "_load_external_acp_backend", AsyncMock(return_value=None))

    await chat_handler._stream_agent_to_websocket_pinned(
        agent_service=AgentService(),  # type: ignore[arg-type]
        context=context,  # type: ignore[arg-type]
        conversation_id="conversation-1",
        user_message="hello",
        project_id="project-1",
    )

    assert closed is True
    assert context.connection_manager.broadcasts == []
