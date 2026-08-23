"""V2-only persistence and adapter seams for MCP HTTP operations."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import MCPSandboxAdapter
from src.infrastructure.plugins.v2.boundary import OPERATION_DB_SESSION_SERVICE_V2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.mcp_services import (
    MCP_APPLICATION_SERVICE_V2,
    MCPApplicationResolverV2,
    MCPProjectAccessDeniedV2,
    SqlMCPLifecycleQueryV2,
    SqlMCPProjectAccessV2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]


class _SandboxAdapter(MCPSandboxAdapter):
    async def sync_from_docker(self) -> int:
        return 0

    async def close(self) -> None:
        return None


async def test_mcp_resolver_exposes_only_operation_owned_domain_dependencies() -> None:
    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(sandbox_runtime_factory=_SandboxAdapter)
    )
    publication = await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=111,
        version=111,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="mcp-domain-services",
                scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-a"),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            resolver = operation.require(MCP_APPLICATION_SERVICE_V2)

            assert isinstance(resolver, MCPApplicationResolverV2)
            services = resolver.resolve(operation)
            assert getattr(services.server_repository, "_session", None) is db
            assert getattr(services.access, "_session", None) is db
            assert getattr(services.lifecycle_queries, "_session", None) is db
            assert services.direct_tool_caller is not None
            assert services.tool_cache is not None
    finally:
        await db.close()
        await host.close()


async def test_mcp_project_access_fails_closed_for_missing_membership() -> None:
    result = Mock(scalar_one_or_none=Mock(return_value=None))
    db = AsyncMock(execute=AsyncMock(return_value=result))
    access = SqlMCPProjectAccessV2(_session=cast(AsyncSession, db))

    with pytest.raises(MCPProjectAccessDeniedV2):
        await access.resolve_project_tenant_id(
            project_id="project-a",
            tenant_id="tenant-a",
            user_id="user-a",
        )


async def test_mcp_lifecycle_queries_are_scoped_and_newest_first() -> None:
    created_at = datetime(2026, 8, 23, tzinfo=UTC)
    scalars = Mock(
        all=Mock(
            return_value=[
                SimpleNamespace(
                    id="event-a",
                    event_type="sync",
                    status="success",
                    error_message=None,
                    metadata_json={"tool_count": 2},
                    created_at=created_at,
                )
            ]
        )
    )
    result = Mock(scalars=Mock(return_value=scalars))
    db = AsyncMock(execute=AsyncMock(return_value=result))
    queries = SqlMCPLifecycleQueryV2(_session=cast(AsyncSession, db))

    events = await queries.list_server_events(
        server_id="server-a",
        tenant_id="tenant-a",
        limit=25,
    )

    assert [event.id for event in events] == ["event-a"]
    assert events[0].metadata == {"tool_count": 2}
    assert events[0].created_at == created_at
    statement = str(db.execute.await_args.args[0])
    assert "mcp_lifecycle_events.server_id" in statement
    assert "mcp_lifecycle_events.tenant_id" in statement
    assert "ORDER BY mcp_lifecycle_events.created_at DESC" in statement
    assert "LIMIT" in statement
