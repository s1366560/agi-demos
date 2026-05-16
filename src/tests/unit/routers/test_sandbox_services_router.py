"""Unit tests for sandbox desktop and terminal service route hardening."""

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException, status

from src.infrastructure.adapters.primary.web.routers.sandbox import services as services_router
from src.infrastructure.adapters.primary.web.routers.sandbox.schemas import (
    DesktopStartRequest,
    TerminalStartRequest,
)


class FailingOrchestrator:
    async def start_desktop(self, sandbox_id: str, config: Any) -> Any:
        raise RuntimeError(f"internal desktop secret for {sandbox_id}")

    async def start_terminal(self, sandbox_id: str, config: Any) -> Any:
        raise RuntimeError(f"internal terminal secret for {sandbox_id}")


async def _allow_sandbox_access(**_kwargs: Any) -> tuple[SimpleNamespace, str]:
    return SimpleNamespace(project_id="project-1"), "project-1"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_start_desktop_sanitizes_internal_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(services_router, "assert_caller_owns_sandbox", _allow_sandbox_access)

    with pytest.raises(HTTPException) as exc_info:
        await services_router.start_desktop(
            sandbox_id="sandbox-secret",
            request=DesktopStartRequest(),
            current_user=SimpleNamespace(id="user-1", is_superuser=True),
            adapter=SimpleNamespace(),
            orchestrator=FailingOrchestrator(),
            event_publisher=None,
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert exc_info.value.detail == "Failed to start desktop"
    assert "internal" not in exc_info.value.detail
    assert "sandbox-secret" not in exc_info.value.detail


@pytest.mark.unit
@pytest.mark.asyncio
async def test_start_terminal_sanitizes_internal_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(services_router, "assert_caller_owns_sandbox", _allow_sandbox_access)

    with pytest.raises(HTTPException) as exc_info:
        await services_router.start_terminal(
            sandbox_id="sandbox-secret",
            request=TerminalStartRequest(),
            current_user=SimpleNamespace(id="user-1", is_superuser=True),
            adapter=SimpleNamespace(),
            orchestrator=FailingOrchestrator(),
            event_publisher=None,
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert exc_info.value.detail == "Failed to start terminal"
    assert "internal" not in exc_info.value.detail
    assert "sandbox-secret" not in exc_info.value.detail
