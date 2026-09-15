"""V2 application seam coverage for Agent SubAgent control."""

from __future__ import annotations

import inspect
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.routers.agent.subagent_router import (
    cancel_subagent_execution,
)
from src.infrastructure.plugins.v2.agent_subagent_control_services import (
    AGENT_SUBAGENT_CONTROL_MODULE_V2,
    AGENT_SUBAGENT_CONTROL_SERVICE_V2,
    AgentSubAgentControlUnavailableV2,
    RedisAgentSubAgentControlServiceV2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import load_profile_document_v2
from src.infrastructure.plugins.v2.redis_runtime import RedisRuntimeServiceV2
from src.infrastructure.plugins.v2.runtime import OperationContextV2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"
_NOW = datetime(2026, 8, 29, 9, 15, tzinfo=UTC)


class _RedisClient:
    def __init__(self) -> None:
        self.set = AsyncMock()

    async def aclose(self) -> None:
        return None

    async def scan_iter(self, *, match: str, count: int) -> AsyncIterator[tuple[str, int]]:
        if False:
            yield match, count

    async def delete(self, *_keys: str | bytes) -> int:
        return 0

    async def xadd(
        self,
        _stream: str,
        _fields: dict[str, object],
        *,
        maxlen: int,
        approximate: bool,
    ) -> bytes:
        _ = maxlen, approximate
        return b"1-0"


async def test_subagent_control_writes_cancel_signal_through_generation_redis() -> None:
    redis_client = _RedisClient()
    service = RedisAgentSubAgentControlServiceV2(
        redis_runtime=RedisRuntimeServiceV2(client=redis_client),
        ttl_seconds=600,
        clock=lambda: _NOW,
    )

    await service.request_cancel(
        execution_id="execution-a",
        requested_by="user-a",
        reason=None,
        conversation_id="conversation-a",
    )

    assert redis_client.set.await_count == 2
    key, encoded = redis_client.set.await_args_list[0].args
    assert key == "subagent:cancel:execution-a"
    assert redis_client.set.await_args_list[0].kwargs == {"ex": 600}
    owner_key, owner_payload = redis_client.set.await_args_list[1].args
    assert owner_key == "agent:control:kill:execution-a"
    assert json.loads(owner_payload)["sender_id"] == "user-a"
    assert json.loads(encoded) == {
        "requested_by": "user-a",
        "reason": "Cancelled by user",
        "conversation_id": "conversation-a",
        "timestamp": _NOW.isoformat(),
    }


async def test_subagent_control_fails_closed_when_generation_redis_is_unavailable() -> None:
    service = RedisAgentSubAgentControlServiceV2(
        redis_runtime=RedisRuntimeServiceV2(client=None),
        ttl_seconds=600,
    )

    with pytest.raises(AgentSubAgentControlUnavailableV2):
        await service.request_cancel(
            execution_id="execution-a",
            requested_by="user-a",
            reason="stop",
            conversation_id=None,
        )


async def test_subagent_control_is_resolved_from_the_pinned_generation() -> None:
    redis_client = _RedisClient()
    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(redis_runtime_factory=lambda: redis_client)
    )
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=1009,
        version=1009,
    )
    assert publication.accepted is True
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="agent-subagent-control",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as operation,
        ):
            service = operation.require(AGENT_SUBAGENT_CONTROL_SERVICE_V2)
            assert isinstance(service, RedisAgentSubAgentControlServiceV2)
            assert service.redis_runtime.client is redis_client
            assert service.ttl_seconds == 600
    finally:
        await host.close()


def test_subagent_control_module_is_an_explicit_profile_consumer() -> None:
    profile = load_profile_document_v2(_PROFILE_PATH)
    entry = next(
        entry for entry in profile.entries if entry.module_ref == AGENT_SUBAGENT_CONTROL_MODULE_V2
    )

    assert entry.enabled is True
    assert entry.config == {"strategy": "redis-cancel-signal", "ttl_seconds": 600}
    assert entry.inject == {"redis": "service:runtime.redis-client"}


def test_subagent_control_route_has_no_static_container_or_redis_lookup() -> None:
    source = inspect.getsource(cancel_subagent_execution)

    assert "get_container_with_db" not in source
    assert "container.redis" not in source
    assert "redis_client.set" not in source
