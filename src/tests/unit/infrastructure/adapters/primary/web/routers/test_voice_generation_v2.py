"""Voice WebSocket agent-turn generation boundary tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from inspect import getsource
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.adapters.primary.web.routers import voice_websocket
from src.infrastructure.adapters.secondary.persistence import database
from src.infrastructure.plugins.v2.agent_turn_services import (
    AGENT_TURN_MODULE_V2,
    AgentTurnResolverV2,
)
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    OPERATION_PLUGIN_DISTRIBUTION_SERVICE_V2,
    clear_process_generation_host_v2,
    current_operation_context_v2,
    install_process_generation_host_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import ProfileDocumentV2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

_ROOT = Path(__file__).resolve().parents[8]


@pytest.mark.unit
async def test_voice_agent_turn_pins_complete_stream_with_operation_services(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
        nonce="voice-agent-turn",
    )
    install_process_generation_host_v2(host)
    fresh_db = object()

    class SessionContext:
        async def __aenter__(self) -> object:
            return fresh_db

        async def __aexit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(database, "async_session_factory", SessionContext)
    shutdown = asyncio.Event()
    observed: dict[str, object] = {}

    class AgentService:
        async def stream_chat_v2(self, **_kwargs: Any):
            operation = current_operation_context_v2()
            observed["operation_id"] = operation.operation_id
            observed["db"] = operation.require(OPERATION_DB_SESSION_SERVICE_V2)
            observed["identity"] = operation.require(OPERATION_IDENTITY_SERVICE_V2)
            observed["metadata"] = operation.require(OPERATION_METADATA_SERVICE_V2)
            observed["distribution"] = operation.require(OPERATION_PLUGIN_DISTRIBUTION_SERVICE_V2)
            shutdown.set()
            yield {"type": "complete", "data": {"content": "voice response"}}

    async def resolve_turn(
        self: AgentTurnResolverV2,
        _operation: object,
    ) -> AgentService:
        observed["resolver"] = self
        return AgentService()

    monkeypatch.setattr(AgentTurnResolverV2, "resolve", resolve_turn)
    websocket = SimpleNamespace(send_json=AsyncMock())
    asr_queue: asyncio.Queue[str] = asyncio.Queue()
    await asr_queue.put("hello")
    tts_queue: asyncio.Queue[str | None] = asyncio.Queue()

    try:
        await asyncio.wait_for(
            voice_websocket._agent_bridge(
                websocket=websocket,
                asr_final_queue=asr_queue,
                tts_text_queue=tts_queue,
                conversation_id="conversation-1",
                project_id="project-1",
                user_id="user-1",
                tenant_id="tenant-1",
                api_key="redacted-test-token",
                shutdown=shutdown,
            ),
            timeout=2.0,
        )

        assert str(observed["operation_id"]).startswith("voice-turn:")
        assert isinstance(observed["resolver"], AgentTurnResolverV2)
        assert observed["db"] is fresh_db
        assert observed["identity"] == {
            "tenant_id": "tenant-1",
            "user_id": "user-1",
            "project_id": "project-1",
        }
        assert observed["metadata"] == {
            "kind": "agent-turn",
            "channel": "voice",
            "conversation_id": "conversation-1",
        }
        distribution = observed["distribution"]
        assert isinstance(distribution, dict)
        assert distribution["descriptor"]["generation"] == 1
    finally:
        clear_process_generation_host_v2(host)
        await host.close()


@pytest.mark.unit
async def test_voice_error_closes_stream_before_operation_and_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    fresh_db = object()

    class SessionContext:
        async def __aenter__(self) -> object:
            return fresh_db

        async def __aexit__(self, *_args: object) -> None:
            order.append("db-closed")

    @asynccontextmanager
    async def ordered_operation(**_kwargs: object) -> AsyncIterator[None]:
        try:
            yield None
        finally:
            order.append("operation-closed")

    shutdown = asyncio.Event()

    class AgentService:
        async def stream_chat_v2(self, **_kwargs: Any):
            try:
                shutdown.set()
                yield {"type": "error", "data": {"message": "failed"}}
                yield {"type": "complete", "data": {"content": "late"}}
            finally:
                order.append("stream-closed")

    monkeypatch.setattr(database, "async_session_factory", SessionContext)
    monkeypatch.setattr(
        voice_websocket,
        "pin_agent_turn_operation_v2",
        ordered_operation,
    )
    monkeypatch.setattr(
        voice_websocket,
        "current_agent_turn_service_v2",
        AsyncMock(return_value=AgentService()),
    )
    websocket = SimpleNamespace(send_json=AsyncMock())
    asr_queue: asyncio.Queue[str] = asyncio.Queue()
    await asr_queue.put("hello")
    tts_queue: asyncio.Queue[str | None] = asyncio.Queue()

    await asyncio.wait_for(
        voice_websocket._agent_bridge(
            websocket=websocket,
            asr_final_queue=asr_queue,
            tts_text_queue=tts_queue,
            conversation_id="conversation-1",
            project_id="project-1",
            user_id="user-1",
            tenant_id="tenant-1",
            api_key="redacted-test-token",
            shutdown=shutdown,
        ),
        timeout=2.0,
    )

    assert order == ["stream-closed", "operation-closed", "db-closed"]


@pytest.mark.unit
async def test_voice_turn_rejects_missing_v2_service_without_static_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def disable_turn_service(document: ProfileDocumentV2) -> ProfileDocumentV2:
        return replace(
            document,
            entries=tuple(
                replace(entry, enabled=False) if entry.module_ref == AGENT_TURN_MODULE_V2 else entry
                for entry in document.entries
            ),
        )

    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=2,
        version=2,
        nonce="voice-agent-turn-missing-service",
        profile_projector=disable_turn_service,
    )
    assert publication.accepted is True
    install_process_generation_host_v2(host)
    fresh_db = object()

    class SessionContext:
        async def __aenter__(self) -> object:
            return fresh_db

        async def __aexit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(database, "async_session_factory", SessionContext)
    shutdown = asyncio.Event()

    async def send_json(payload: dict[str, object]) -> None:
        if payload.get("type") == "error":
            shutdown.set()

    websocket = SimpleNamespace(send_json=AsyncMock(side_effect=send_json))
    asr_queue: asyncio.Queue[str] = asyncio.Queue()
    await asr_queue.put("hello")
    tts_queue: asyncio.Queue[str | None] = asyncio.Queue()

    try:
        await asyncio.wait_for(
            voice_websocket._agent_bridge(
                websocket=websocket,
                asr_final_queue=asr_queue,
                tts_text_queue=tts_queue,
                conversation_id="conversation-1",
                project_id="project-1",
                user_id="user-1",
                tenant_id="tenant-1",
                api_key="redacted-test-token",
                shutdown=shutdown,
            ),
            timeout=2.0,
        )

        websocket.send_json.assert_any_await(
            {
                "type": "error",
                "message": (
                    "service service:agent.turn-service@1.0.0 is unavailable for scope session"
                ),
                "code": "missing_service",
            }
        )
    finally:
        clear_process_generation_host_v2(host)
        await host.close()


def test_voice_turn_has_no_static_llm_or_di_composition() -> None:
    source = getsource(voice_websocket.voice_chat_endpoint) + getsource(
        voice_websocket._agent_bridge
    )

    assert "create_llm_client" not in source
    assert "DIContainer" not in source
    assert ".agent_service(" not in source
