"""Contracts for the retired platform Workspace autonomy scheduler surface."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.routers import workspace_leader_bootstrap as bootstrap
from src.infrastructure.adapters.secondary.persistence.models import User


@pytest.mark.unit
async def test_autonomy_compatibility_call_fails_closed_for_workspace_core() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await bootstrap.maybe_auto_trigger_existing_root_execution(
            db=cast(AsyncSession, SimpleNamespace()),
            workspace_id="core-authoritative-workspace",
            current_user=cast(User, SimpleNamespace(id="user-1")),
            request=cast(Request, SimpleNamespace()),
            force=True,
            system_tick=True,
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == {
        "code": "WORKSPACE_CORE_UNAVAILABLE",
        "reason": "workspace_core_unavailable",
        "detail": "Workspace Core is unavailable",
    }


@pytest.mark.unit
def test_obsolete_autonomy_tick_scheduler_is_a_noop() -> None:
    assert bootstrap.schedule_autonomy_tick("workspace-1", "actor-1") is None


@pytest.mark.unit
def test_autonomy_compatibility_module_exports_only_core_owned_surfaces() -> None:
    assert bootstrap.__all__ == [
        "maybe_auto_trigger_existing_root_execution",
        "schedule_autonomy_tick",
    ]
