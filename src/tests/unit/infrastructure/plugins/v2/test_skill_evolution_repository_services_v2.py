"""Generation-owned SkillEvolution repository Provider coverage."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.boundary import OPERATION_DB_SESSION_SERVICE_V2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.skill_evolution_repository_services import (
    SKILL_EVOLUTION_REPOSITORY_APPLICATION_MODULE_V2,
    SKILL_EVOLUTION_REPOSITORY_APPLICATION_SERVICE_V2,
    SKILL_EVOLUTION_REPOSITORY_PROVIDER_INJECT_V2,
    SKILL_EVOLUTION_REPOSITORY_PROVIDER_MODULE_V2,
    SKILL_EVOLUTION_REPOSITORY_PROVIDER_SERVICE_V2,
    SkillEvolutionRepositoryApplicationResolverProtocolV2,
    SkillEvolutionRepositoryProtocolV2,
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
        generation=1024,
        version=1024,
    )
    assert publication.accepted is True, publication.receipt
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="http-skill-evolution-repository",
                scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-a"),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            resolver = operation.require(SKILL_EVOLUTION_REPOSITORY_APPLICATION_SERVICE_V2)

            assert isinstance(
                resolver,
                SkillEvolutionRepositoryApplicationResolverProtocolV2,
            )
            repository = resolver.resolve(operation).repository
            assert isinstance(repository, SkillEvolutionRepositoryProtocolV2)
            assert repository._session is db
    finally:
        await db.close()
        await host.close()


def test_default_profile_declares_explicit_repository_alias() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    entries = {entry.module_ref: entry for entry in document.entries}
    ordered_modules = tuple(entry.module_ref for entry in document.entries)

    provider = entries[SKILL_EVOLUTION_REPOSITORY_PROVIDER_MODULE_V2]
    assert provider.config == {"strategy": "request-async-session"}
    assert provider.inject == {}
    assert provider.scope == ScopeV2(kind=ScopeKindV2.ROOT)
    application = entries[SKILL_EVOLUTION_REPOSITORY_APPLICATION_MODULE_V2]
    assert application.config == {"strategy": "operation-scoped-provider"}
    assert application.inject == {
        SKILL_EVOLUTION_REPOSITORY_PROVIDER_INJECT_V2: (
            SKILL_EVOLUTION_REPOSITORY_PROVIDER_SERVICE_V2
        )
    }
    assert ordered_modules.index(
        SKILL_EVOLUTION_REPOSITORY_PROVIDER_MODULE_V2
    ) < ordered_modules.index(SKILL_EVOLUTION_REPOSITORY_APPLICATION_MODULE_V2)


async def test_provider_fails_closed_without_async_session() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=1025,
        version=1025,
    )
    assert publication.accepted is True, publication.receipt
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="invalid-skill-evolution-repository",
                scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-a"),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, object())
            resolver = operation.require(SKILL_EVOLUTION_REPOSITORY_APPLICATION_SERVICE_V2)

            with pytest.raises(RuntimeV2Error) as error:
                resolver.resolve(operation)

        assert error.value.code == "invalid_operation_db_session"
    finally:
        await host.close()


def test_repository_protocol_requires_status_mutation_authority() -> None:
    read_only_repository = SimpleNamespace(
        get_job=AsyncMock(),
        list_jobs=AsyncMock(),
        count_sessions_by_skill=AsyncMock(),
        get_overview_stats=AsyncMock(),
        get_skill_session_summaries=AsyncMock(),
        list_recent_sessions=AsyncMock(),
    )

    assert not isinstance(read_only_repository, SkillEvolutionRepositoryProtocolV2)


async def test_missing_provider_is_rejected_before_application_loading() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == SKILL_EVOLUTION_REPOSITORY_PROVIDER_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(
        disabled,
        {manifest.plugin_id: manifest},
        generation=1026,
    )

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-skill-evolution-repository-application" in str(error.value)
