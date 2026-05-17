"""Tests for HITL route hardening."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from src.domain.model.agent.hitl_request import HITLRequest, HITLRequestStatus, HITLRequestType
from src.infrastructure.adapters.primary.web.routers.agent import hitl as hitl_router
from src.infrastructure.adapters.primary.web.routers.agent.schemas import (
    HITLCancelRequest,
    HITLResponseRequest,
)


class FailingDb:
    async def execute(self, *_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("internal hitl db secret")


class MissingHITLRepo:
    get_by_id = AsyncMock(return_value=None)


def _hitl_request(*, status: HITLRequestStatus = HITLRequestStatus.PENDING) -> HITLRequest:
    return HITLRequest(
        id="hitl-secret",
        request_type=HITLRequestType.CLARIFICATION,
        conversation_id="conversation-secret",
        tenant_id="tenant-1",
        project_id="project-1",
        user_id="user-1",
        question="Continue?",
        status=status,
    )


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
async def test_load_authorized_pending_hitl_request_sanitizes_missing_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hitl_router, "SqlHITLRequestRepository", lambda _db: MissingHITLRepo())

    with pytest.raises(HTTPException) as exc_info:
        await hitl_router._load_authorized_pending_hitl_request(
            db=SimpleNamespace(),
            request_id="hitl-secret",
            user_id="user-1",
            tenant_id="tenant-1",
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "HITL request not found"
    assert "hitl-secret" not in exc_info.value.detail


@pytest.mark.unit
@pytest.mark.asyncio
async def test_load_authorized_pending_hitl_request_sanitizes_expired_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Repo:
        get_by_id = AsyncMock(return_value=_hitl_request())

    monkeypatch.setattr(hitl_router, "SqlHITLRequestRepository", lambda _db: Repo())
    monkeypatch.setattr(hitl_router, "_user_has_project_access", AsyncMock(return_value=True))
    monkeypatch.setattr(
        hitl_router,
        "_mark_hitl_timeout_if_expired",
        AsyncMock(return_value=True),
    )

    with pytest.raises(HTTPException) as exc_info:
        await hitl_router._load_authorized_pending_hitl_request(
            db=SimpleNamespace(),
            request_id="hitl-secret",
            user_id="user-1",
            tenant_id="tenant-1",
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "HITL request has expired"
    assert "hitl-secret" not in exc_info.value.detail


@pytest.mark.unit
@pytest.mark.asyncio
async def test_load_authorized_pending_hitl_request_sanitizes_non_pending_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Repo:
        get_by_id = AsyncMock(return_value=_hitl_request(status=HITLRequestStatus.ANSWERED))

    monkeypatch.setattr(hitl_router, "SqlHITLRequestRepository", lambda _db: Repo())
    monkeypatch.setattr(hitl_router, "_user_has_project_access", AsyncMock(return_value=True))
    monkeypatch.setattr(
        hitl_router,
        "_mark_hitl_timeout_if_expired",
        AsyncMock(return_value=False),
    )

    with pytest.raises(HTTPException) as exc_info:
        await hitl_router._load_authorized_pending_hitl_request(
            db=SimpleNamespace(),
            request_id="hitl-secret",
            user_id="user-1",
            tenant_id="tenant-1",
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "HITL request is no longer pending"
    assert "hitl-secret" not in exc_info.value.detail
    assert "answered" not in exc_info.value.detail


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
async def test_respond_to_hitl_sanitizes_invalid_type() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await hitl_router.respond_to_hitl(
            request=HITLResponseRequest(
                request_id="hitl-secret",
                hitl_type="secret_type",
                response_data={"answer": "yes"},
            ),
            current_user=SimpleNamespace(id="user-1"),
            tenant_id="tenant-1",
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid HITL type"
    assert "secret_type" not in exc_info.value.detail


@pytest.mark.unit
@pytest.mark.asyncio
async def test_respond_to_hitl_sanitizes_update_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Repo:
        update_response = AsyncMock(return_value=None)

    monkeypatch.setattr(hitl_router, "SqlHITLRequestRepository", lambda _db: Repo())
    monkeypatch.setattr(
        hitl_router,
        "_load_authorized_pending_hitl_request",
        AsyncMock(return_value=_hitl_request()),
    )
    monkeypatch.setattr(
        hitl_router,
        "_validate_and_summarize_hitl_response",
        lambda **_kwargs: ("clarification", "yes", {}),
    )

    with pytest.raises(HTTPException) as exc_info:
        await hitl_router.respond_to_hitl(
            request=HITLResponseRequest(
                request_id="hitl-secret",
                hitl_type="clarification",
                response_data={"answer": "yes"},
            ),
            current_user=SimpleNamespace(id="user-1"),
            tenant_id="tenant-1",
            db=SimpleNamespace(commit=AsyncMock()),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "HITL request could not be updated"
    assert "hitl-secret" not in exc_info.value.detail


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


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cancel_hitl_request_sanitizes_cancel_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Repo:
        mark_cancelled = AsyncMock(return_value=None)

    monkeypatch.setattr(hitl_router, "SqlHITLRequestRepository", lambda _db: Repo())
    monkeypatch.setattr(
        hitl_router,
        "_load_authorized_pending_hitl_request",
        AsyncMock(return_value=_hitl_request()),
    )

    with pytest.raises(HTTPException) as exc_info:
        await hitl_router.cancel_hitl_request(
            request=HITLCancelRequest(request_id="hitl-secret", reason="user cancelled"),
            current_user=SimpleNamespace(id="user-1"),
            tenant_id="tenant-1",
            db=SimpleNamespace(commit=AsyncMock()),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "HITL request could not be cancelled"
    assert "hitl-secret" not in exc_info.value.detail
