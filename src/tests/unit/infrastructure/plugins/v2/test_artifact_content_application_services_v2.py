"""V2 application seam for Artifact content authority and reconciliation."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.artifact_content_authority_service import (
    ArtifactContentSaveOutcome,
)
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.ports.repositories.artifact_content_authority_repository import (
    ArtifactContentAuthorityRepositoryPort,
)
from src.domain.ports.services.storage_service_port import StorageServicePort
from src.infrastructure.plugins.v2.artifact_content_gc_runtime import (
    ASYNC_SESSION_FACTORY_MODULE_V2,
    ASYNC_SESSION_FACTORY_SERVICE_V2,
    OBJECT_STORAGE_PROVIDER_MODULE_V2,
    OBJECT_STORAGE_SERVICE_V2,
    AsyncSessionFactoryServiceV2,
    ObjectStorageServiceV2,
)
from src.infrastructure.plugins.v2.artifact_content_persistence import (
    ARTIFACT_CONTENT_PROVIDER_MODULE_V2,
    ARTIFACT_CONTENT_PROVIDER_SERVICE_V2,
    ARTIFACT_CONTENT_PROVIDER_SESSIONS_INJECT_V2,
    ArtifactContentPersistenceServicesV2,
    SqlArtifactContentPersistenceFactoryV2,
)
from src.infrastructure.plugins.v2.artifact_content_services import (
    ARTIFACT_CONTENT_APPLICATION_MODULE_V2,
    ARTIFACT_CONTENT_APPLICATION_SERVICE_V2,
    ARTIFACT_CONTENT_PROVIDER_INJECT_V2,
    ARTIFACT_CONTENT_STORAGE_INJECT_V2,
    ArtifactContentApplicationResolverV2,
)
from src.infrastructure.plugins.v2.boundary import OPERATION_DB_SESSION_SERVICE_V2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import (
    ContextV2,
    LoaderV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
)
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"
_CONSUMER_PATH = _ROOT / "src/infrastructure/plugins/v2/artifact_content_services.py"


async def test_resolver_binds_content_services_to_the_operation_session() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=157,
        version=157,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="http-artifact-content-application",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            resolver = operation.require(ARTIFACT_CONTENT_APPLICATION_SERVICE_V2)
            storage = generation.resolve(
                OBJECT_STORAGE_SERVICE_V2,
                ScopeV2(kind=ScopeKindV2.ROOT),
            )
            sessions = generation.resolve(
                ASYNC_SESSION_FACTORY_SERVICE_V2,
                ScopeV2(kind=ScopeKindV2.ROOT),
            )
            provider = generation.resolve(
                ARTIFACT_CONTENT_PROVIDER_SERVICE_V2,
                ScopeV2(kind=ScopeKindV2.ROOT),
            )

            assert isinstance(resolver, ArtifactContentApplicationResolverV2)
            assert isinstance(storage, ObjectStorageServiceV2)
            assert isinstance(sessions, AsyncSessionFactoryServiceV2)
            assert isinstance(provider, SqlArtifactContentPersistenceFactoryV2)
            assert resolver.provider is provider
            services = resolver.resolve(operation)
            assert services.content._repository._session is db
            assert services.content._storage is storage.storage_service
            assert services.reconciler._session_factory is sessions.factory
            assert services.reconciler._storage is storage.storage_service
            assert services.content._orphan_recorder.__self__ is services.reconciler
    finally:
        await db.close()
        await host.close()


async def test_resolver_accepts_a_profile_selected_fake_provider() -> None:
    repository = object()
    storage_service = object()

    class _FakeReconciler:
        async def reconcile(self, _outcome: ArtifactContentSaveOutcome) -> None:
            return None

        async def record_pending(
            self,
            _outcome: ArtifactContentSaveOutcome,
            *,
            reason_code: str,
            last_error_code: str,
            next_attempt_at: datetime | None = None,
        ) -> None:
            _ = (reason_code, last_error_code, next_attempt_at)

    reconciler = _FakeReconciler()

    class _FakeProvider:
        def __init__(self) -> None:
            self.calls: list[tuple[OperationContextV2, object]] = []

        def build(
            self,
            operation: OperationContextV2,
            *,
            storage: StorageServicePort,
        ) -> ArtifactContentPersistenceServicesV2:
            self.calls.append((operation, storage))
            return ArtifactContentPersistenceServicesV2(
                repository=cast(ArtifactContentAuthorityRepositoryPort, repository),
                reconciler=reconciler,
            )

    provider = _FakeProvider()
    resolver = ArtifactContentApplicationResolverV2(
        provider=provider,
        storage=ObjectStorageServiceV2(
            storage_service=cast(StorageServicePort, storage_service),
            strategy="fake",
        ),
    )
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=158,
        version=158,
    )
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="fake-artifact-content-provider",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as operation,
        ):
            services = resolver.resolve(operation)

            assert services.content._repository is repository
            assert services.content._storage is storage_service
            assert services.reconciler is reconciler
            assert provider.calls == [(operation, storage_service)]
    finally:
        await host.close()


async def test_sql_provider_isolates_repositories_by_operation_session() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=159,
        version=159,
    )
    first_db = AsyncSession()
    second_db = AsyncSession()
    try:
        async with await host.acquire() as generation:
            provider = generation.resolve(
                ARTIFACT_CONTENT_PROVIDER_SERVICE_V2,
                ScopeV2(kind=ScopeKindV2.ROOT),
            )
            storage = generation.resolve(
                OBJECT_STORAGE_SERVICE_V2,
                ScopeV2(kind=ScopeKindV2.ROOT),
            )
            assert isinstance(provider, SqlArtifactContentPersistenceFactoryV2)
            assert isinstance(storage, ObjectStorageServiceV2)

            async with OperationContextV2(
                generation=generation,
                operation_id="artifact-content-operation-first",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as first_operation:
                _ = first_operation.provide(OPERATION_DB_SESSION_SERVICE_V2, first_db)
                first = provider.build(
                    first_operation,
                    storage=storage.storage_service,
                )

            async with OperationContextV2(
                generation=generation,
                operation_id="artifact-content-operation-second",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as second_operation:
                _ = second_operation.provide(OPERATION_DB_SESSION_SERVICE_V2, second_db)
                second = provider.build(
                    second_operation,
                    storage=storage.storage_service,
                )

            assert first.repository._session is first_db
            assert second.repository._session is second_db
            assert first.repository is not second.repository
    finally:
        await first_db.close()
        await second_db.close()
        await host.close()


def test_artifact_content_profile_declares_provider_and_consumer_aliases() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    entries = {entry.module_ref: entry for entry in document.entries}
    ordered_modules = tuple(entry.module_ref for entry in document.entries)

    assert entries[ARTIFACT_CONTENT_PROVIDER_MODULE_V2].inject == {
        ARTIFACT_CONTENT_PROVIDER_SESSIONS_INJECT_V2: ASYNC_SESSION_FACTORY_SERVICE_V2,
    }
    assert entries[ARTIFACT_CONTENT_APPLICATION_MODULE_V2].inject == {
        ARTIFACT_CONTENT_PROVIDER_INJECT_V2: ARTIFACT_CONTENT_PROVIDER_SERVICE_V2,
        ARTIFACT_CONTENT_STORAGE_INJECT_V2: OBJECT_STORAGE_SERVICE_V2,
    }
    provider_index = ordered_modules.index(ARTIFACT_CONTENT_PROVIDER_MODULE_V2)
    consumer_index = ordered_modules.index(ARTIFACT_CONTENT_APPLICATION_MODULE_V2)
    assert ordered_modules.index(ASYNC_SESSION_FACTORY_MODULE_V2) < provider_index
    assert provider_index < consumer_index
    assert ordered_modules.index(OBJECT_STORAGE_PROVIDER_MODULE_V2) < consumer_index


@pytest.mark.parametrize(
    "disabled_module",
    [ARTIFACT_CONTENT_PROVIDER_MODULE_V2, OBJECT_STORAGE_PROVIDER_MODULE_V2],
)
async def test_missing_provider_is_rejected_without_container_fallback(
    disabled_module: str,
) -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    isolated_modules = {
        "builtin://memstack/runtime/generation-boundary",
        ASYNC_SESSION_FACTORY_MODULE_V2,
        OBJECT_STORAGE_PROVIDER_MODULE_V2,
        ARTIFACT_CONTENT_PROVIDER_MODULE_V2,
        ARTIFACT_CONTENT_APPLICATION_MODULE_V2,
    }
    isolated_entries = tuple(
        entry for entry in document.entries if entry.module_ref in isolated_modules
    )
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False) if entry.module_ref == disabled_module else entry
            for entry in isolated_entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(
        disabled,
        {manifest.plugin_id: manifest},
        generation=158,
    )

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-artifact-content-services" in str(error.value)


async def test_invalid_profile_selected_provider_fails_closed() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(
        document,
        {manifest.plugin_id: manifest},
        generation=160,
    )
    definitions = builtin_runtime_definitions_v2()
    provider_definition = next(
        definition
        for definition in definitions
        if definition.module_ref == ARTIFACT_CONTENT_PROVIDER_MODULE_V2
    )

    def apply_invalid_provider(context: ContextV2, _config: Mapping[str, Any]) -> None:
        _ = context.provide(
            ARTIFACT_CONTENT_PROVIDER_SERVICE_V2,
            object(),
            label="invalid-artifact-content-provider",
        )

    invalid_provider = PluginDefinitionV2(
        module_ref=provider_definition.module_ref,
        contract_digest=provider_definition.contract_digest,
        apply=apply_invalid_provider,
    )
    definitions_with_invalid_provider = tuple(
        invalid_provider
        if definition.module_ref == ARTIFACT_CONTENT_PROVIDER_MODULE_V2
        else definition
        for definition in definitions
    )

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(definitions_with_invalid_provider).stage(snapshot)

    assert error.value.code == "invalid_artifact_content_provider"
    assert "invalid implementation" in str(error.value)


def test_manifest_declares_persistence_provider_before_application_consumer() -> None:
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    modules = {module.module_ref: module for module in manifest.modules}
    provider = modules[ARTIFACT_CONTENT_PROVIDER_MODULE_V2]
    consumer = modules[ARTIFACT_CONTENT_APPLICATION_MODULE_V2]

    assert [provided.service for provided in provider.contract.services.provides] == [
        ARTIFACT_CONTENT_PROVIDER_SERVICE_V2
    ]
    assert {
        requirement.alias: requirement.service
        for requirement in provider.contract.services.requires
    } == {
        ARTIFACT_CONTENT_PROVIDER_SESSIONS_INJECT_V2: ASYNC_SESSION_FACTORY_SERVICE_V2,
    }
    assert {
        requirement.alias: requirement.service
        for requirement in consumer.contract.services.requires
    } == {
        ARTIFACT_CONTENT_PROVIDER_INJECT_V2: ARTIFACT_CONTENT_PROVIDER_SERVICE_V2,
        ARTIFACT_CONTENT_STORAGE_INJECT_V2: OBJECT_STORAGE_SERVICE_V2,
    }


def test_application_consumer_does_not_select_sql_persistence_implementations() -> None:
    source = _CONSUMER_PATH.read_text(encoding="utf-8")

    assert "SqlArtifactContentAuthorityRepository" not in source
    assert "ArtifactContentCommitReconciler(" not in source
