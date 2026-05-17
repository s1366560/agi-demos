"""Unit tests for trust router error mapping."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from src.application.schemas.trust_schemas import ApprovalResolveRequest
from src.infrastructure.adapters.primary.web.routers import trust


class _MissingApprovalService:
    async def resolve_approval(self, *_args: object, **_kwargs: object) -> object:
        raise ValueError("approval request approval-secret not found")


@pytest.mark.unit
async def test_resolve_approval_request_sanitizes_missing_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def allow_access(*_args: object, **_kwargs: object) -> None:
        return None

    db = SimpleNamespace(commit=AsyncMock())
    monkeypatch.setattr(trust, "_require_tenant_access", allow_access)
    monkeypatch.setattr(trust, "_build_service", lambda _db: _MissingApprovalService())

    with pytest.raises(HTTPException) as exc_info:
        await trust.resolve_approval_request(
            tenant_id="tenant-1",
            record_id="approval-secret",
            body=ApprovalResolveRequest(decision="approved"),
            current_user=SimpleNamespace(id="user-1"),
            db=db,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Approval request not found"
    assert "approval-secret" not in str(exc_info.value.detail)
    db.commit.assert_not_awaited()
