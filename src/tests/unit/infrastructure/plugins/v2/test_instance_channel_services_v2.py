"""V2 Provider/Consumer coverage for instance-channel application services."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.configuration.containers.instance_container import InstanceContainer
from src.configuration.di_container import DIContainer
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.boundary import OPERATION_DB_SESSION_SERVICE_V2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.instance_channel_services import (
    INSTANCE_CHANNEL_APPLICATION_MODULE_V2,
    INSTANCE_CHANNEL_APPLICATION_SERVICE_V2,
    INSTANCE_CHANNEL_PROVIDER_MODULE_V2,
    InstanceChannelAccessServiceV2,
    InstanceChannelApplicationResolverV2,
)
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


async def test_application_resolver_builds_services_from_the_operation_provider() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=35,
        version=35,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="http-instance-channels:user-a",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            resolver = operation.require(INSTANCE_CHANNEL_APPLICATION_SERVICE_V2)
            assert isinstance(resolver, InstanceChannelApplicationResolverV2)

            services = resolver.resolve(operation)

            assert services.channels._channel_repo._session is db
            assert services.access.instance_repository.session is db
    finally:
        await db.close()
        await host.close()


def test_provider_and_consumer_are_independent_explicit_profile_entries() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    enabled_modules = tuple(entry.module_ref for entry in document.entries if entry.enabled)

    assert INSTANCE_CHANNEL_PROVIDER_MODULE_V2 in enabled_modules
    assert INSTANCE_CHANNEL_APPLICATION_MODULE_V2 in enabled_modules
    assert enabled_modules.index(INSTANCE_CHANNEL_PROVIDER_MODULE_V2) < enabled_modules.index(
        INSTANCE_CHANNEL_APPLICATION_MODULE_V2
    )


async def test_application_resolver_rejects_a_missing_provider_without_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == INSTANCE_CHANNEL_PROVIDER_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(
        disabled,
        {manifest.plugin_id: manifest},
        generation=36,
    )

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-instance-channel-services" in str(error.value)


async def test_application_resolver_requires_an_operation_db_session() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=37,
        version=37,
    )
    assert publication.accepted is True
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="http-instance-channels:no-db",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as operation,
        ):
            resolver = operation.require(INSTANCE_CHANNEL_APPLICATION_SERVICE_V2)

            with pytest.raises(RuntimeV2Error) as error:
                resolver.resolve(operation)

            assert error.value.code == "missing_service"
    finally:
        await host.close()


async def test_access_service_hides_missing_instances_and_returns_declared_tenant() -> None:
    repository = SimpleNamespace(
        find_by_id=AsyncMock(side_effect=[None, SimpleNamespace(tenant_id="tenant-a")])
    )
    access = InstanceChannelAccessServiceV2(instance_repository=repository)

    assert await access.tenant_id_for_instance("missing") is None
    assert await access.tenant_id_for_instance("instance-a") == "tenant-a"


def test_static_instance_channel_accessors_are_retired_after_v2_cutover() -> None:
    assert not hasattr(InstanceContainer, "instance_channel_repository")
    assert not hasattr(InstanceContainer, "instance_channel_service")
    assert not hasattr(DIContainer, "instance_channel_service")
