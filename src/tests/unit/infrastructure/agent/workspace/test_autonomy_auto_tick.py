"""Retirement contract for the retired platform Workspace autonomy scheduler."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from src.infrastructure.adapters.primary.web.routers import (
    workspace_leader_bootstrap as wlb,
)


@pytest.mark.unit
async def test_existing_root_execution_fails_closed_to_avernet_core() -> None:
    """Platform autonomy execution is retired; Core is the command authority."""
    with pytest.raises(HTTPException) as exc_info:
        await wlb.maybe_auto_trigger_existing_root_execution(
            db=MagicMock(),
            workspace_id="ws-1",
            current_user=SimpleNamespace(id="user-1"),
        )

    assert exc_info.value.status_code == 503


@pytest.mark.unit
def test_schedule_autonomy_tick_is_a_noop() -> None:
    """Obsolete post-commit ticks are ignored; the Core outbox schedules."""
    wlb.schedule_autonomy_tick("ws-1", "user-1")
