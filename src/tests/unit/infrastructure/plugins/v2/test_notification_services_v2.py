"""V2 provider and application coverage for notification services."""

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
from src.infrastructure.plugins.v2.notification_services import (
    NOTIFICATION_APPLICATION_MODULE_V2,
    NOTIFICATION_APPLICATION_SERVICE_V2,
    NOTIFICATION_PROVIDER_MODULE_V2,
    NotificationAccessDeniedV2,
    NotificationApplicationResolverV2,
    NotificationApplicationServicesV2,
)
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


async def test_notification_application_resolver_builds_operation_owned_services() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=24,
        version=24,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="notifications:user-a",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            resolver = operation.require(NOTIFICATION_APPLICATION_SERVICE_V2)
            assert isinstance(resolver, NotificationApplicationResolverV2)

            services = resolver.resolve(operation)

            assert getattr(services.persistence, "_session", None) is db
    finally:
        await db.close()
        await host.close()


def test_notification_modules_are_explicit_ordered_profile_entries() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    enabled_modules = tuple(entry.module_ref for entry in document.entries if entry.enabled)

    assert NOTIFICATION_PROVIDER_MODULE_V2 in enabled_modules
    assert NOTIFICATION_APPLICATION_MODULE_V2 in enabled_modules
    assert enabled_modules.index(NOTIFICATION_PROVIDER_MODULE_V2) < enabled_modules.index(
        NOTIFICATION_APPLICATION_MODULE_V2
    )


async def test_notification_application_rejects_missing_provider_without_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == NOTIFICATION_PROVIDER_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(disabled, {manifest.plugin_id: manifest}, generation=25)

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-notification-services" in str(error.value)


async def test_cross_user_create_is_rejected_before_persistence_mutation() -> None:
    persistence = SimpleNamespace(create_notification=AsyncMock())
    services = NotificationApplicationServicesV2(persistence=persistence)

    with pytest.raises(NotificationAccessDeniedV2):
        await services.create_notification(
            user_id="user-a",
            is_superuser=False,
            data={"user_id": "user-b", "message": "denied"},
        )

    persistence.create_notification.assert_not_awaited()
