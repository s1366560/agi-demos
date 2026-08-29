"""Generation-owned Skill repository Provider coverage."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.ports.repositories.skill_repository import SkillRepositoryPort
from src.domain.ports.repositories.skill_version_repository import SkillVersionRepositoryPort
from src.infrastructure.plugins.v2.boundary import OPERATION_DB_SESSION_SERVICE_V2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.skill_repository_services import (
    SKILL_REPOSITORY_APPLICATION_MODULE_V2,
    SKILL_REPOSITORY_APPLICATION_SERVICE_V2,
    SKILL_REPOSITORY_PROVIDER_INJECT_V2,
    SKILL_REPOSITORY_PROVIDER_MODULE_V2,
    SKILL_REPOSITORY_PROVIDER_SERVICE_V2,
    SKILL_VERSION_REPOSITORY_PROVIDER_INJECT_V2,
    SKILL_VERSION_REPOSITORY_PROVIDER_MODULE_V2,
    SKILL_VERSION_REPOSITORY_PROVIDER_SERVICE_V2,
    SkillRepositoryApplicationResolverProtocolV2,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


async def test_provider_builds_repository_from_exact_operation_session() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=1009,
        version=1009,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="http-skill-repository",
                scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-a"),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            resolver = operation.require(SKILL_REPOSITORY_APPLICATION_SERVICE_V2)

            assert isinstance(resolver, SkillRepositoryApplicationResolverProtocolV2)
            services = resolver.resolve(operation)
            assert isinstance(services.repository, SkillRepositoryPort)
            assert isinstance(services.version_repository, SkillVersionRepositoryPort)
            assert services.repository._session is db
            assert services.version_repository._session is db
    finally:
        await db.close()
        await host.close()


def test_default_profile_declares_explicit_repository_alias() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    entries = {entry.module_ref: entry for entry in document.entries}
    ordered_modules = tuple(entry.module_ref for entry in document.entries)

    provider = entries[SKILL_REPOSITORY_PROVIDER_MODULE_V2]
    assert provider.config == {"strategy": "request-async-session"}
    assert provider.inject == {}
    assert provider.scope == ScopeV2(kind=ScopeKindV2.ROOT)
    version_provider = entries[SKILL_VERSION_REPOSITORY_PROVIDER_MODULE_V2]
    assert version_provider.config == {"strategy": "request-async-session"}
    assert version_provider.inject == {}
    assert version_provider.scope == ScopeV2(kind=ScopeKindV2.ROOT)
    application = entries[SKILL_REPOSITORY_APPLICATION_MODULE_V2]
    assert application.config == {"strategy": "operation-scoped-provider"}
    assert application.inject == {
        SKILL_REPOSITORY_PROVIDER_INJECT_V2: SKILL_REPOSITORY_PROVIDER_SERVICE_V2,
        SKILL_VERSION_REPOSITORY_PROVIDER_INJECT_V2: (SKILL_VERSION_REPOSITORY_PROVIDER_SERVICE_V2),
    }
    assert ordered_modules.index(SKILL_REPOSITORY_PROVIDER_MODULE_V2) < ordered_modules.index(
        SKILL_REPOSITORY_APPLICATION_MODULE_V2
    )
    assert ordered_modules.index(
        SKILL_VERSION_REPOSITORY_PROVIDER_MODULE_V2
    ) < ordered_modules.index(SKILL_REPOSITORY_APPLICATION_MODULE_V2)


async def test_provider_fails_closed_without_async_session() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=1010,
        version=1010,
    )
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="invalid-skill-repository",
                scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-a"),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, object())
            resolver = operation.require(SKILL_REPOSITORY_APPLICATION_SERVICE_V2)

            with pytest.raises(RuntimeV2Error) as error:
                resolver.resolve(operation)

        assert error.value.code == "invalid_operation_db_session"
    finally:
        await host.close()


@pytest.mark.parametrize(
    "missing_module",
    (SKILL_REPOSITORY_PROVIDER_MODULE_V2, SKILL_VERSION_REPOSITORY_PROVIDER_MODULE_V2),
)
async def test_missing_provider_is_rejected_before_application_loading(
    missing_module: str,
) -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False) if entry.module_ref == missing_module else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(
        disabled,
        {manifest.plugin_id: manifest},
        generation=1012,
    )

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-skill-repository-application" in str(error.value)


async def test_wrong_version_provider_alias_is_rejected_before_application_loading() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    broken = replace(
        document,
        entries=tuple(
            replace(
                entry,
                inject={
                    **entry.inject,
                    SKILL_VERSION_REPOSITORY_PROVIDER_INJECT_V2: (
                        SKILL_REPOSITORY_PROVIDER_SERVICE_V2
                    ),
                },
            )
            if entry.module_ref == SKILL_REPOSITORY_APPLICATION_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(
        broken,
        {manifest.plugin_id: manifest},
        generation=1013,
    )

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "inject_service_mismatch"
    assert "builtin-skill-repository-application" in str(error.value)
