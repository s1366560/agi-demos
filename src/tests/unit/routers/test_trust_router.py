"""Unit tests for trust router error mapping."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.trust_schemas import ApprovalResolveRequest
from src.infrastructure.adapters.primary.web.routers import trust
from src.infrastructure.adapters.secondary.persistence.models import (
    DecisionRecordModel,
    Project,
    User,
    WorkspaceModel,
)


class _MissingApprovalService:
    async def resolve_approval(self, *_args: object, **_kwargs: object) -> object:
        raise ValueError("approval request approval-secret not found")


class _UnexpectedTrustService:
    async def list_policies(self, *_args: object, **_kwargs: object) -> object:
        raise AssertionError("service should not be called")


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


@pytest.mark.unit
async def test_list_trust_policies_rejects_workspace_from_other_tenant(
    monkeypatch: pytest.MonkeyPatch,
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    async def allow_access(*_args: object, **_kwargs: object) -> None:
        return None

    workspace = WorkspaceModel(
        id=str(uuid4()),
        tenant_id="tenant-other",
        project_id=test_project_db.id,
        name="Other tenant workspace",
        created_by=test_user.id,
    )
    test_db.add(workspace)
    await test_db.commit()

    monkeypatch.setattr(trust, "_require_tenant_access", allow_access)
    monkeypatch.setattr(trust, "_build_service", lambda _db: _UnexpectedTrustService())

    with pytest.raises(HTTPException) as exc_info:
        await trust.list_trust_policies(
            tenant_id=test_project_db.tenant_id,
            current_user=SimpleNamespace(id=test_user.id, is_superuser=False),
            db=test_db,
            workspace_id=workspace.id,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Workspace not found"


@pytest.mark.unit
async def test_get_decision_record_rejects_record_outside_requested_workspace(
    monkeypatch: pytest.MonkeyPatch,
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    async def allow_access(*_args: object, **_kwargs: object) -> None:
        return None

    workspace = WorkspaceModel(
        id=str(uuid4()),
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        name="Requested workspace",
        created_by=test_user.id,
    )
    record = DecisionRecordModel(
        id=str(uuid4()),
        tenant_id=test_project_db.tenant_id,
        workspace_id="other-workspace",
        agent_instance_id="agent-1",
        decision_type="tool_call",
        proposal={"tool": "shell"},
        outcome="pending",
    )
    test_db.add_all([workspace, record])
    await test_db.commit()

    monkeypatch.setattr(trust, "_require_tenant_access", allow_access)

    with pytest.raises(HTTPException) as exc_info:
        await trust.get_decision_record(
            tenant_id=test_project_db.tenant_id,
            record_id=record.id,
            current_user=SimpleNamespace(id=test_user.id, is_superuser=False),
            db=test_db,
            workspace_id=workspace.id,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Decision record not found"


@pytest.mark.unit
async def test_resolve_approval_request_rejects_record_from_other_tenant(
    monkeypatch: pytest.MonkeyPatch,
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    async def allow_access(*_args: object, **_kwargs: object) -> None:
        return None

    record = DecisionRecordModel(
        id=str(uuid4()),
        tenant_id="tenant-other",
        workspace_id="workspace-other",
        agent_instance_id="agent-1",
        decision_type="tool_call",
        proposal={"tool": "shell"},
        outcome="pending",
    )
    test_db.add(record)
    await test_db.commit()

    monkeypatch.setattr(trust, "_require_tenant_access", allow_access)

    with pytest.raises(HTTPException) as exc_info:
        await trust.resolve_approval_request(
            tenant_id=test_project_db.tenant_id,
            record_id=record.id,
            body=ApprovalResolveRequest(decision="allow_once"),
            current_user=SimpleNamespace(id=test_user.id, is_superuser=False),
            db=test_db,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Approval request not found"
    result = await test_db.execute(select(DecisionRecordModel).where(DecisionRecordModel.id == record.id))
    persisted = result.scalar_one()
    assert persisted.outcome == "pending"
    assert persisted.reviewer_id is None
