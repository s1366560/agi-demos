"""V2 Provider/Consumer coverage for lightweight AI-tool operations."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.ai_tool_services import (
    AI_TOOL_APPLICATION_MODULE_V2,
    AI_TOOL_APPLICATION_SERVICE_V2,
    AI_TOOL_TENANT_PROVIDER_MODULE_V2,
    AiToolApplicationResolverV2,
    AiToolApplicationServicesV2,
    AiToolClientUnavailableV2,
    SqlAiToolTenantPersistenceV2,
)
from src.infrastructure.plugins.v2.boundary import OPERATION_DB_SESSION_SERVICE_V2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


async def test_ai_tool_resolver_builds_persistence_from_operation_session() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=91,
        version=91,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="ai-tools:tenant-a",
                scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-a"),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            resolver = operation.require(AI_TOOL_APPLICATION_SERVICE_V2)

            assert isinstance(resolver, AiToolApplicationResolverV2)
            services = resolver.resolve(operation)
            assert getattr(services.persistence, "_session", None) is db
    finally:
        await db.close()
        await host.close()


def test_ai_tool_modules_are_explicit_ordered_profile_entries() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    enabled_modules = tuple(entry.module_ref for entry in document.entries if entry.enabled)

    assert AI_TOOL_TENANT_PROVIDER_MODULE_V2 in enabled_modules
    assert AI_TOOL_APPLICATION_MODULE_V2 in enabled_modules
    assert enabled_modules.index(AI_TOOL_TENANT_PROVIDER_MODULE_V2) < enabled_modules.index(
        AI_TOOL_APPLICATION_MODULE_V2
    )
    application_entry = next(
        entry for entry in document.entries if entry.module_ref == AI_TOOL_APPLICATION_MODULE_V2
    )
    assert application_entry.inject == {"provider": "service:persistence.ai-tool-tenant-provider"}


async def test_ai_tool_application_rejects_missing_provider_without_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == AI_TOOL_TENANT_PROVIDER_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(disabled, {manifest.plugin_id: manifest}, generation=92)

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-ai-tool-services" in str(error.value)


async def test_ai_tool_resolver_rejects_non_session_operation_service() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=93,
        version=93,
    )
    assert publication.accepted is True
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="ai-tools:invalid-db",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, object())
            resolver = operation.require(AI_TOOL_APPLICATION_SERVICE_V2)
            assert isinstance(resolver, AiToolApplicationResolverV2)

            with pytest.raises(RuntimeV2Error) as error:
                _ = resolver.resolve(operation)

            assert error.value.code == "invalid_operation_db_session"
    finally:
        await host.close()


async def test_ai_tool_application_resolves_tenant_then_client() -> None:
    client = SimpleNamespace(generate=AsyncMock())
    persistence = SimpleNamespace(resolve_tenant_id=AsyncMock(return_value="tenant-a"))
    client_factory = AsyncMock(return_value=client)
    services = AiToolApplicationServicesV2(
        persistence=persistence,
        client_factory=client_factory,
    )

    resolved = await services.resolve_client(user_id="user-a", tenant_id=None)

    assert resolved is client
    persistence.resolve_tenant_id.assert_awaited_once_with(
        user_id="user-a",
        declared_tenant_id=None,
    )
    client_factory.assert_awaited_once_with("tenant-a")


async def test_ai_tool_application_fails_closed_when_client_is_unavailable() -> None:
    services = AiToolApplicationServicesV2(
        persistence=SimpleNamespace(resolve_tenant_id=AsyncMock(return_value=None)),
        client_factory=AsyncMock(return_value=None),
    )

    with pytest.raises(AiToolClientUnavailableV2):
        await services.resolve_client(user_id="user-a", tenant_id=None)


async def test_sql_ai_tool_tenant_provider_prefers_declared_tenant(test_db) -> None:
    persistence = SqlAiToolTenantPersistenceV2(_session=test_db)

    tenant_id = await persistence.resolve_tenant_id(
        user_id="user-a",
        declared_tenant_id=" tenant-a ",
    )

    assert tenant_id == "tenant-a"
