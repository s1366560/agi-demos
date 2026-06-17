from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.domain.model.tenant.event_log import EventLog
from src.infrastructure.adapters.primary.web.routers.events import (
    get_selected_event_tenant,
    list_event_types,
    list_events,
)


@pytest.mark.unit
async def test_get_selected_event_tenant_uses_default_without_explicit_scope() -> None:
    with patch(
        "src.infrastructure.adapters.primary.web.routers.events.require_tenant_access",
        AsyncMock(),
    ) as require_access:
        tenant_id = await get_selected_event_tenant(
            selected_tenant_id=None,
            fallback_tenant_id="tenant-default",
            current_user=MagicMock(),
            db=MagicMock(),
        )

    assert tenant_id == "tenant-default"
    require_access.assert_not_awaited()


@pytest.mark.unit
async def test_get_selected_event_tenant_validates_explicit_scope() -> None:
    db = MagicMock()
    current_user = MagicMock()
    with patch(
        "src.infrastructure.adapters.primary.web.routers.events.require_tenant_access",
        AsyncMock(),
    ) as require_access:
        tenant_id = await get_selected_event_tenant(
            selected_tenant_id="tenant-selected",
            fallback_tenant_id="tenant-default",
            current_user=current_user,
            db=db,
        )

    assert tenant_id == "tenant-selected"
    require_access.assert_awaited_once_with(db, current_user, "tenant-selected")


@pytest.mark.unit
async def test_list_events_uses_selected_tenant() -> None:
    service = MagicMock()
    service.list_events = AsyncMock(
        return_value=(
            [
                EventLog(
                    id="event-1",
                    tenant_id="tenant-selected",
                    event_type="gene.installed",
                    message="Gene installed",
                    source="gene-market",
                    metadata={},
                    created_at=datetime(2026, 1, 1, tzinfo=UTC),
                )
            ],
            1,
        )
    )

    response = await list_events(
        event_type="gene.installed",
        date_from=None,
        date_to=None,
        page=2,
        page_size=10,
        tenant_id="tenant-selected",
        service=service,
    )

    service.list_events.assert_awaited_once_with(
        tenant_id="tenant-selected",
        event_type="gene.installed",
        date_from=None,
        date_to=None,
        page=2,
        page_size=10,
    )
    assert response.total == 1
    assert response.items[0].tenant_id == "tenant-selected"


@pytest.mark.unit
async def test_list_event_types_uses_selected_tenant() -> None:
    service = MagicMock()
    service.get_event_types = AsyncMock(return_value=["gene.installed"])

    response = await list_event_types(tenant_id="tenant-selected", service=service)

    service.get_event_types.assert_awaited_once_with("tenant-selected")
    assert response == ["gene.installed"]
