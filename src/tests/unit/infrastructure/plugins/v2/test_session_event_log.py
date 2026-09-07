"""Provider/Consumer coverage for the generation-scoped session event log."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.agent.actor import execution
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.session_event_log import (
    SESSION_EVENT_LOG_SERVICE_V2,
    SessionEventCursorV2,
    SessionEventLogServiceV2,
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
        provider = operation.require(SESSION_EVENT_LOG_SERVICE_V2)
        assert isinstance(provider, SessionEventLogServiceV2)
        with patch.object(
            SessionEventLogServiceV2,
            "append",
            new_callable=AsyncMock,
        ) as append:
            await execution._persist_events(
                conversation_id="conversation-a",
                message_id="message-a",
                events=events,
                correlation_id="correlation-a",
            )

    append.assert_awaited_once_with(
        conversation_id="conversation-a",
        message_id="message-a",
        events=events,
        correlation_id="correlation-a",
    )
    await host.close()


@pytest.mark.unit
async def test_actor_persistence_requires_a_pinned_generation() -> None:
    with pytest.raises(RuntimeV2Error) as error:
        await execution._persist_events(
            conversation_id="conversation-a",
            message_id="message-a",
            events=[{"type": "status", "data": {"status": "running"}}],
        )

    assert error.value.code == "operation_context_not_pinned"


@pytest.mark.unit
async def test_actor_persistence_propagates_missing_service() -> None:
    from src.infrastructure.plugins.v2 import boundary

    operation = MagicMock()
    operation.require.side_effect = RuntimeV2Error(
        "service_not_found",
        "session event-log service is not available",
    )
    with (
        patch.object(boundary, "current_operation_context_v2", return_value=operation),
        pytest.raises(RuntimeV2Error) as error,
    ):
        await execution._persist_events(
            conversation_id="conversation-a",
            message_id="message-a",
            events=[{"type": "status", "data": {"status": "running"}}],
        )

    assert error.value.code == "service_not_found"


@pytest.mark.unit
async def test_actor_tail_cursor_consumes_generation_event_log_provider() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
    )

    async with pin_operation_context_v2(
        host,
        operation_id="session-event-log-cursor-consumer",
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
    ):
        with patch.object(
            SessionEventLogServiceV2,
            "last_cursor",
            new=AsyncMock(return_value=SessionEventCursorV2(event_time_us=900, event_counter=7)),
        ) as last_cursor:
            cursor = await execution._get_last_db_event_time("conversation-a")

    assert cursor == (900, 7)
    last_cursor.assert_awaited_once_with(conversation_id="conversation-a")
    await host.close()


@pytest.mark.unit
async def test_actor_tail_cursor_propagates_storage_failure() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
    )

    async with pin_operation_context_v2(
        host,
        operation_id="session-event-log-cursor-failure",
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
    ):
        with (
            patch.object(
                SessionEventLogServiceV2,
                "last_cursor",
                new=AsyncMock(side_effect=OSError("database unavailable")),
            ),
            pytest.raises(OSError, match="database unavailable"),
        ):
            await execution._get_last_db_event_time("conversation-a")

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
                SESSION_EVENT_LOG_SERVICE_V2,
                ScopeV2(kind=ScopeKindV2.ROOT),
            ),
            SessionEventLogServiceV2,
        )

    await host.close()

    with pytest.raises(RuntimeError, match="generation is disposed"):
        generation.resolve(
            SESSION_EVENT_LOG_SERVICE_V2,
            ScopeV2(kind=ScopeKindV2.ROOT),
        )
