"""V2 Provider/Consumer coverage for persistence, project, and tenant services."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.configuration.di_container import DIContainer
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.boundary import OPERATION_DB_SESSION_SERVICE_V2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.project_tenant_services import (
    PROJECT_TENANT_PROVIDER_MODULE_V2,
    PROJECT_TENANT_SHADOW_MODULE_V2,
    PROJECT_TENANT_SHADOW_SERVICE_V2,
    ProjectTenantServicesV2,
    ProjectTenantShadowComparatorV2,
)
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import (
    FiberPhaseV2,
    LoaderV2,
    OperationContextV2,
    RuntimeV2Error,
)
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


def _legacy_services(container: DIContainer) -> ProjectTenantServicesV2:
    return ProjectTenantServicesV2(
        project_repository=container.project_repository(),
        project_service=container.project_service(),
        tenant_service=container.tenant_service(),
    )


@pytest.mark.unit
async def test_project_tenant_shadow_matches_types_session_and_project_scope() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=1,
        version=1,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with await host.acquire() as generation:
            scope = ScopeV2(
                kind=ScopeKindV2.PROJECT,
                tenant_id="tenant-a",
                project_id="project-a",
            )
            async with OperationContextV2(
                generation=generation,
                operation_id="http-shadow:project-a",
                scope=scope,
            ) as operation:
                _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
                comparator = operation.require(PROJECT_TENANT_SHADOW_SERVICE_V2)
                assert isinstance(comparator, ProjectTenantShadowComparatorV2)

                evidence = comparator.compare(
                    operation=operation,
                    legacy=_legacy_services(DIContainer(db=db)),
                    expected_scope=scope,
                )

                assert evidence.matches is True
                assert evidence.differences == ()
                assert evidence.error_code is None
                assert evidence.descriptor == generation.descriptor
                assert evidence.scope == scope
            assert operation.phase is FiberPhaseV2.DISPOSED
    finally:
        await db.close()
        await host.close()


@pytest.mark.unit
async def test_project_tenant_shadow_reports_session_and_scope_differences() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=1,
        version=1,
    )
    operation_db = AsyncSession()
    legacy_db = AsyncSession()
    try:
        async with await host.acquire() as generation:
            operation_scope = ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-a")
            expected_scope = ScopeV2(
                kind=ScopeKindV2.PROJECT,
                tenant_id="tenant-a",
                project_id="project-a",
            )
            async with OperationContextV2(
                generation=generation,
                operation_id="http-shadow:mismatch",
                scope=operation_scope,
            ) as operation:
                _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, operation_db)
                comparator = operation.require(PROJECT_TENANT_SHADOW_SERVICE_V2)
                assert isinstance(comparator, ProjectTenantShadowComparatorV2)

                evidence = comparator.compare(
                    operation=operation,
                    legacy=_legacy_services(DIContainer(db=legacy_db)),
                    expected_scope=expected_scope,
                )

                assert evidence.matches is False
                assert "operation.scope" in evidence.differences
                assert "project_repository.legacy_session" in evidence.differences
                assert "project_service.project_repository.legacy_session" in evidence.differences
                assert "tenant_service.tenant_repository.legacy_session" in evidence.differences
    finally:
        await operation_db.close()
        await legacy_db.close()
        await host.close()


@pytest.mark.unit
async def test_project_tenant_provider_requires_operation_db_session_without_fallback() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=1,
        version=1,
    )
    legacy_db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="http-shadow:missing-db",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as operation,
        ):
            comparator = operation.require(PROJECT_TENANT_SHADOW_SERVICE_V2)
            assert isinstance(comparator, ProjectTenantShadowComparatorV2)
            with pytest.raises(RuntimeV2Error) as error:
                comparator.compare(
                    operation=operation,
                    legacy=_legacy_services(DIContainer(db=legacy_db)),
                    expected_scope=ScopeV2(kind=ScopeKindV2.ROOT),
                )
    finally:
        await legacy_db.close()
        await host.close()

    assert error.value.code == "missing_service"


@pytest.mark.unit
def test_project_tenant_modules_are_independent_explicit_profile_entries() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    enabled_modules = {entry.module_ref for entry in document.entries if entry.enabled}

    assert PROJECT_TENANT_PROVIDER_MODULE_V2 in enabled_modules
    assert PROJECT_TENANT_SHADOW_MODULE_V2 in enabled_modules


@pytest.mark.unit
async def test_disabling_project_tenant_provider_rejects_shadow_consumer_without_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == PROJECT_TENANT_PROVIDER_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(
        disabled,
        {manifest.plugin_id: manifest},
        generation=2,
    )

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
