"""Pinned Redis authority coverage for Agent execution status HTTP reads."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
import redis.asyncio as redis
from fastapi import HTTPException, Request

from src.infrastructure.adapters.primary.web.routers.agent import messages
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.plugins.v2.boundary import (
    clear_process_generation_host_v2,
    install_process_generation_host_v2,
    pin_generation_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


class _TrackedRedisClient:
    def __init__(self, name: str) -> None:
        self.name = name
        self.close_calls = 0
        self.calls: list[tuple[str, str]] = []
        self.reload_generation = None
        self.values = {"agent:running:conversation-1": "message-1"}

    async def exists(self, key: str) -> int:
        self.calls.append(("exists", key))
        reload_generation = self.reload_generation
        self.reload_generation = None
        if reload_generation is not None:
            await reload_generation()
        return int(key in self.values)

    async def get(self, key: str) -> str | None:
        self.calls.append(("get", key))
        return self.values.get(key)

    async def xinfo_stream(self, key: str) -> dict[str, int]:
        self.calls.append(("xinfo_stream", key))
        return {"length": 1}

    async def xrevrange(
        self, key: str, *, count: int = 1
    ) -> list[tuple[bytes, dict[bytes, bytes]]]:
        self.calls.append(("xrevrange", key))
        return [
            (
                b"1-0",
                {b"data": json.dumps({"event_time_us": 123_456, "event_counter": 7}).encode()},
            )
        ][:count]

    async def aclose(self) -> None:
        self.close_calls += 1


class _StaticContainerRedisProbe:
    def __init__(self, fallback: object) -> None:
        self.fallback = fallback
        self.accesses = 0
        self.event_repo = SimpleNamespace(get_last_event_time=AsyncMock(return_value=(0, 0)))

    @property
    def redis_client(self) -> object:
        self.accesses += 1
        return self.fallback

    def agent_execution_event_repository(self) -> object:
        return self.event_repo


def _request() -> Request:
    return cast(
        Request,
        SimpleNamespace(
            method="GET",
            url=SimpleNamespace(path="/api/v1/agent/conversations/conversation-1/status"),
        ),
    )


def _bind_route(
    monkeypatch: pytest.MonkeyPatch,
    container: _StaticContainerRedisProbe,
) -> MagicMock:
    get_container = MagicMock(return_value=container)
    monkeypatch.setattr(messages, "_verify_conversation_access", AsyncMock(return_value=None))
    monkeypatch.setattr(messages, "get_container_with_db", get_container)
    monkeypatch.setattr(redis, "Redis", _TrackedRedisClient)
    return get_container


async def _read_status(*, include_recovery_info: bool) -> dict[str, Any]:
    return await messages.get_conversation_execution_status(
        "conversation-1",
        request=_request(),
        project_id="project-1",
        include_recovery_info=include_recovery_info,
        from_time_us=100_000,
        current_user=cast(User, SimpleNamespace(id="user-1")),
        tenant_id="tenant-1",
        db=cast(Any, SimpleNamespace()),
    )


async def test_execution_status_uses_exact_request_generation_redis_during_reload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_client = _TrackedRedisClient("first")
    second_client = _TrackedRedisClient("second")
    clients = iter((first_client, second_client))

    async def redis_factory() -> _TrackedRedisClient:
        return next(clients)

    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(redis_runtime_factory=redis_factory)
    )
    first = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=931,
        version=931,
    )
    assert first.accepted is True
    install_process_generation_host_v2(host)

    async def reload_generation() -> None:
        second = await host.bootstrap(
            profile_path=_PROFILE_PATH,
            manifest_paths=(_MANIFEST_PATH,),
            generation=932,
            version=932,
        )
        assert second.accepted is True
        assert first_client.close_calls == 0

    first_client.reload_generation = reload_generation
    static_client = _TrackedRedisClient("static")
    static_probe = _StaticContainerRedisProbe(static_client)
    get_container = _bind_route(monkeypatch, static_probe)

    try:
        async with pin_generation_v2(host):
            result = await _read_status(include_recovery_info=True)
            assert first_client.close_calls == 0

        assert result == {
            "conversation_id": "conversation-1",
            "is_running": True,
            "current_message_id": "message-1",
            "recovery": {
                "can_recover": True,
                "last_event_time_us": 123_456,
                "last_event_counter": 7,
                "stream_exists": True,
                "recovery_source": "stream",
            },
        }
        get_container.assert_not_called()
        assert static_probe.accesses == 0
        assert first_client.calls == [
            ("exists", "agent:running:conversation-1"),
            ("get", "agent:running:conversation-1"),
            ("xinfo_stream", "agent:events:conversation-1"),
            ("xrevrange", "agent:events:conversation-1"),
        ]
        assert second_client.calls == []
        assert first_client.close_calls == 1
        assert second_client.close_calls == 0
    finally:
        clear_process_generation_host_v2(host)
        await host.close()

    assert second_client.close_calls == 1


async def test_execution_status_rejects_when_v2_redis_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=933,
        version=933,
    )
    assert publication.accepted is True
    install_process_generation_host_v2(host)

    static_client = _TrackedRedisClient("static")
    static_probe = _StaticContainerRedisProbe(static_client)
    get_container = _bind_route(monkeypatch, static_probe)

    try:
        async with pin_generation_v2(host):
            with pytest.raises(HTTPException) as error:
                await _read_status(include_recovery_info=False)
    finally:
        clear_process_generation_host_v2(host)
        await host.close()

    assert error.value.status_code == 503
    assert error.value.detail == {
        "code": "agent_worker_redis_unavailable",
        "message": "Agent execution status authority is unavailable",
    }
    get_container.assert_not_called()
    assert static_probe.accesses == 0
    assert static_client.calls == []
