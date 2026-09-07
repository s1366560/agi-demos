"""V2 application resolver coverage for project and tenant services."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.boundary import OPERATION_DB_SESSION_SERVICE_V2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.project_tenant_services import (
    PROJECT_TENANT_APPLICATION_MODULE_V2,
    PROJECT_TENANT_APPLICATION_SERVICE_V2,
    PROJECT_TENANT_PROVIDER_MODULE_V2,
    ProjectTenantApplicationResolverV2,
)
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


@pytest.mark.unit
async def test_application_resolver_builds_services_from_the_operation_provider() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=4,
        version=4,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="http-authority:project-a",
                scope=ScopeV2(
                    kind=ScopeKindV2.PROJECT,
                    tenant_id="tenant-a",
                    project_id="project-a",
                ),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            resolver = operation.require(PROJECT_TENANT_APPLICATION_SERVICE_V2)
            assert isinstance(resolver, ProjectTenantApplicationResolverV2)

            services = resolver.resolve(operation)

            assert getattr(services.project_repository, "_session", None) is db
            assert services.project_service._project_repo.session is db
            assert services.project_service._user_repo.session is db
            assert services.tenant_service._tenant_repo.session is db
            assert services.tenant_service._user_repo.session is db
    finally:
        await db.close()
        await host.close()


@pytest.mark.unit
def test_application_resolver_is_an_independent_explicit_profile_entry() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    enabled_modules = tuple(entry.module_ref for entry in document.entries if entry.enabled)

    assert PROJECT_TENANT_PROVIDER_MODULE_V2 in enabled_modules
    assert PROJECT_TENANT_APPLICATION_MODULE_V2 in enabled_modules
    assert enabled_modules.index(PROJECT_TENANT_PROVIDER_MODULE_V2) < enabled_modules.index(
        PROJECT_TENANT_APPLICATION_MODULE_V2
    )


@pytest.mark.unit
async def test_application_resolver_rejects_a_missing_provider_without_fallback() -> None:
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
        generation=5,
    )

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-project-tenant-services" in str(error.value)
