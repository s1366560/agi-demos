"""Unit tests for workspace autonomy route error mapping."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from src.infrastructure.adapters.primary.web.routers import workspace_autonomy


@pytest.mark.unit
async def test_autonomy_tick_sanitizes_permission_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail_tick(**_kwargs: Any) -> dict[str, Any]:
        raise PermissionError("workspace autonomy secret denied")

    monkeypatch.setattr(
        workspace_autonomy,
        "maybe_auto_trigger_existing_root_execution",
        fail_tick,
    )

    with pytest.raises(HTTPException) as exc_info:
        await workspace_autonomy.trigger_workspace_autonomy_tick(
            workspace_id="workspace-secret",
            request=SimpleNamespace(),
            payload=None,
            current_user=SimpleNamespace(id="user-1"),
            db=SimpleNamespace(rollback=AsyncMock()),
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Access denied"
    assert "secret" not in str(exc_info.value.detail)


@pytest.mark.unit
async def test_autonomy_tick_sanitizes_not_found_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail_tick(**_kwargs: Any) -> dict[str, Any]:
        raise ValueError("workspace workspace-secret not found")

    monkeypatch.setattr(
        workspace_autonomy,
        "maybe_auto_trigger_existing_root_execution",
        fail_tick,
    )

    with pytest.raises(HTTPException) as exc_info:
        await workspace_autonomy.trigger_workspace_autonomy_tick(
            workspace_id="workspace-secret",
            request=SimpleNamespace(),
            payload=None,
            current_user=SimpleNamespace(id="user-1"),
            db=SimpleNamespace(rollback=AsyncMock()),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Workspace not found"
    assert "workspace-secret" not in str(exc_info.value.detail)
