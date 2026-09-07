"""Active deadline reconciliation lifecycle for plugin protocol v2."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.platform_plugin_deadline_reconciler_v2 import (
    PlatformPluginDeadlineReconcilerV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginRepositoryV2,
)

pytestmark = pytest.mark.unit


@asynccontextmanager
async def _session_factory(session: AsyncSession) -> AsyncIterator[AsyncSession]:
    yield session


async def test_deadline_reconciler_uses_fresh_transaction_and_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock(spec=AsyncSession)
    observed: dict[str, object] = {}
    now = datetime(2026, 8, 30, 4, 30, tzinfo=UTC)

    async def reconcile(
        _repository: PlatformPluginRepositoryV2,
        *,
        now: datetime | None = None,
        limit: int = 100,
    ) -> int:
        observed.update(now=now, limit=limit)
        return 2

    monkeypatch.setattr(PlatformPluginRepositoryV2, "reconcile_publication_deadlines", reconcile)
    worker = PlatformPluginDeadlineReconcilerV2(
        session_factory=lambda: _session_factory(session),
        clock=lambda: now,
        batch_size=7,
    )

    assert await worker.run_once() == 2
    assert observed == {"now": now, "limit": 7}
    session.commit.assert_awaited_once()


async def test_deadline_reconciler_start_is_idempotent_and_stop_drains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock(spec=AsyncSession)
    swept = asyncio.Event()

    async def reconcile(
        _repository: PlatformPluginRepositoryV2,
        *,
        now: datetime | None = None,
        limit: int = 100,
    ) -> int:
        _ = (now, limit)
        swept.set()
        return 0

    monkeypatch.setattr(PlatformPluginRepositoryV2, "reconcile_publication_deadlines", reconcile)
    worker = PlatformPluginDeadlineReconcilerV2(
        session_factory=lambda: _session_factory(session),
        poll_interval_seconds=60,
    )

    worker.start()
    worker.start()
    await asyncio.wait_for(swept.wait(), timeout=1)
    assert worker.is_running is True

    await worker.stop()

    assert worker.is_running is False
    session.commit.assert_awaited_once()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    (
        ({"batch_size": 0}, "batch size"),
        ({"poll_interval_seconds": 0}, "poll interval"),
    ),
)
def test_deadline_reconciler_rejects_invalid_schedule(
    kwargs: dict[str, object],
    message: str,
) -> None:
    session = AsyncMock(spec=AsyncSession)
    with pytest.raises(ValueError, match=message):
        PlatformPluginDeadlineReconcilerV2(
            session_factory=lambda: _session_factory(session),
            **kwargs,
        )
