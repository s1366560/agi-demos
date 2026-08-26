"""Request-lifetime coverage for the Workspace Context V2 authority."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src.domain.model.plugins.generated_v2 import ScopeKindV2
from src.infrastructure.adapters.primary.web.workspace_context_application_authority_v2 import (
    WorkspaceContextApplicationAuthorityV2,
    workspace_context_application_authority_context_v2,
)
from src.infrastructure.adapters.secondary.persistence.models import APIKey
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    pin_generation_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime import FiberPhaseV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[7]
_ROUTER_PATH = _ROOT / "src/infrastructure/adapters/primary/web/routers/workspace_context.py"


def _request(*, method: str = "GET") -> Request:
    return Request(
        {
            "type": "http",
            "app": FastAPI(),
            "headers": [],
            "method": method,
            "path": "/api/v1/workspace-context",
            "path_params": {},
            "query_string": b"",
            "route": SimpleNamespace(path="/api/v1/workspace-context"),
            "scheme": "http",
            "server": ("test", 80),
        }
    )


async def test_authority_pins_root_generation_and_disposes_after_handler() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=113,
        version=113,
    )
    assert publication.accepted is True
    db = AsyncSession()
    api_key = cast(APIKey, SimpleNamespace(id="key-1", user_id="user-1"))
    authority: WorkspaceContextApplicationAuthorityV2 | None = None
    try:
        async with (
            pin_generation_v2(host),
            workspace_context_application_authority_context_v2(
                request=_request(),
                api_key=api_key,
                db=db,
            ) as authority,
        ):
            assert authority.operation.phase is FiberPhaseV2.ACTIVE
            assert authority.operation.descriptor.generation == 113
            assert authority.operation.context.scope.kind is ScopeKindV2.ROOT
            assert authority.db is db
            assert authority.api_key is api_key
            assert authority.operation.require(OPERATION_DB_SESSION_SERVICE_V2) is db
            assert authority.operation.require(OPERATION_IDENTITY_SERVICE_V2) == {
                "user_id": "user-1",
                "api_key_id": "key-1",
            }
            assert authority.operation.require(OPERATION_METADATA_SERVICE_V2) == {
                "kind": "http-authority",
                "method": "GET",
                "path": "/api/v1/workspace-context",
            }
            assert authority.services.context.persistence._session is db

        assert authority.operation.phase is FiberPhaseV2.DISPOSED
    finally:
        await db.close()
        await host.close()


async def test_authority_propagates_generation_failure_without_static_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_generation() -> Any:
        raise RuntimeV2Error("generation_not_pinned", "test")

    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.workspace_context_application_authority_v2.current_generation_v2",
        missing_generation,
    )
    db = AsyncSession()
    api_key = cast(APIKey, SimpleNamespace(id="key-1", user_id="user-1"))
    try:
        with pytest.raises(RuntimeV2Error) as error:
            async with workspace_context_application_authority_context_v2(
                request=_request(),
                api_key=api_key,
                db=db,
            ):
                pass
    finally:
        await db.close()

    assert error.value.code == "generation_not_pinned"


def test_router_has_no_static_repository_or_db_dependency() -> None:
    source = _ROUTER_PATH.read_text(encoding="utf-8")

    assert "SqlDesktopWorkspaceContextRepository" not in source
    assert "verify_api_key_dependency" in source
    assert "get_db" not in source
    assert "AsyncSession" not in source
