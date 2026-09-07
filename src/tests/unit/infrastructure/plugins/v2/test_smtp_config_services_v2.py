"""V2 Provider/Consumer coverage for tenant SMTP configuration services."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.models import Project
from src.infrastructure.plugins.v2 import smtp_config_services as smtp_subject
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
from src.infrastructure.plugins.v2.smtp_config_services import (
    SMTP_CONFIG_APPLICATION_MODULE_V2,
    SMTP_CONFIG_APPLICATION_SERVICE_V2,
    SMTP_CONFIG_PROVIDER_MODULE_V2,
    SmtpConfigApplicationResolverV2,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


async def test_application_resolver_builds_smtp_service_from_operation_db() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=88,
        version=88,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="http-smtp-config:tenant-a",
                scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-a"),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            resolver = operation.require(SMTP_CONFIG_APPLICATION_SERVICE_V2)
            assert isinstance(resolver, SmtpConfigApplicationResolverV2)

            services = resolver.resolve(operation)

            assert services.smtp._repo._session is db
    finally:
        await db.close()
        await host.close()


def test_provider_and_consumer_are_independent_explicit_profile_entries() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    enabled_modules = tuple(entry.module_ref for entry in document.entries if entry.enabled)

    assert SMTP_CONFIG_PROVIDER_MODULE_V2 in enabled_modules
    assert SMTP_CONFIG_APPLICATION_MODULE_V2 in enabled_modules
    assert enabled_modules.index(SMTP_CONFIG_PROVIDER_MODULE_V2) < enabled_modules.index(
        SMTP_CONFIG_APPLICATION_MODULE_V2
    )


async def test_application_resolver_rejects_missing_provider_without_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == SMTP_CONFIG_PROVIDER_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(
        disabled,
        {manifest.plugin_id: manifest},
        generation=89,
    )

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-smtp-config-services" in str(error.value)


async def test_application_resolver_requires_operation_db_session() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=90,
        version=90,
    )
    assert publication.accepted is True
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="http-smtp-config:no-db",
                scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-a"),
            ) as operation,
        ):
            resolver = operation.require(SMTP_CONFIG_APPLICATION_SERVICE_V2)

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
        generation=91,
        version=91,
    )
    assert publication.accepted is True
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="http-smtp-config:invalid-db",
                scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-a"),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, object())
            resolver = operation.require(SMTP_CONFIG_APPLICATION_SERVICE_V2)

            with pytest.raises(RuntimeV2Error) as error:
                resolver.resolve(operation)

            assert error.value.code == "invalid_operation_db_session"
    finally:
        await host.close()


async def test_smtp_crud_uses_the_operation_session(
    test_db: AsyncSession,
    test_project_db: Project,
) -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=92,
        version=92,
    )
    assert publication.accepted is True
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="http-smtp-config:crud",
                scope=ScopeV2(
                    kind=ScopeKindV2.TENANT,
                    tenant_id=test_project_db.tenant_id,
                ),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, test_db)
            resolver = operation.require(SMTP_CONFIG_APPLICATION_SERVICE_V2)
            services = resolver.resolve(operation)

            created = await services.smtp.upsert_config(
                test_project_db.tenant_id,
                smtp_host="smtp.example.com",
                smtp_port=587,
                smtp_username="mailer",
                smtp_password="operation-secret",
                from_email="mailer@example.com",
                from_name="MemStack",
                use_tls=True,
            )
            loaded = await services.smtp.get_config(test_project_db.tenant_id)
            await services.smtp.delete_config(created.id)
            deleted = await services.smtp.get_config(test_project_db.tenant_id)

            assert loaded is not None
            assert loaded.id == created.id
            assert loaded.smtp_password_encrypted != "operation-secret"
            assert deleted is None
    finally:
        await host.close()


async def test_later_smtp_candidate_failure_keeps_last_good_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_apply = smtp_subject._apply_smtp_config_provider_v2
    apply_count = 0

    def flaky_apply(context: ContextV2, config: dict[str, object]) -> None:
        nonlocal apply_count
        apply_count += 1
        if apply_count > 1:
            raise RuntimeError("smtp provider unavailable")
        original_apply(context, config)

    monkeypatch.setattr(smtp_subject, "_apply_smtp_config_provider_v2", flaky_apply)
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    first = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=93,
        version=93,
    )
    assert first.accepted is True
    active = host.manager.current
    assert active is not None

    failed = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=94,
        version=94,
    )

    assert failed.accepted is False
    assert failed.receipt.error_code == "staging_failed"
    assert host.manager.current is active
    assert host.manager.current.descriptor.generation == 93
    await host.close()
