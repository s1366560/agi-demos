"""Production generation integration coverage for notification routes."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI, status
from httpx import AsyncClient
from sqlalchemy import select

from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    initialize_plugin_runtime_v2,
    shutdown_plugin_runtime_v2,
)
from src.infrastructure.adapters.secondary.persistence.models import Notification

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _notification_v2_runtime(test_app: FastAPI) -> AsyncIterator[None]:
    """Exercise notification requests through the production generation dispatcher."""
    await initialize_plugin_runtime_v2(test_app)
    assert "notifications" in test_app.state.platform_plugin_route_graph_v2.v2_owned_row_ids
    try:
        yield
    finally:
        await shutdown_plugin_runtime_v2(test_app)


async def test_notification_crud_uses_generation_owned_service(
    authenticated_async_client: AsyncClient,
    db,
) -> None:
    create_response = await authenticated_async_client.post(
        "/api/v1/notifications/create",
        json={
            "title": "V2 notification",
            "message": "generation owned",
            "data": {"source": "integration"},
        },
    )
    assert create_response.status_code == status.HTTP_200_OK
    notification_id = create_response.json()["id"]

    list_response = await authenticated_async_client.get("/api/v1/notifications/")
    assert list_response.status_code == status.HTTP_200_OK
    assert notification_id in {
        notification["id"] for notification in list_response.json()["notifications"]
    }

    mark_response = await authenticated_async_client.put(
        f"/api/v1/notifications/{notification_id}/read"
    )
    assert mark_response.status_code == status.HTTP_200_OK
    db.expire_all()
    result = await db.execute(select(Notification).where(Notification.id == notification_id))
    assert result.scalar_one().is_read is True

    delete_response = await authenticated_async_client.delete(
        f"/api/v1/notifications/{notification_id}"
    )
    assert delete_response.status_code == status.HTTP_200_OK
    result = await db.execute(select(Notification).where(Notification.id == notification_id))
    assert result.scalar_one_or_none() is None
