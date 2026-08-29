"""Request authority coverage for generation-owned Agent message history."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src.domain.model.plugins.generated_v2 import ScopeKindV2
from src.infrastructure.adapters.primary.web.agent_message_history_http_application_authority_v2 import (
    agent_message_history_http_application_authority_dependency_v2,
)
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.plugins.v2.agent_message_history_services import (
    AgentMessageHistoryServiceV2,
)
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    pin_generation_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime import FiberPhaseV2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[7]


class _RedisClient:
    async def aclose(self) -> None:
        return None

    async def scan_iter(self, *, match: str, count: int) -> AsyncIterator[str]:
        if False:
            yield match, str(count)

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
            "method": "GET",
            "path": "/api/v1/agent/conversations/conversation-a/messages",
            "path_params": {"conversation_id": "conversation-a"},
            "query_string": b"project_id=project-a",
            "scheme": "http",
            "server": ("test", 80),
        }
    )


async def test_authority_uses_pinned_project_generation_and_exact_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def allow_access(self: AgentMessageHistoryServiceV2, **_kwargs: str) -> object:
        return SimpleNamespace(id="conversation-a")

    monkeypatch.setattr(
        AgentMessageHistoryServiceV2,
        "require_conversation_access",
        allow_access,
    )
    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(redis_runtime_factory=_RedisClient)
    )
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1011,
        version=1011,
    )
    dependency = None
    authority = None
    db = cast(AsyncSession, AsyncMock(spec=AsyncSession))
    try:
        async with pin_generation_v2(host):
            dependency = agent_message_history_http_application_authority_dependency_v2(
                request=_request(),
                conversation_id="conversation-a",
                project_id="project-a",
                current_user=cast(User, SimpleNamespace(id="user-a")),
                tenant_id="tenant-a",
                db=db,
            )
            authority = await anext(dependency)

            assert authority.operation.phase is FiberPhaseV2.ACTIVE
            assert authority.operation.descriptor.generation == 1011
            assert authority.operation.context.scope.kind is ScopeKindV2.PROJECT
            assert authority.operation.require(OPERATION_IDENTITY_SERVICE_V2) == {
                "tenant_id": "tenant-a",
                "project_id": "project-a",
                "user_id": "user-a",
            }
            assert authority.operation.require(OPERATION_METADATA_SERVICE_V2) == {
                "kind": "http-authority",
                "method": "GET",
                "path": "/api/v1/agent/conversations/conversation-a/messages",
            }
            assert isinstance(authority.service, AgentMessageHistoryServiceV2)
            await dependency.aclose()

        assert authority.operation.phase is FiberPhaseV2.DISPOSED
    finally:
        if dependency is not None:
            await dependency.aclose()
        await host.close()
