"""Provider/Consumer coverage for the generation-scoped session event log."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.agent.actor import execution
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.session_event_log import (
    SESSION_EVENT_LOG_WRITER_SERVICE_V2,
    SessionEventLogWriterV2,
)

_ROOT = Path(__file__).resolve().parents[6]


@pytest.mark.unit
async def test_actor_persistence_consumes_generation_event_log_provider() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
    )
    events = [{"type": "assistant_message", "data": {"content": "persisted first"}}]

    async with pin_operation_context_v2(
        host,
        operation_id="session-event-log-consumer",
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
    ) as operation:
        provider = operation.require(SESSION_EVENT_LOG_WRITER_SERVICE_V2)
        assert isinstance(provider, SessionEventLogWriterV2)
        with patch.object(
            SessionEventLogWriterV2,
            "persist",
            new_callable=AsyncMock,
        ) as persist:
            await execution._persist_events(
                conversation_id="conversation-a",
                message_id="message-a",
                events=events,
                correlation_id="correlation-a",
            )

    persist.assert_awaited_once_with(
        writer=execution._persist_events_native,
        conversation_id="conversation-a",
        message_id="message-a",
        events=events,
        correlation_id="correlation-a",
    )
    await host.close()


@pytest.mark.unit
async def test_session_event_log_provider_disappears_when_generation_unloads() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
    )
    async with await host.acquire() as generation:
        assert isinstance(
            generation.resolve(
                SESSION_EVENT_LOG_WRITER_SERVICE_V2,
                ScopeV2(kind=ScopeKindV2.ROOT),
            ),
            SessionEventLogWriterV2,
        )

    await host.close()

    with pytest.raises(RuntimeError, match="generation is disposed"):
        generation.resolve(
            SESSION_EVENT_LOG_WRITER_SERVICE_V2,
            ScopeV2(kind=ScopeKindV2.ROOT),
        )
