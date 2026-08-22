"""V2 Provider/Consumer coverage for support-ticket operations."""

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
from src.infrastructure.plugins.v2.boundary import OPERATION_DB_SESSION_SERVICE_V2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.support_ticket_services import (
    SUPPORT_TICKET_APPLICATION_MODULE_V2,
    SUPPORT_TICKET_APPLICATION_SERVICE_V2,
    SUPPORT_TICKET_PROVIDER_MODULE_V2,
    SupportTenantAccessDeniedV2,
    SupportTicketApplicationResolverV2,
    SupportTicketApplicationServicesV2,
    SupportTicketSnapshotV2,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


def _snapshot(*, ticket_id: str = "ticket-a") -> SupportTicketSnapshotV2:
    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    return SupportTicketSnapshotV2(
        id=ticket_id,
        tenant_id="tenant-a",
        user_id="user-a",
        subject="Subject",
        message="Message",
        priority="medium",
        status="open",
        created_at=created_at,
        updated_at=created_at,
        resolved_at=None,
    )


async def test_support_ticket_resolver_builds_persistence_from_operation_session() -> None:
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
                operation_id="support-ticket:tenant-a",
                scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-a"),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            resolver = operation.require(SUPPORT_TICKET_APPLICATION_SERVICE_V2)

            assert isinstance(resolver, SupportTicketApplicationResolverV2)
            services = resolver.resolve(operation)
            assert getattr(services.persistence, "_session", None) is db
    finally:
        await db.close()
        await host.close()


def test_support_ticket_modules_are_explicit_ordered_profile_entries() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    enabled_modules = tuple(entry.module_ref for entry in document.entries if entry.enabled)

    assert SUPPORT_TICKET_PROVIDER_MODULE_V2 in enabled_modules
    assert SUPPORT_TICKET_APPLICATION_MODULE_V2 in enabled_modules
    assert enabled_modules.index(SUPPORT_TICKET_PROVIDER_MODULE_V2) < enabled_modules.index(
        SUPPORT_TICKET_APPLICATION_MODULE_V2
    )
    application_entry = next(
        entry
        for entry in document.entries
        if entry.module_ref == SUPPORT_TICKET_APPLICATION_MODULE_V2
    )
    assert application_entry.inject == {"provider": "service:persistence.support-ticket-provider"}


async def test_support_ticket_application_rejects_missing_provider_without_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == SUPPORT_TICKET_PROVIDER_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(disabled, {manifest.plugin_id: manifest}, generation=82)

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-support-ticket-services" in str(error.value)


async def test_support_ticket_resolver_rejects_non_session_operation_service() -> None:
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
                operation_id="support-ticket:invalid-db",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, object())
            resolver = operation.require(SUPPORT_TICKET_APPLICATION_SERVICE_V2)
            assert isinstance(resolver, SupportTicketApplicationResolverV2)

            with pytest.raises(RuntimeV2Error) as error:
                _ = resolver.resolve(operation)

            assert error.value.code == "invalid_operation_db_session"
    finally:
        await host.close()


async def test_support_ticket_application_rejects_foreign_tenant_before_create() -> None:
    persistence = SimpleNamespace(
        has_tenant_membership=AsyncMock(return_value=False),
        create_ticket=AsyncMock(),
    )
    services = SupportTicketApplicationServicesV2(persistence=persistence)

    with pytest.raises(SupportTenantAccessDeniedV2):
        await services.create_ticket(
            user_id="user-a",
            is_superuser=False,
            data={"tenant_id": "tenant-b", "subject": "Denied", "message": "Denied"},
        )

    persistence.has_tenant_membership.assert_awaited_once_with(
        user_id="user-a",
        tenant_id="tenant-b",
    )
    persistence.create_ticket.assert_not_awaited()


async def test_support_ticket_application_delegates_user_scoped_crud() -> None:
    snapshot = _snapshot()
    persistence = SimpleNamespace(
        has_tenant_membership=AsyncMock(return_value=True),
        create_ticket=AsyncMock(return_value=snapshot),
        list_tickets=AsyncMock(return_value=SimpleNamespace(tickets=(snapshot,), total=1)),
        get_ticket=AsyncMock(return_value=snapshot),
        update_ticket=AsyncMock(return_value=snapshot),
        close_ticket=AsyncMock(return_value=snapshot),
    )
    services = SupportTicketApplicationServicesV2(persistence=persistence)

    created = await services.create_ticket(
        user_id="user-a",
        is_superuser=False,
        data={
            "tenant_id": "tenant-a",
            "subject": "Subject",
            "message": "Message",
            "priority": "high",
        },
    )
    page = await services.list_tickets(
        user_id="user-a",
        is_superuser=False,
        tenant_id="tenant-a",
        status="open",
        limit=10,
        offset=2,
    )
    fetched = await services.get_ticket(user_id="user-a", ticket_id="ticket-a")
    updated = await services.update_ticket(
        user_id="user-a",
        ticket_id="ticket-a",
        data={"subject": "New", "ignored": "value"},
    )
    closed = await services.close_ticket(user_id="user-a", ticket_id="ticket-a")

    assert created is snapshot
    assert page.tickets == (snapshot,)
    assert page.total == 1
    assert page.limit == 10
    assert page.offset == 2
    assert fetched is snapshot
    assert updated is snapshot
    assert closed is snapshot
    record = persistence.create_ticket.await_args.kwargs["record"]
    assert record.user_id == "user-a"
    assert record.tenant_id == "tenant-a"
    assert record.priority == "high"
    persistence.list_tickets.assert_awaited_once_with(
        user_id="user-a",
        tenant_id="tenant-a",
        status="open",
        limit=10,
        offset=2,
    )
    persistence.get_ticket.assert_awaited_once_with(
        user_id="user-a",
        ticket_id="ticket-a",
    )
    persistence.update_ticket.assert_awaited_once_with(
        user_id="user-a",
        ticket_id="ticket-a",
        updates={"subject": "New"},
    )
    resolved_at = persistence.close_ticket.await_args.kwargs["resolved_at"]
    assert resolved_at.tzinfo is UTC
