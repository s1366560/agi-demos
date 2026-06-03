"""Unit tests for audit router runtime hook query surfaces."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from src.domain.model.audit.audit_entry import AuditEntry
from src.infrastructure.adapters.primary.web.routers.audit import (
    export_audit_logs,
    get_runtime_hook_audit_summary,
    list_runtime_hook_audit_logs,
)


def _sample_audit_entry() -> AuditEntry:
    return AuditEntry(
        id="audit-1",
        timestamp=datetime.now(UTC),
        actor="system",
        action="runtime_hook.custom_execution_succeeded",
        resource_type="runtime_hook",
        resource_id="script:demo",
        tenant_id="tenant-1",
        details={
            "hook_name": "before_response",
            "executor_kind": "script",
            "hook_family": "mutating",
            "isolation_mode": "host",
        },
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_runtime_hook_audit_logs_returns_filtered_entries() -> None:
    service = MagicMock()
    service.list_runtime_hook_entries = AsyncMock(return_value=([_sample_audit_entry()], 1))

    with (
        patch(
            "src.infrastructure.adapters.primary.web.routers.audit.require_tenant_access",
            AsyncMock(),
        ),
        patch(
            "src.infrastructure.adapters.primary.web.routers.audit._build_service",
            return_value=service,
        ),
    ):
        response = await list_runtime_hook_audit_logs(
            tenant_id="tenant-1",
            current_user=MagicMock(),
            db=MagicMock(),
            hook_name="before_response",
            executor_kind="script",
            hook_family="mutating",
            isolation_mode="host",
            limit=25,
            offset=0,
        )

    assert response.total == 1
    assert response.items[0].details["executor_kind"] == "script"
    service.list_runtime_hook_entries.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_runtime_hook_audit_summary_returns_aggregate_counts() -> None:
    service = MagicMock()
    service.summarize_runtime_hook_entries = AsyncMock(
        return_value={
            "total": 2,
            "action_counts": {"runtime_hook.custom_execution_failed": 1},
            "executor_counts": {"script": 2},
            "family_counts": {"mutating": 2},
            "isolation_mode_counts": {"sandbox": 1, "host": 1},
            "latest_timestamp": datetime.now(UTC),
        }
    )

    with (
        patch(
            "src.infrastructure.adapters.primary.web.routers.audit.require_tenant_access",
            AsyncMock(),
        ),
        patch(
            "src.infrastructure.adapters.primary.web.routers.audit._build_service",
            return_value=service,
        ),
    ):
        response = await get_runtime_hook_audit_summary(
            tenant_id="tenant-1",
            current_user=MagicMock(),
            db=MagicMock(),
            executor_kind="script",
            isolation_mode="sandbox",
        )

    assert response.total == 2
    assert response.executor_counts["script"] == 2
    assert response.isolation_mode_counts["sandbox"] == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_export_audit_logs_uses_runtime_hook_filters() -> None:
    service = MagicMock()
    service.list_runtime_hook_entries = AsyncMock(return_value=([_sample_audit_entry()], 1))
    service.list_entries_filtered = AsyncMock()

    with (
        patch(
            "src.infrastructure.adapters.primary.web.routers.audit.require_tenant_access",
            AsyncMock(),
        ),
        patch(
            "src.infrastructure.adapters.primary.web.routers.audit._build_service",
            return_value=service,
        ),
    ):
        response = await export_audit_logs(
            tenant_id="tenant-1",
            current_user=MagicMock(),
            db=MagicMock(),
            export_format="json",
            action="runtime_hook.custom_execution_succeeded",
            hook_name="before_response",
            executor_kind="script",
            hook_family="mutating",
            isolation_mode="sandbox",
        )

    assert response.media_type == "application/json"
    service.list_runtime_hook_entries.assert_awaited_once_with(
        "tenant-1",
        action="runtime_hook.custom_execution_succeeded",
        hook_name="before_response",
        executor_kind="script",
        hook_family="mutating",
        isolation_mode="sandbox",
        limit=10_000,
        offset=0,
    )
    service.list_entries_filtered.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_export_audit_logs_uses_generic_filters() -> None:
    service = MagicMock()
    service.list_entries_filtered = AsyncMock(return_value=([_sample_audit_entry()], 1))
    service.list_runtime_hook_entries = AsyncMock()
    start_time = datetime(2026, 4, 15, tzinfo=UTC)
    end_time = datetime(2026, 4, 16, tzinfo=UTC)

    with (
        patch(
            "src.infrastructure.adapters.primary.web.routers.audit.require_tenant_access",
            AsyncMock(),
        ),
        patch(
            "src.infrastructure.adapters.primary.web.routers.audit._build_service",
            return_value=service,
        ),
    ):
        response = await export_audit_logs(
            tenant_id="tenant-1",
            current_user=MagicMock(),
            db=MagicMock(),
            export_format="csv",
            action="tenant.updated",
            resource_type="tenant",
            actor="system",
            hook_name=None,
            executor_kind=None,
            hook_family=None,
            isolation_mode=None,
            start_time=start_time,
            end_time=end_time,
        )

    assert response.media_type == "text/csv"
    service.list_entries_filtered.assert_awaited_once_with(
        "tenant-1",
        action="tenant.updated",
        resource_type="tenant",
        actor="system",
        start_time=start_time,
        end_time=end_time,
        limit=10_000,
        offset=0,
    )
    service.list_runtime_hook_entries.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_runtime_hook_audit_routes_require_tenant_access() -> None:
    with (
        patch(
            "src.infrastructure.adapters.primary.web.routers.audit.require_tenant_access",
            AsyncMock(side_effect=HTTPException(status_code=403, detail="forbidden")),
        ) as require_access,
        pytest.raises(HTTPException, match="forbidden") as exc_info,
    ):
        await list_runtime_hook_audit_logs(
            tenant_id="tenant-1",
            current_user=MagicMock(),
            db=MagicMock(),
        )

    assert exc_info.value.status_code == 403
    require_access.assert_awaited_once()
