"""Tests for SQL audit repository tenant scoping."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.models import AuditLog
from src.infrastructure.adapters.secondary.persistence.sql_audit_repository import (
    SqlAuditRepository,
)


def _audit_log(
    entry_id: str,
    *,
    tenant_id: str | None,
    action: str = "runtime_hook.custom_execution_succeeded",
    timestamp: datetime | None = None,
) -> AuditLog:
    return AuditLog(
        id=entry_id,
        timestamp=timestamp or datetime.now(UTC),
        actor="system",
        action=action,
        resource_type="runtime_hook",
        resource_id="script:demo",
        tenant_id=tenant_id,
        details={
            "hook_name": "before_response",
            "executor_kind": "script",
            "hook_family": "mutating",
            "isolation_mode": "host",
        },
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_find_by_tenant_includes_legacy_global_audit_rows(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    db_session.add_all(
        [
            _audit_log("audit-tenant", tenant_id="tenant-1", timestamp=now),
            _audit_log("audit-global", tenant_id=None, timestamp=now - timedelta(seconds=1)),
            _audit_log("audit-other", tenant_id="tenant-2", timestamp=now - timedelta(seconds=2)),
        ]
    )
    await db_session.flush()

    repo = SqlAuditRepository(db_session)
    items = await repo.find_by_tenant("tenant-1", limit=10, offset=0)
    total = await repo.count_by_tenant("tenant-1")

    assert [item.id for item in items] == ["audit-tenant", "audit-global"]
    assert total == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_filtered_runtime_hook_queries_include_legacy_global_audit_rows(
    db_session: AsyncSession,
) -> None:
    db_session.add_all(
        [
            _audit_log("audit-global-match", tenant_id=None),
            _audit_log(
                "audit-global-other-action",
                tenant_id=None,
                action="runtime_hook.custom_execution_failed",
            ),
            _audit_log("audit-other-tenant", tenant_id="tenant-2"),
        ]
    )
    await db_session.flush()

    repo = SqlAuditRepository(db_session)
    items = await repo.find_by_tenant_filtered(
        "tenant-1",
        action="runtime_hook.custom_execution_succeeded",
        action_prefix="runtime_hook.",
        resource_type="runtime_hook",
        detail_filters={"hook_name": "before_response", "executor_kind": "script"},
        limit=10,
        offset=0,
    )
    total = await repo.count_by_tenant_filtered(
        "tenant-1",
        action="runtime_hook.custom_execution_succeeded",
        action_prefix="runtime_hook.",
        resource_type="runtime_hook",
        detail_filters={"hook_name": "before_response", "executor_kind": "script"},
    )

    assert [item.id for item in items] == ["audit-global-match"]
    assert total == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_summary_includes_legacy_global_audit_rows(db_session: AsyncSession) -> None:
    db_session.add_all(
        [
            _audit_log("audit-global-started", tenant_id=None, action="runtime_hook.started"),
            _audit_log("audit-global-succeeded", tenant_id=None),
            _audit_log("audit-other-tenant", tenant_id="tenant-2"),
        ]
    )
    await db_session.flush()

    repo = SqlAuditRepository(db_session)
    summary = await repo.summarize_by_tenant_filtered(
        "tenant-1",
        action_prefix="runtime_hook.",
        resource_type="runtime_hook",
        detail_filters={"hook_name": "before_response"},
    )

    assert summary["total"] == 2
    assert summary["action_counts"] == {
        "runtime_hook.started": 1,
        "runtime_hook.custom_execution_succeeded": 1,
    }
