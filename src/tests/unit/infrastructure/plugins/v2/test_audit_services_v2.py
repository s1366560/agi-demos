"""V2 Provider/Consumer coverage for audit query services."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2 import audit_services as audit_subject
from src.infrastructure.plugins.v2.audit_services import (
    AUDIT_APPLICATION_MODULE_V2,
    AUDIT_APPLICATION_SERVICE_V2,
    AUDIT_PROVIDER_MODULE_V2,
    AuditApplicationResolverV2,
)
from src.infrastructure.plugins.v2.boundary import OPERATION_DB_SESSION_SERVICE_V2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import (
    ContextV2,
    LoaderV2,
    OperationContextV2,
    RuntimeV2Error,
)
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


async def test_application_resolver_builds_audit_query_service_from_operation_db() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=81,
        version=81,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="http-audit:tenant-a",
                scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-a"),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            resolver = operation.require(AUDIT_APPLICATION_SERVICE_V2)
            assert isinstance(resolver, AuditApplicationResolverV2)

            services = resolver.resolve(operation)

            assert services.query._repo._session is db
    finally:
        await db.close()
        await host.close()


def test_provider_and_consumer_are_independent_explicit_profile_entries() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    enabled_modules = tuple(entry.module_ref for entry in document.entries if entry.enabled)

    assert AUDIT_PROVIDER_MODULE_V2 in enabled_modules
    assert AUDIT_APPLICATION_MODULE_V2 in enabled_modules
    assert enabled_modules.index(AUDIT_PROVIDER_MODULE_V2) < enabled_modules.index(
        AUDIT_APPLICATION_MODULE_V2
    )


async def test_application_resolver_rejects_missing_provider_without_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False) if entry.module_ref == AUDIT_PROVIDER_MODULE_V2 else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(
        disabled,
        {manifest.plugin_id: manifest},
        generation=82,
    )

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-audit-query-services" in str(error.value)


async def test_application_resolver_requires_operation_db_session() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=83,
        version=83,
    )
    assert publication.accepted is True
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="http-audit:no-db",
                scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-a"),
            ) as operation,
        ):
            resolver = operation.require(AUDIT_APPLICATION_SERVICE_V2)

            with pytest.raises(RuntimeV2Error) as error:
                resolver.resolve(operation)

            assert error.value.code == "missing_service"
    finally:
        await host.close()


async def test_application_resolver_rejects_non_async_operation_db_session() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=84,
        version=84,
    )
    assert publication.accepted is True
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="http-audit:invalid-db",
                scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-a"),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, object())
            resolver = operation.require(AUDIT_APPLICATION_SERVICE_V2)

            with pytest.raises(RuntimeV2Error) as error:
                resolver.resolve(operation)

            assert error.value.code == "invalid_operation_db_session"
    finally:
        await host.close()


async def test_later_audit_candidate_failure_keeps_last_good_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_apply = audit_subject._apply_audit_provider_v2
    apply_count = 0

    def flaky_apply(context: ContextV2, config: dict[str, object]) -> None:
        nonlocal apply_count
        apply_count += 1
        if apply_count > 1:
            raise RuntimeError("audit provider unavailable")
        original_apply(context, config)

    monkeypatch.setattr(audit_subject, "_apply_audit_provider_v2", flaky_apply)
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    first = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=85,
        version=85,
    )
    assert first.accepted is True
    active = host.manager.current
    assert active is not None

    failed = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=86,
        version=86,
    )

    assert failed.accepted is False
    assert failed.receipt.error_code == "staging_failed"
    assert host.manager.current is active
    assert host.manager.current.descriptor.generation == 85
    await host.close()
