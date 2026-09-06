"""Pinned V2 Redis authority coverage for active Agent HTTP seams."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from fastapi import Request, status
from fastapi.responses import JSONResponse

from src.infrastructure.adapters.primary.web.routers.agent import run_input_authority
from src.infrastructure.adapters.secondary.persistence.models import AgentRunInputModel, User
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

    async def scan_iter(self, *, match: str, count: int) -> AsyncIterator[str | bytes]:
        for key in ():
            yield key

    async def delete(self, *keys: str | bytes) -> int:
        return 0

    async def xadd(self, *_args: object, **_kwargs: object) -> object:
        raise AssertionError("Redis stream publication is outside this authority fixture")

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


def _request_with_static_redis(probe: _StaticContainerRedisProbe) -> Request:
    return cast(
        Request,
        SimpleNamespace(
            method="POST",
            url=SimpleNamespace(path="/api/v1/agent/runs/run-1/inputs"),
            app=SimpleNamespace(state=SimpleNamespace(container=probe)),
        ),
    )


def _run_input_row() -> AgentRunInputModel:
    now = datetime.now(UTC)
    return cast(
        AgentRunInputModel,
        SimpleNamespace(
            id="input-1",
            tenant_id="tenant-1",
            project_id="project-1",
            conversation_id="conversation-1",
            run_id="run-1",
            actor_user_id="user-1",
            expected_run_revision=7,
            message="Steer on the next Observe boundary.",
            message_id="message-1",
            idempotency_key="input-key-1",
            delivery="steer_now",
            references_json=[],
            context_items_json=[],
            status="pending_boundary",
            sequence=1,
            queue_position=None,
            applied_round=None,
            applied_at=None,
            injected_via=None,
            dispatch_status="dispatching",
            dispatch_attempts=1,
            dispatch_lease_expires_at=now,
            dispatch_error_code=None,
            promotion_key=None,
            promoted_at=None,
            created_at=now,
            updated_at=now,
        ),
    )


async def test_run_input_dispatch_uses_exact_request_generation_redis_during_reload(
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
        generation=911,
        version=911,
    )
    assert first.accepted is True
    install_process_generation_host_v2(host)

    observed_clients: list[object] = []

    async def send_control(channel: object, _message: object) -> bool:
        observed_clients.append(channel._redis)  # type: ignore[attr-defined]
        second = await host.bootstrap(
            profile_path=_PROFILE_PATH,
            manifest_paths=(_MANIFEST_PATH,),
            generation=912,
            version=912,
        )
        assert second.accepted is True
        assert first_client.close_calls == 0
        return True

    monkeypatch.setattr(run_input_authority.RedisControlChannel, "send_control", send_control)
    static_probe = _StaticContainerRedisProbe(object())
    db = SimpleNamespace(commit=AsyncMock())
    row = _run_input_row()
    user = cast(User, SimpleNamespace(id="user-1"))

    try:
        async with pin_generation_v2(host):
            response = await run_input_authority._dispatch_persisted_steer(
                request=_request_with_static_redis(static_probe),
                db=db,
                row=row,
                current_user=user,
                created=True,
            )
            assert first_client.close_calls == 0

        assert response.accepted is True
        assert observed_clients == [first_client]
        assert static_probe.accesses == 0
        assert first_client.close_calls == 1
        assert second_client.close_calls == 0
    finally:
        clear_process_generation_host_v2(host)
        await host.close()

    assert second_client.close_calls == 1


async def test_run_input_dispatch_returns_structured_rejection_when_v2_redis_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=913,
        version=913,
    )
    assert publication.accepted is True
    install_process_generation_host_v2(host)

    send_control = AsyncMock(return_value=True)
    monkeypatch.setattr(run_input_authority.RedisControlChannel, "send_control", send_control)
    static_probe = _StaticContainerRedisProbe(object())
    db = SimpleNamespace(commit=AsyncMock())
    row = _run_input_row()
    user = cast(User, SimpleNamespace(id="user-1"))

    try:
        async with pin_generation_v2(host):
            response = await run_input_authority._dispatch_persisted_steer(
                request=_request_with_static_redis(static_probe),
                db=db,
                row=row,
                current_user=user,
                created=True,
            )
    finally:
        clear_process_generation_host_v2(host)
        await host.close()

    assert isinstance(response, JSONResponse)
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert json.loads(response.body) == {
        "accepted": False,
        "reason_code": "run_input_dispatch_failed",
        "detail": "Run input delivery failed",
        "run_id": "run-1",
        "run_revision": 7,
        "input_id": "input-1",
        "idempotency_key": "input-key-1",
        "dispatch_status": "failed",
        "retryable": True,
    }
    assert row.dispatch_status == "failed"
    assert row.dispatch_error_code == "control_channel_unavailable"
    assert static_probe.accesses == 0
    send_control.assert_not_awaited()
    db.commit.assert_awaited_once()
