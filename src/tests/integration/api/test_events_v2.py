"""Production generation integration coverage for tenant event-log routes."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI, status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    initialize_plugin_runtime_v2,
    shutdown_plugin_runtime_v2,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Tenant,
    TenantEventLogModel,
    User,
)

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _events_v2_runtime(
    test_app: FastAPI,
    test_user: User,
    test_tenant_db: Tenant,
) -> AsyncIterator[None]:
    """Exercise event-log requests through the production generation dispatcher."""
    original_current_user = test_app.dependency_overrides[get_current_user]
    test_app.dependency_overrides[get_current_user] = lambda: test_user
    try:
        await initialize_plugin_runtime_v2(test_app)
        assert "events" in test_app.state.platform_plugin_route_graph_v2.v2_owned_row_ids
        assert test_tenant_db.id
        yield
    finally:
        await shutdown_plugin_runtime_v2(test_app)
        test_app.dependency_overrides[get_current_user] = original_current_user


async def test_event_queries_use_generation_service_and_authorized_tenant(
    authenticated_async_client: AsyncClient,
    test_db: AsyncSession,
    test_tenant_db,
) -> None:
    event = TenantEventLogModel(
        id="event-v2-a",
        tenant_id=str(test_tenant_db.id),
        event_type="gene.installed",
        message="Installed from V2",
        source="marketplace",
        metadata_={"generation": "v2"},
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    test_db.add(event)
    await test_db.commit()

    list_response = await authenticated_async_client.get(
        "/api/v1/events",
        params={"tenant_id": str(test_tenant_db.id)},
    )
    types_response = await authenticated_async_client.get(
        "/api/v1/events/types",
        params={"tenant_id": str(test_tenant_db.id)},
    )

    assert list_response.status_code == status.HTTP_200_OK
    assert list_response.json() == {
        "items": [
            {
                "id": "event-v2-a",
                "tenant_id": str(test_tenant_db.id),
                "event_type": "gene.installed",
                "message": "Installed from V2",
                "source": "marketplace",
                "metadata": {"generation": "v2"},
                "created_at": "2026-01-01T00:00:00",
            }
        ],
        "total": 1,
        "page": 1,
        "page_size": 20,
    }
    assert types_response.status_code == status.HTTP_200_OK
    assert types_response.json() == ["gene.installed"]


async def test_event_query_rejects_existing_tenant_without_membership(
    authenticated_async_client: AsyncClient,
    test_db: AsyncSession,
    test_tenant_db: Tenant,
    another_user: User,
) -> None:
    tenant = Tenant(
        id="77777777-7777-4777-8777-777777777777",
        name="V2 Non-member Tenant",
        slug="v2-non-member-tenant",
        owner_id=str(another_user.id),
        plan="free",
    )
    test_db.add(tenant)
    await test_db.commit()
    assert test_tenant_db.id != tenant.id

    response = await authenticated_async_client.get(
        "/api/v1/events",
        params={"tenant_id": tenant.id},
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN, response.text
