"""Tests for HITL route hardening."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from src.infrastructure.adapters.primary.web.routers.agent import hitl as hitl_router
from src.infrastructure.adapters.primary.web.routers.agent.schemas import (
    HITLCancelRequest,
    HITLResponseRequest,
)


class FailingDb:
    async def execute(self, *_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("internal hitl db secret")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_pending_hitl_requests_sanitizes_internal_errors() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await hitl_router.get_pending_hitl_requests(
            conversation_id="conversation-1",
            current_user=SimpleNamespace(id="user-1"),
            tenant_id="tenant-1",
            db=FailingDb(),
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Failed to get pending HITL requests"
    assert "internal" not in exc_info.value.detail


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_project_pending_hitl_requests_sanitizes_internal_errors() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await hitl_router.get_project_pending_hitl_requests(
            project_id="project-1",
            current_user=SimpleNamespace(id="user-1"),
            tenant_id="tenant-1",
            db=FailingDb(),
            limit=50,
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Failed to get pending HITL requests"
    assert "internal" not in exc_info.value.detail


@pytest.mark.unit
@pytest.mark.asyncio
async def test_respond_to_hitl_sanitizes_internal_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        hitl_router,
        "_load_authorized_pending_hitl_request",
        AsyncMock(side_effect=RuntimeError("internal hitl load secret")),
    )

    with pytest.raises(HTTPException) as exc_info:
        await hitl_router.respond_to_hitl(
            request=HITLResponseRequest(
                request_id="hitl-1",
                hitl_type="clarification",
                response_data={"answer": "yes"},
            ),
            current_user=SimpleNamespace(id="user-1"),
            tenant_id="tenant-1",
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Failed to respond to HITL request"
    assert "internal" not in exc_info.value.detail


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cancel_hitl_request_sanitizes_internal_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        hitl_router,
        "_load_authorized_pending_hitl_request",
        AsyncMock(side_effect=RuntimeError("internal hitl cancel secret")),
    )

    with pytest.raises(HTTPException) as exc_info:
        await hitl_router.cancel_hitl_request(
            request=HITLCancelRequest(request_id="hitl-1", reason="user cancelled"),
            current_user=SimpleNamespace(id="user-1"),
            tenant_id="tenant-1",
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Failed to cancel HITL request"
    assert "internal" not in exc_info.value.detail
