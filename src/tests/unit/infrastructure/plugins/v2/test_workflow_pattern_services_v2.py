"""V2 Provider/Consumer coverage for workflow-pattern persistence."""

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
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.workflow_pattern_services import (
    WORKFLOW_PATTERN_APPLICATION_MODULE_V2,
    WORKFLOW_PATTERN_APPLICATION_SERVICE_V2,
    WORKFLOW_PATTERN_PROVIDER_MODULE_V2,
    WorkflowPatternApplicationResolverV2,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


async def test_workflow_pattern_resolver_builds_repository_from_operation_session() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=171,
        version=171,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="workflow-pattern:tenant-a",
                scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-a"),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            resolver = operation.require(WORKFLOW_PATTERN_APPLICATION_SERVICE_V2)

            assert isinstance(resolver, WorkflowPatternApplicationResolverV2)
            services = resolver.resolve(operation)
            assert getattr(services.repository, "_session", None) is db
    finally:
        await db.close()
        await host.close()


def test_workflow_pattern_modules_are_explicit_ordered_profile_entries() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    enabled_modules = tuple(entry.module_ref for entry in document.entries if entry.enabled)

    assert WORKFLOW_PATTERN_PROVIDER_MODULE_V2 in enabled_modules
    assert WORKFLOW_PATTERN_APPLICATION_MODULE_V2 in enabled_modules
    assert enabled_modules.index(WORKFLOW_PATTERN_PROVIDER_MODULE_V2) < enabled_modules.index(
        WORKFLOW_PATTERN_APPLICATION_MODULE_V2
    )
    application_entry = next(
        entry
        for entry in document.entries
        if entry.module_ref == WORKFLOW_PATTERN_APPLICATION_MODULE_V2
    )
    assert application_entry.inject == {"provider": "service:persistence.workflow-pattern-provider"}


async def test_workflow_pattern_application_rejects_missing_provider_without_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == WORKFLOW_PATTERN_PROVIDER_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(disabled, {manifest.plugin_id: manifest}, generation=172)

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-workflow-pattern-services" in str(error.value)


async def test_workflow_pattern_resolver_rejects_non_session_operation_service() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=173,
        version=173,
    )
    assert publication.accepted is True
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="workflow-pattern:invalid-db",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, object())
            resolver = operation.require(WORKFLOW_PATTERN_APPLICATION_SERVICE_V2)
            assert isinstance(resolver, WorkflowPatternApplicationResolverV2)

            with pytest.raises(RuntimeV2Error) as error:
                _ = resolver.resolve(operation)

            assert error.value.code == "invalid_operation_db_session"
    finally:
        await host.close()


def test_static_workflow_pattern_accessor_is_retired_after_v2_cutover() -> None:
    assert not hasattr(DIContainer, "workflow_pattern_repository")
