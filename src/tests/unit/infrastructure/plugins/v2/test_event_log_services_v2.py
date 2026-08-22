"""V2 Provider/Consumer coverage for tenant event-log queries."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.model.tenant.event_log import EventLog
from src.infrastructure.plugins.v2.boundary import OPERATION_DB_SESSION_SERVICE_V2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.event_log_services import (
    EVENT_LOG_APPLICATION_MODULE_V2,
    EVENT_LOG_APPLICATION_SERVICE_V2,
    EVENT_LOG_PROVIDER_MODULE_V2,
    EventLogApplicationResolverV2,
    EventLogQueryApplicationServicesV2,
)
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


async def test_event_log_resolver_builds_service_from_operation_session() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=71,
        version=71,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="event-log-query:tenant-a",
                scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-a"),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            resolver = operation.require(EVENT_LOG_APPLICATION_SERVICE_V2)

            assert isinstance(resolver, EventLogApplicationResolverV2)
            services = resolver.resolve(operation)
            repository = getattr(services.query, "_repo", None)
            assert getattr(repository, "_session", None) is db
    finally:
        await db.close()
        await host.close()


def test_event_log_modules_are_explicit_ordered_profile_entries() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    enabled_modules = tuple(entry.module_ref for entry in document.entries if entry.enabled)

    assert EVENT_LOG_PROVIDER_MODULE_V2 in enabled_modules
    assert EVENT_LOG_APPLICATION_MODULE_V2 in enabled_modules
    assert enabled_modules.index(EVENT_LOG_PROVIDER_MODULE_V2) < enabled_modules.index(
        EVENT_LOG_APPLICATION_MODULE_V2
    )
    application_entry = next(
        entry for entry in document.entries if entry.module_ref == EVENT_LOG_APPLICATION_MODULE_V2
    )
    assert application_entry.inject == {"provider": "service:persistence.event-log-query-provider"}


async def test_event_log_application_rejects_missing_provider_without_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == EVENT_LOG_PROVIDER_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(disabled, {manifest.plugin_id: manifest}, generation=72)

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-event-log-query-services" in str(error.value)


async def test_event_log_resolver_rejects_non_session_operation_service() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=73,
        version=73,
    )
    assert publication.accepted is True
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="event-log-query:invalid-db",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, object())
            resolver = operation.require(EVENT_LOG_APPLICATION_SERVICE_V2)
            assert isinstance(resolver, EventLogApplicationResolverV2)

            with pytest.raises(RuntimeV2Error) as error:
                _ = resolver.resolve(operation)

            assert error.value.code == "invalid_operation_db_session"
    finally:
        await host.close()


async def test_event_log_application_delegates_exact_tenant_query() -> None:
    event = EventLog(
        id="event-a",
        tenant_id="tenant-a",
        event_type="gene.installed",
        message="installed",
        source="marketplace",
        metadata={},
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    query = SimpleNamespace(
        list_events=AsyncMock(return_value=([event], 1)),
        get_event_types=AsyncMock(return_value=["gene.installed"]),
    )
    services = EventLogQueryApplicationServicesV2(query=query)

    items, total = await services.list_events(
        tenant_id="tenant-a",
        event_type="gene.installed",
        date_from=None,
        date_to=None,
        page=2,
        page_size=7,
    )
    event_types = await services.get_event_types(tenant_id="tenant-a")

    assert items == [event]
    assert total == 1
    assert event_types == ["gene.installed"]
    query.list_events.assert_awaited_once_with(
        tenant_id="tenant-a",
        event_type="gene.installed",
        date_from=None,
        date_to=None,
        page=2,
        page_size=7,
    )
    query.get_event_types.assert_awaited_once_with("tenant-a")
