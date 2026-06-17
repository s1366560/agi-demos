from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.tenant.event_log import EventLog
from src.infrastructure.adapters.secondary.persistence.sql_event_log_repository import (
    SqlEventLogRepository,
)


class _CountResult:
    def scalar_one(self) -> int:
        return 0


class _ScalarRows:
    def all(self) -> list[Any]:
        return []


class _FetchResult:
    def scalars(self) -> _ScalarRows:
        return _ScalarRows()


class _RecordingSession:
    def __init__(self) -> None:
        self.statements: list[Any] = []

    async def execute(self, statement: Any) -> _CountResult | _FetchResult:
        self.statements.append(statement)
        if len(self.statements) == 1:
            return _CountResult()
        return _FetchResult()


def _event_log(
    *,
    event_id: str,
    tenant_id: str = "tenant-1",
    event_type: str = "gene.installed",
    created_at: datetime,
) -> EventLog:
    return EventLog(
        id=event_id,
        tenant_id=tenant_id,
        event_type=event_type,
        message=f"Event {event_id}",
        source="system",
        created_at=created_at,
    )


@pytest.mark.unit
async def test_find_by_tenant_declares_deterministic_order_by() -> None:
    session = _RecordingSession()
    repo = SqlEventLogRepository(cast(AsyncSession, session))

    await repo.find_by_tenant("tenant-1")

    fetch_statement = str(session.statements[-1])
    assert "ORDER BY tenant_event_logs.created_at DESC, tenant_event_logs.id ASC" in fetch_statement


@pytest.mark.unit
async def test_find_by_tenant_orders_events_by_newest_then_id(test_db: AsyncSession) -> None:
    repo = SqlEventLogRepository(test_db)
    base_time = datetime(2026, 1, 1, tzinfo=UTC)

    for event in [
        _event_log(event_id="tie-b", created_at=base_time + timedelta(minutes=1)),
        _event_log(event_id="oldest", created_at=base_time),
        _event_log(event_id="other-tenant", tenant_id="tenant-2", created_at=base_time),
        _event_log(event_id="newest", created_at=base_time + timedelta(minutes=2)),
        _event_log(event_id="tie-a", created_at=base_time + timedelta(minutes=1)),
    ]:
        await repo.save(event)
    await test_db.flush()

    first_page, total = await repo.find_by_tenant("tenant-1", page=1, page_size=4)
    second_page, _ = await repo.find_by_tenant("tenant-1", page=2, page_size=2)

    assert total == 4
    assert [event.id for event in first_page] == ["newest", "tie-a", "tie-b", "oldest"]
    assert [event.id for event in second_page] == ["tie-b", "oldest"]
