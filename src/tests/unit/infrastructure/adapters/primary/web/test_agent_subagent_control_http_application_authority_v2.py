"""Request authority coverage for generation-owned Agent SubAgent control."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from starlette.requests import Request

from src.domain.model.plugins.generated_v2 import ScopeKindV2
from src.infrastructure.adapters.primary.web.agent_subagent_control_http_application_authority_v2 import (
    agent_subagent_control_http_application_authority_dependency_v2,
)
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.plugins.v2.agent_subagent_control_services import (
    RedisAgentSubAgentControlServiceV2,
)
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    pin_generation_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime import FiberPhaseV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[7]


class _RedisClient:
    async def set(self, *_args: object, **_kwargs: object) -> None:
        return None

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


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "app": FastAPI(),
            "headers": [],
            "method": "POST",
            "path": "/api/v1/agent/subagent/execution-a/cancel",
            "path_params": {},
            "query_string": b"",
            "scheme": "http",
            "server": ("test", 80),
        }
    )


async def test_authority_uses_pinned_root_generation_and_request_identity() -> None:
    redis_client = _RedisClient()
    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(redis_runtime_factory=lambda: redis_client)
    )
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1010,
        version=1010,
    )
    dependency = None
    authority = None
    try:
        async with pin_generation_v2(host):
            dependency = agent_subagent_control_http_application_authority_dependency_v2(
                request=_request(),
                current_user=cast(User, SimpleNamespace(id="user-a")),
            )
            authority = await anext(dependency)

            assert authority.operation.phase is FiberPhaseV2.ACTIVE
            assert authority.operation.descriptor.generation == 1010
            assert authority.operation.context.scope.kind is ScopeKindV2.ROOT
            assert authority.operation.require(OPERATION_IDENTITY_SERVICE_V2) == {
                "user_id": "user-a"
            }
            assert authority.operation.require(OPERATION_METADATA_SERVICE_V2) == {
                "kind": "http-authority",
                "method": "POST",
                "path": "/api/v1/agent/subagent/execution-a/cancel",
            }
            assert isinstance(authority.service, RedisAgentSubAgentControlServiceV2)
            await dependency.aclose()

        assert authority.operation.phase is FiberPhaseV2.DISPOSED
    finally:
        if dependency is not None:
            await dependency.aclose()
        await host.close()


async def test_authority_fails_closed_without_a_pinned_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_generation() -> Any:
        raise RuntimeV2Error("generation_not_pinned", "test")

    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.agent_subagent_control_http_application_authority_v2.current_generation_v2",
        missing_generation,
    )
    dependency = agent_subagent_control_http_application_authority_dependency_v2(
        request=_request(),
        current_user=cast(User, SimpleNamespace(id="user-a")),
    )
    try:
        with pytest.raises(RuntimeV2Error) as error:
            await anext(dependency)
    finally:
        await dependency.aclose()

    assert error.value.code == "generation_not_pinned"
