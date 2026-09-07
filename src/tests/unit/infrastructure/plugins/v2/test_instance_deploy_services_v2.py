"""V2 Provider/Consumer coverage for instance and deploy services."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.configuration.di_container import DIContainer
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.boundary import OPERATION_DB_SESSION_SERVICE_V2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.instance_deploy_services import (
    INSTANCE_DEPLOY_APPLICATION_MODULE_V2,
    INSTANCE_DEPLOY_APPLICATION_SERVICE_V2,
    INSTANCE_DEPLOY_PROVIDER_MODULE_V2,
    DeployProgressStreamV2,
    InstanceDeployApplicationResolverV2,
)
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


class _RedisCacheClient:
    async def scan_iter(self, *, match: str, count: int) -> AsyncIterator[str | bytes]:
        for key in ():
            yield key

    async def delete(self, *keys: str | bytes) -> int:
        return 0

    async def xadd(self, *_args: object, **_kwargs: object) -> object:
        raise AssertionError("Redis stream publication is outside this authority fixture")


async def test_application_resolver_builds_services_from_the_operation_provider() -> None:
    redis_client = _RedisCacheClient()
    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(sandbox_redis_client=redis_client)
    )
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=47,
        version=47,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="http-instances:tenant-a",
                scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-a"),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            resolver = operation.require(INSTANCE_DEPLOY_APPLICATION_SERVICE_V2)
            assert isinstance(resolver, InstanceDeployApplicationResolverV2)

            services = resolver.resolve(operation)

            assert services.instances._instance_repo._session is db
            assert services.instances._instance_member_repo._session is db
            assert services.instances._deploy_record_repo._session is db
            assert services.deploys._instance_repo._session is db
            assert services.deploys._deploy_record_repo._session is db
            assert services.directory._db is db
            assert services.access._db is db
            assert services.progress._redis_client is redis_client
    finally:
        await db.close()
        await host.close()


def test_provider_and_consumer_are_independent_explicit_profile_entries() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    enabled_modules = tuple(entry.module_ref for entry in document.entries if entry.enabled)

    assert INSTANCE_DEPLOY_PROVIDER_MODULE_V2 in enabled_modules
    assert INSTANCE_DEPLOY_APPLICATION_MODULE_V2 in enabled_modules
    assert enabled_modules.index(INSTANCE_DEPLOY_PROVIDER_MODULE_V2) < enabled_modules.index(
        INSTANCE_DEPLOY_APPLICATION_MODULE_V2
    )


async def test_application_resolver_rejects_a_missing_provider_without_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == INSTANCE_DEPLOY_PROVIDER_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(
        disabled,
        {manifest.plugin_id: manifest},
        generation=48,
    )

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-instance-deploy-services" in str(error.value)


async def test_application_resolver_requires_an_operation_db_session() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=49,
        version=49,
    )
    assert publication.accepted is True
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="http-instances:no-db",
                scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-a"),
            ) as operation,
        ):
            resolver = operation.require(INSTANCE_DEPLOY_APPLICATION_SERVICE_V2)

            with pytest.raises(RuntimeV2Error) as error:
                resolver.resolve(operation)

            assert error.value.code == "missing_service"
    finally:
        await host.close()


def test_static_instance_and_deploy_accessors_are_retired_after_v2_cutover() -> None:
    for accessor in (
        "instance_repository",
        "instance_member_repository",
        "deploy_record_repository",
        "cluster_repository",
        "instance_service",
        "deploy_service",
    ):
        assert not hasattr(DIContainer, accessor)


async def test_terminal_progress_stream_does_not_require_redis() -> None:
    record = SimpleNamespace(
        id="deploy-a",
        status=SimpleNamespace(value="succeeded"),
        is_terminal=lambda: True,
    )
    stream = DeployProgressStreamV2(_redis_client=None).stream(
        record=record,
        is_disconnected=None,
    )

    events = [event async for event in stream]

    assert events == [
        'data: {"type": "status", "status": "succeeded", "deploy_id": "deploy-a"}\n\n',
        'data: {"type": "done", "status": "succeeded"}\n\n',
    ]
