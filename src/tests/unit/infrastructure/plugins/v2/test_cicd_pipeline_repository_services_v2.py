"""Generation-owned CI/CD pipeline repository Provider coverage."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.sql_cicd_pipeline import (
    SqlCicdPipelineRepository,
)
from src.infrastructure.plugins.v2.boundary import OPERATION_DB_SESSION_SERVICE_V2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.cicd_pipeline_repository_services import (
    CICD_PIPELINE_REPOSITORY_PROVIDER_MODULE_V2,
    CICD_PIPELINE_REPOSITORY_PROVIDER_SERVICE_V2,
    CicdPipelineRepositoryProviderProtocolV2,
)
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"
_DRONE_PIPELINE_REPOSITORY_INJECT_V2 = "pipeline_repository"
_DRONE_TOOL_MODULE_V2 = "builtin://memstack/agent/tool/drone"


async def test_provider_builds_repository_from_exact_operation_session() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=1025,
        version=1025,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="cicd-pipeline-repository",
                scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-a"),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            provider = operation.require(CICD_PIPELINE_REPOSITORY_PROVIDER_SERVICE_V2)

            assert isinstance(provider, CicdPipelineRepositoryProviderProtocolV2)
            repository = provider.build(operation)
            assert isinstance(repository, SqlCicdPipelineRepository)
            assert repository._db is db
    finally:
        await db.close()
        await host.close()


def test_default_profile_declares_provider_before_drone_consumer() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    entries = {entry.module_ref: entry for entry in document.entries}
    ordered_modules = tuple(entry.module_ref for entry in document.entries)

    provider = entries[CICD_PIPELINE_REPOSITORY_PROVIDER_MODULE_V2]
    assert provider.config == {"strategy": "request-async-session"}
    assert provider.inject == {}
    assert provider.scope == ScopeV2(kind=ScopeKindV2.ROOT)

    drone = entries[_DRONE_TOOL_MODULE_V2]
    assert drone.inject[_DRONE_PIPELINE_REPOSITORY_INJECT_V2] == (
        CICD_PIPELINE_REPOSITORY_PROVIDER_SERVICE_V2
    )
    assert ordered_modules.index(CICD_PIPELINE_REPOSITORY_PROVIDER_MODULE_V2) < (
        ordered_modules.index(_DRONE_TOOL_MODULE_V2)
    )


async def test_provider_fails_closed_without_async_session() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=1026,
        version=1026,
    )
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="invalid-cicd-pipeline-repository",
                scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-a"),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, object())
            provider = operation.require(CICD_PIPELINE_REPOSITORY_PROVIDER_SERVICE_V2)

            with pytest.raises(RuntimeV2Error) as error:
                provider.build(operation)

        assert error.value.code == "invalid_operation_db_session"
    finally:
        await host.close()


async def test_missing_provider_is_rejected_before_drone_loading() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == CICD_PIPELINE_REPOSITORY_PROVIDER_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(disabled, {manifest.plugin_id: manifest}, generation=1027)

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-drone-tool" in str(error.value)
