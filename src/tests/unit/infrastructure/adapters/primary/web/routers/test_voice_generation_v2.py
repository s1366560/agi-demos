"""Voice WebSocket agent-turn generation boundary tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.adapters.primary.web.routers import voice_websocket
from src.infrastructure.adapters.secondary.persistence import database
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

    scoped_container = SimpleNamespace(agent_service=lambda _llm: AgentService())
    base_container = SimpleNamespace(
        with_db=lambda db: scoped_container if db is fresh_db else None
    )
    websocket = SimpleNamespace(send_json=AsyncMock())
    asr_queue: asyncio.Queue[str] = asyncio.Queue()
    await asr_queue.put("hello")
    tts_queue: asyncio.Queue[str | None] = asyncio.Queue()

    try:
        await asyncio.wait_for(
            voice_websocket._agent_bridge(
                websocket=websocket,
                base_container=base_container,
                llm=object(),
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
    scoped_container = SimpleNamespace(agent_service=lambda _llm: AgentService())
    base_container = SimpleNamespace(
        with_db=lambda db: scoped_container if db is fresh_db else None
    )
    websocket = SimpleNamespace(send_json=AsyncMock())
    asr_queue: asyncio.Queue[str] = asyncio.Queue()
    await asr_queue.put("hello")
    tts_queue: asyncio.Queue[str | None] = asyncio.Queue()

    await asyncio.wait_for(
        voice_websocket._agent_bridge(
            websocket=websocket,
            base_container=base_container,
            llm=object(),
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
