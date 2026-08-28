"""Pinned Redis authority coverage for Agent WebSocket control commands."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.adapters.primary.web.websocket.handlers.control_handler import (
    SteerSubAgentHandler,
)
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


class _Result:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


class _TrackedRedisClient:
    def __init__(self, name: str) -> None:
        self.name = name
        self.close_calls = 0
        self.calls: list[tuple[str, str]] = []
        self.reload_generation = None
        self.values = {
            "subagent:state:conversation-1:execution-1": json.dumps(
                {
                    "execution_id": "execution-1",
                    "subagent_id": "agent-1",
                    "subagent_name": "Researcher",
                    "conversation_id": "conversation-1",
                    "status": "running",
                }
            )
        }

    async def get(self, key: str) -> str | None:
        self.calls.append(("get", key))
        reload_generation = self.reload_generation
        self.reload_generation = None
        if reload_generation is not None:
            await reload_generation()
        return self.values.get(key)

    async def set(self, key: str, value: str, **kwargs: object) -> bool:
        self.calls.append(("set", key))
        if kwargs.get("nx") and key in self.values:
            return False
        self.values[key] = value
        return True

    async def delete(self, key: str) -> int:
        self.calls.append(("delete", key))
        return int(self.values.pop(key, None) is not None)

    async def aclose(self) -> None:
        self.close_calls += 1


class _StaticContainerRedisProbe:
    def __init__(self, fallback: object) -> None:
        self.fallback = fallback
        self.accesses = 0

    @property
    def redis_client(self) -> object:
        self.accesses += 1
        return self.fallback


def _message_context(static_redis: object) -> tuple[SimpleNamespace, _StaticContainerRedisProbe]:
    conversation = SimpleNamespace(
        id="conversation-1",
        project_id="project-1",
        participant_agents=["agent-1"],
    )
    parent_run = SimpleNamespace(id="parent-run-1", revision=7, status="running")
    probe = _StaticContainerRedisProbe(static_redis)
    context = SimpleNamespace(
        user_id="user-1",
        tenant_id="tenant-1",
        db=SimpleNamespace(
            execute=AsyncMock(side_effect=[_Result(conversation), _Result(parent_run)])
        ),
        container=probe,
        send_json=AsyncMock(),
    )
    return context, probe


def _command() -> dict[str, Any]:
    return {
        "type": "steer",
        "conversation_id": "conversation-1",
        "run_id": "execution-1",
        "instruction": "Inspect the failed authority test.",
        "expected_run_revision": 7,
        "idempotency_key": "control-key-1",
    }


async def test_websocket_control_uses_connection_generation_redis_during_reload(
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
        generation=921,
        version=921,
    )
    assert first.accepted is True
    install_process_generation_host_v2(host)

    async def reload_generation() -> None:
        second = await host.bootstrap(
            profile_path=_PROFILE_PATH,
            manifest_paths=(_MANIFEST_PATH,),
            generation=922,
            version=922,
        )
        assert second.accepted is True
        assert first_client.close_calls == 0

    first_client.reload_generation = reload_generation
    observed_clients: list[object] = []

    async def send_control(channel: object, _message: object) -> bool:
        observed_clients.append(channel._redis)  # type: ignore[attr-defined]
        return True

    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.websocket.handlers.control_handler."
        "RedisControlChannel.send_control",
        send_control,
    )
    static_client = _TrackedRedisClient("static")
    context, static_probe = _message_context(static_client)

    try:
        async with pin_generation_v2(host):
            await SteerSubAgentHandler().handle(context, _command())
            assert first_client.close_calls == 0

        ack = context.send_json.await_args.args[0]
        assert ack["accepted"] is True
        assert observed_clients == [first_client]
        assert static_probe.accesses == 0
        assert first_client.calls
        assert second_client.calls == []
        assert first_client.close_calls == 1
        assert second_client.close_calls == 0
    finally:
        clear_process_generation_host_v2(host)
        await host.close()

    assert second_client.close_calls == 1


async def test_websocket_control_rejects_when_v2_redis_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=923,
        version=923,
    )
    assert publication.accepted is True
    install_process_generation_host_v2(host)

    send_control = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.websocket.handlers.control_handler."
        "RedisControlChannel.send_control",
        send_control,
    )
    static_client = _TrackedRedisClient("static")
    context, static_probe = _message_context(static_client)

    try:
        async with pin_generation_v2(host):
            await SteerSubAgentHandler().handle(context, _command())
    finally:
        clear_process_generation_host_v2(host)
        await host.close()

    ack = context.send_json.await_args.args[0]
    assert ack["accepted"] is False
    assert ack["reason_code"] == "control_authority_unavailable"
    assert static_probe.accesses == 0
    send_control.assert_not_awaited()
