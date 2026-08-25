"""V2 Provider/Consumer coverage for tenant agent configuration services."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.configuration.containers.agent_container import AgentContainer
from src.configuration.di_container import DIContainer
from src.domain.model.agent.tenant_agent_config import TenantAgentConfig
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.artifact_content_gc_runtime import (
    ASYNC_SESSION_FACTORY_MODULE_V2,
    ASYNC_SESSION_FACTORY_SERVICE_V2,
)
from src.infrastructure.plugins.v2.boundary import OPERATION_DB_SESSION_SERVICE_V2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.tenant_agent_config_services import (
    TENANT_AGENT_CONFIG_APPLICATION_MODULE_V2,
    TENANT_AGENT_CONFIG_APPLICATION_SERVICE_V2,
    TENANT_AGENT_CONFIG_PROVIDER_MODULE_V2,
    SqlTenantAgentConfigServiceFactoryV2,
    TenantAgentConfigApplicationResolverV2,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


async def test_application_resolver_builds_repositories_from_operation_db() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=71,
        version=71,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="http-tenant-agent-config:tenant-a",
                scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-a"),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            resolver = operation.require(TENANT_AGENT_CONFIG_APPLICATION_SERVICE_V2)
            assert isinstance(resolver, TenantAgentConfigApplicationResolverV2)

            services = resolver.resolve(operation)

            assert services.configs._session is db
            assert services.authority._session is db
    finally:
        await db.close()
        await host.close()


async def test_generation_provider_loads_custom_config_and_closes_its_session() -> None:
    db = AsyncSession()
    entered = False
    closed = False

    @asynccontextmanager
    async def session_context() -> Any:
        nonlocal entered, closed
        entered = True
        try:
            yield db
        finally:
            closed = True

    expected = TenantAgentConfig.create_default("tenant-a").update_llm_settings(
        model="openai/gpt-5.4"
    )
    repo = MagicMock()
    repo.get_by_tenant = AsyncMock(return_value=expected)
    sessions = cast(Any, SimpleNamespace(factory=session_context))
    provider = SqlTenantAgentConfigServiceFactoryV2(sessions=sessions)

    with patch(
        "src.infrastructure.plugins.v2.tenant_agent_config_services.SqlTenantAgentConfigRepository",
        return_value=repo,
    ):
        result = await provider.load("tenant-a")

    assert result is expected
    assert entered is True
    assert closed is True
    repo.get_by_tenant.assert_awaited_once_with("tenant-a")
    await db.close()


async def test_generation_provider_defaults_only_when_config_is_absent() -> None:
    db = AsyncSession()

    @asynccontextmanager
    async def session_context() -> Any:
        yield db

    repo = MagicMock()
    repo.get_by_tenant = AsyncMock(return_value=None)
    provider = SqlTenantAgentConfigServiceFactoryV2(
        sessions=cast(Any, SimpleNamespace(factory=session_context))
    )

    with patch(
        "src.infrastructure.plugins.v2.tenant_agent_config_services.SqlTenantAgentConfigRepository",
        return_value=repo,
    ):
        result = await provider.load("tenant-a")

    assert result.tenant_id == "tenant-a"
    assert result.config_type.value == "default"
    assert result.llm_model == "default"
    await db.close()


async def test_generation_provider_propagates_database_failure_without_default_fallback() -> None:
    db = AsyncSession()

    @asynccontextmanager
    async def session_context() -> Any:
        yield db

    repo = MagicMock()
    repo.get_by_tenant = AsyncMock(side_effect=RuntimeError("database unavailable"))
    provider = SqlTenantAgentConfigServiceFactoryV2(
        sessions=cast(Any, SimpleNamespace(factory=session_context))
    )

    with (
        patch(
            "src.infrastructure.plugins.v2.tenant_agent_config_services."
            "SqlTenantAgentConfigRepository",
            return_value=repo,
        ),
        pytest.raises(RuntimeV2Error) as error,
    ):
        await provider.load("tenant-a")

    assert error.value.code == "tenant_agent_config_load_failed"
    await db.close()


def test_provider_and_consumer_are_explicit_ordered_profile_entries() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    enabled_entries = tuple(entry for entry in document.entries if entry.enabled)
    enabled_modules = tuple(entry.module_ref for entry in enabled_entries)

    sessions_index = enabled_modules.index(ASYNC_SESSION_FACTORY_MODULE_V2)
    provider_index = enabled_modules.index(TENANT_AGENT_CONFIG_PROVIDER_MODULE_V2)
    application_index = enabled_modules.index(TENANT_AGENT_CONFIG_APPLICATION_MODULE_V2)

    assert sessions_index < provider_index < application_index
    provider_entry = enabled_entries[provider_index]
    assert provider_entry.inject == {"sessions": ASYNC_SESSION_FACTORY_SERVICE_V2}


async def test_application_resolver_rejects_missing_provider_without_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == TENANT_AGENT_CONFIG_PROVIDER_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(
        disabled,
        {manifest.plugin_id: manifest},
        generation=72,
    )

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-tenant-agent-config-services" in str(error.value)


async def test_application_resolver_requires_operation_db_session() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=73,
        version=73,
    )
    assert publication.accepted is True
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="http-tenant-agent-config:no-db",
                scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-a"),
            ) as operation,
        ):
            resolver = operation.require(TENANT_AGENT_CONFIG_APPLICATION_SERVICE_V2)

            with pytest.raises(RuntimeV2Error) as error:
                resolver.resolve(operation)

            assert error.value.code == "missing_service"
    finally:
        await host.close()


def test_static_tenant_agent_config_accessors_are_retired_after_v2_cutover() -> None:
    assert not hasattr(AgentContainer, "tenant_agent_config_repository")
    assert not hasattr(DIContainer, "tenant_agent_config_repository")
