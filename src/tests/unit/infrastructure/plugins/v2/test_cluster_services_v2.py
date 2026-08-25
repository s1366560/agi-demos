"""V2 Provider/Consumer coverage for cluster application services."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.configuration.containers.instance_container import InstanceContainer
from src.configuration.di_container import DIContainer
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.boundary import OPERATION_DB_SESSION_SERVICE_V2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.cluster_services import (
    CLUSTER_APPLICATION_MODULE_V2,
    CLUSTER_APPLICATION_SERVICE_V2,
    CLUSTER_PROVIDER_MODULE_V2,
    ClusterApplicationResolverV2,
    ClusterRunnerPoolServiceV2,
)
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
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
        generation=43,
        version=43,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="http-clusters:tenant-a",
                scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-a"),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            resolver = operation.require(CLUSTER_APPLICATION_SERVICE_V2)
            assert isinstance(resolver, ClusterApplicationResolverV2)

            services = resolver.resolve(operation)

            assert services.clusters._cluster_repo._session is db
            assert services.runner_pools._repository._session is db
    finally:
        await db.close()
        await host.close()


def test_provider_and_consumer_are_independent_explicit_profile_entries() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    enabled_modules = tuple(entry.module_ref for entry in document.entries if entry.enabled)

    assert CLUSTER_PROVIDER_MODULE_V2 in enabled_modules
    assert CLUSTER_APPLICATION_MODULE_V2 in enabled_modules
    assert enabled_modules.index(CLUSTER_PROVIDER_MODULE_V2) < enabled_modules.index(
        CLUSTER_APPLICATION_MODULE_V2
    )


async def test_application_resolver_rejects_a_missing_provider_without_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == CLUSTER_PROVIDER_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(
        disabled,
        {manifest.plugin_id: manifest},
        generation=44,
    )

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-cluster-services" in str(error.value)


async def test_application_resolver_requires_an_operation_db_session() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=45,
        version=45,
    )
    assert publication.accepted is True
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="http-clusters:no-db",
                scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-a"),
            ) as operation,
        ):
            resolver = operation.require(CLUSTER_APPLICATION_SERVICE_V2)

            with pytest.raises(RuntimeV2Error) as error:
                resolver.resolve(operation)

            assert error.value.code == "missing_service"
    finally:
        await host.close()


def test_static_cluster_service_accessors_are_retired_after_v2_cutover() -> None:
    assert not hasattr(InstanceContainer, "cluster_service")
    assert not hasattr(DIContainer, "cluster_repository")
    assert not hasattr(DIContainer, "cluster_service")


async def test_runner_pool_service_keeps_tenant_scoping_behind_the_service_seam() -> None:
    repository = SimpleNamespace(
        list_pools_by_cluster=AsyncMock(return_value=["pool-a"]),
        list_instances_by_tenant=AsyncMock(return_value=["runner-a"]),
    )
    service = ClusterRunnerPoolServiceV2(_repository=cast(Any, repository))

    result = await service.list_for_cluster(tenant_id="tenant-a", cluster_id="cluster-a")

    assert result == (["pool-a"], ["runner-a"])
    repository.list_pools_by_cluster.assert_awaited_once_with(
        tenant_id="tenant-a",
        cluster_id="cluster-a",
    )
    repository.list_instances_by_tenant.assert_awaited_once_with("tenant-a")
