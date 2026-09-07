"""V2 Provider/Consumer coverage for tenant billing services."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.models import Tenant, User
from src.infrastructure.plugins.v2 import billing_services as billing_subject
from src.infrastructure.plugins.v2.billing_services import (
    BILLING_APPLICATION_MODULE_V2,
    BILLING_APPLICATION_SERVICE_V2,
    BILLING_PROVIDER_MODULE_V2,
    BillingApplicationResolverV2,
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


async def test_application_resolver_builds_billing_services_from_operation_db() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=96,
        version=96,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="http-billing:tenant-a",
                scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-a"),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            resolver = operation.require(BILLING_APPLICATION_SERVICE_V2)
            assert isinstance(resolver, BillingApplicationResolverV2)

            services = resolver.resolve(operation)

            assert services.billing.persistence._session is db
    finally:
        await db.close()
        await host.close()


def test_provider_and_consumer_are_independent_explicit_profile_entries() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    enabled_modules = tuple(entry.module_ref for entry in document.entries if entry.enabled)

    assert BILLING_PROVIDER_MODULE_V2 in enabled_modules
    assert BILLING_APPLICATION_MODULE_V2 in enabled_modules
    assert enabled_modules.index(BILLING_PROVIDER_MODULE_V2) < enabled_modules.index(
        BILLING_APPLICATION_MODULE_V2
    )


async def test_application_resolver_rejects_missing_provider_without_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == BILLING_PROVIDER_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(
        disabled,
        {manifest.plugin_id: manifest},
        generation=97,
    )

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-billing-services" in str(error.value)


async def test_application_resolver_requires_operation_db_session() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=98,
        version=98,
    )
    assert publication.accepted is True
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="http-billing:no-db",
                scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-a"),
            ) as operation,
        ):
            resolver = operation.require(BILLING_APPLICATION_SERVICE_V2)

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
        generation=99,
        version=99,
    )
    assert publication.accepted is True
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="http-billing:invalid-db",
                scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-a"),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, object())
            resolver = operation.require(BILLING_APPLICATION_SERVICE_V2)

            with pytest.raises(RuntimeV2Error) as error:
                resolver.resolve(operation)

            assert error.value.code == "invalid_operation_db_session"
    finally:
        await host.close()


async def test_billing_read_and_upgrade_use_the_operation_session(
    test_db: AsyncSession,
    test_tenant_db: Tenant,
    test_user: User,
) -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=100,
        version=100,
    )
    assert publication.accepted is True
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="http-billing:read-upgrade",
                scope=ScopeV2(
                    kind=ScopeKindV2.TENANT,
                    tenant_id=test_tenant_db.id,
                ),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, test_db)
            resolver = operation.require(BILLING_APPLICATION_SERVICE_V2)
            services = resolver.resolve(operation)

            billing = await services.billing.get_billing_info(
                user_id=test_user.id,
                tenant_id=test_tenant_db.id,
            )
            upgraded = await services.billing.upgrade_plan(
                user_id=test_user.id,
                tenant_id=test_tenant_db.id,
                plan_data={"plan": "pro"},
            )

            assert billing["tenant"]["id"] == test_tenant_db.id
            assert billing["usage"]["projects"] == 0
            assert upgraded["plan"] == "pro"
            assert upgraded["storage_limit"] == 100 * 1024 * 1024 * 1024
            assert services.billing.persistence._session is test_db
    finally:
        await host.close()


async def test_later_billing_candidate_failure_keeps_last_good_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_apply = billing_subject._apply_billing_provider_v2
    apply_count = 0

    def flaky_apply(context: ContextV2, config: dict[str, object]) -> None:
        nonlocal apply_count
        apply_count += 1
        if apply_count > 1:
            raise RuntimeError("billing provider unavailable")
        original_apply(context, config)

    monkeypatch.setattr(billing_subject, "_apply_billing_provider_v2", flaky_apply)
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    first = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=101,
        version=101,
    )
    assert first.accepted is True
    active = host.manager.current
    assert active is not None

    failed = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=102,
        version=102,
    )

    assert failed.accepted is False
    assert failed.receipt.error_code == "staging_failed"
    assert host.manager.current is active
    assert host.manager.current.descriptor.generation == 101
    await host.close()
