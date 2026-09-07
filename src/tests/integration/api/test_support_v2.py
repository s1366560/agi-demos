"""Production generation integration coverage for both support-ticket aliases."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI, status
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    initialize_plugin_runtime_v2,
    shutdown_plugin_runtime_v2,
)
from src.infrastructure.adapters.secondary.persistence.models import SupportTicket, Tenant, User

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _support_v2_runtime(
    test_app: FastAPI,
    test_user: User,
    test_tenant_db: Tenant,
) -> AsyncIterator[None]:
    """Exercise support requests through the production generation dispatcher."""
    original_current_user = test_app.dependency_overrides[get_current_user]
    test_app.dependency_overrides[get_current_user] = lambda: test_user
    try:
        await initialize_plugin_runtime_v2(test_app)
        owned_rows = test_app.state.platform_plugin_route_graph_v2.v2_owned_row_ids
        assert "support" in owned_rows
        assert "support-2" in owned_rows
        assert test_tenant_db.id
        yield
    finally:
        await shutdown_plugin_runtime_v2(test_app)
        test_app.dependency_overrides[get_current_user] = original_current_user


async def test_support_crud_crosses_both_generation_owned_aliases(
    authenticated_async_client: AsyncClient,
    test_db: AsyncSession,
    test_tenant_db: Tenant,
) -> None:
    create_response = await authenticated_async_client.post(
        "/api/v1/support/tickets",
        json={
            "tenant_id": test_tenant_db.id,
            "subject": "V2 support",
            "message": "generation owned",
            "priority": "high",
        },
    )
    assert create_response.status_code == status.HTTP_200_OK
    ticket_id = create_response.json()["id"]

    list_response = await authenticated_async_client.get(
        "/support/tickets",
        params={"tenant_id": test_tenant_db.id},
    )
    detail_response = await authenticated_async_client.get(f"/api/v1/support/tickets/{ticket_id}")
    update_response = await authenticated_async_client.put(
        f"/support/tickets/{ticket_id}",
        json={"subject": "Updated by V2"},
    )
    close_response = await authenticated_async_client.post(
        f"/api/v1/support/tickets/{ticket_id}/close"
    )

    assert list_response.status_code == status.HTTP_200_OK
    assert ticket_id in {ticket["id"] for ticket in list_response.json()["tickets"]}
    assert detail_response.status_code == status.HTTP_200_OK
    assert detail_response.json()["tenant_id"] == test_tenant_db.id
    assert update_response.status_code == status.HTTP_200_OK
    assert update_response.json()["subject"] == "Updated by V2"
    assert close_response.status_code == status.HTTP_200_OK
    assert close_response.json()["status"] == "closed"
    test_db.expire_all()
    result = await test_db.execute(select(SupportTicket).where(SupportTicket.id == ticket_id))
    assert result.scalar_one().status == "closed"


async def test_support_rejects_existing_tenant_without_membership(
    authenticated_async_client: AsyncClient,
    test_db: AsyncSession,
    another_user: User,
) -> None:
    tenant = Tenant(
        id="88888888-8888-4888-8888-888888888888",
        name="Foreign Support Tenant",
        slug="foreign-support-tenant",
        owner_id=str(another_user.id),
        plan="free",
    )
    test_db.add(tenant)
    await test_db.commit()

    response = await authenticated_async_client.post(
        "/api/v1/support/tickets",
        json={
            "tenant_id": tenant.id,
            "subject": "Denied",
            "message": "Denied",
        },
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN, response.text
