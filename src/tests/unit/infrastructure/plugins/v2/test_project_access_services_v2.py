"""V2 project-membership Provider and application authority coverage."""

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
from src.infrastructure.plugins.v2.project_access_services import (
    PROJECT_ACCESS_APPLICATION_MODULE_V2,
    PROJECT_ACCESS_APPLICATION_SERVICE_V2,
    PROJECT_ACCESS_PROVIDER_MODULE_V2,
    ProjectAccessDeniedV2,
    ProjectAccessResolverV2,
    SqlProjectAccessTransactionV2,
)
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


async def test_sql_project_access_requires_exact_tenant_membership(
    db_session: AsyncSession,
    test_project_db: object,
    test_user: object,
) -> None:
    transaction = SqlProjectAccessTransactionV2(db=db_session)
    project_id = str(test_project_db.id)
    tenant_id = str(test_project_db.tenant_id)
    user_id = str(test_user.id)

    grant = await transaction.require_access(
        project_id=project_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )

    assert grant.project_id == project_id
    assert grant.tenant_id == tenant_id
    assert grant.user_id == user_id
    with pytest.raises(ProjectAccessDeniedV2):
        await transaction.require_access(
            project_id=project_id,
            tenant_id="tenant-other",
            user_id=user_id,
        )
    with pytest.raises(ProjectAccessDeniedV2):
        await transaction.require_access(
            project_id=project_id,
            tenant_id=tenant_id,
            user_id="user-other",
        )


async def test_project_access_resolver_uses_the_operation_session() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=981,
        version=981,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="project-access:project-a",
                scope=ScopeV2(
                    kind=ScopeKindV2.PROJECT,
                    tenant_id="tenant-a",
                    project_id="project-a",
                ),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            resolver = operation.require(PROJECT_ACCESS_APPLICATION_SERVICE_V2)

            assert isinstance(resolver, ProjectAccessResolverV2)
            service = resolver.resolve(operation)
            assert isinstance(service.transaction, SqlProjectAccessTransactionV2)
            assert service.transaction.db is db
    finally:
        await db.close()
        await host.close()


def test_project_access_modules_are_explicit_and_provider_precedes_application() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    enabled_modules = tuple(entry.module_ref for entry in document.entries if entry.enabled)

    assert PROJECT_ACCESS_PROVIDER_MODULE_V2 in enabled_modules
    assert PROJECT_ACCESS_APPLICATION_MODULE_V2 in enabled_modules
    assert enabled_modules.index(PROJECT_ACCESS_PROVIDER_MODULE_V2) < enabled_modules.index(
        PROJECT_ACCESS_APPLICATION_MODULE_V2
    )
    application = next(
        entry
        for entry in document.entries
        if entry.module_ref == PROJECT_ACCESS_APPLICATION_MODULE_V2
    )
    assert application.inject == {"provider": "service:persistence.project-access-provider"}


async def test_project_access_application_rejects_missing_provider_without_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == PROJECT_ACCESS_PROVIDER_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(disabled, {manifest.plugin_id: manifest}, generation=982)

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-project-access" in str(error.value)
