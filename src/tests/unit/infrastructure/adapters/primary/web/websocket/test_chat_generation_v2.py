"""WebSocket client-turn generation boundary tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest

from src.infrastructure.adapters.primary.web.websocket.handlers import chat_handler
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_PLUGIN_DISTRIBUTION_SERVICE_V2,
    current_operation_context_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime import GenerationLeaseV2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

_ROOT = Path(__file__).resolve().parents[8]


class _ReloadBeforeAcquireHost(PlatformPluginRuntimeHostV2):
    def __init__(self) -> None:
        super().__init__(builtin_runtime_definitions_v2())
        self.reload_before_acquire = False

    async def acquire(self) -> GenerationLeaseV2:
        if self.reload_before_acquire:
            self.reload_before_acquire = False
            await self.bootstrap(
                profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
                manifest_paths=(
                    _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",
                ),
                generation=2,
                version=2,
                nonce="websocket-turn-2",
            )
        return await super().acquire()


class _TurnContext:
    tenant_id = "tenant-1"
    user_id = "user-1"
    db = object()

    def __init__(self, host: PlatformPluginRuntimeHostV2) -> None:
        self.plugin_runtime_host_v2 = host

    @asynccontextmanager
    async def fresh_db_context(self) -> AsyncIterator[_TurnContext]:
        yield self


@pytest.mark.unit
async def test_client_turn_distribution_matches_generation_when_reload_wins_admission_race(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = _ReloadBeforeAcquireHost()
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
        nonce="websocket-turn-1",
    )
    host.reload_before_acquire = True
    observed: list[tuple[int, int]] = []

    async def capture_generation(**_kwargs: Any) -> None:
        operation = current_operation_context_v2()
        distribution = operation.require(OPERATION_PLUGIN_DISTRIBUTION_SERVICE_V2)
        assert isinstance(distribution, dict)
        descriptor = distribution["descriptor"]
        assert isinstance(descriptor, dict)
        observed.append((operation.descriptor.generation, descriptor["generation"]))

    monkeypatch.setattr(chat_handler, "_stream_agent_with_scoped_session", capture_generation)

    await chat_handler.stream_agent_to_websocket_with_fresh_session(
        context=_TurnContext(host),  # type: ignore[arg-type]
        conversation_id="conversation-1",
        user_message="hello",
        project_id="project-1",
        execution_message_id="turn-1",
    )

    assert observed == [(2, 2)]
    await host.close()
