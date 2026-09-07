"""Unit tests for tenant-scoped invitation route authorization."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src.application.schemas.invitation_schemas import (
    AcceptInvitationRequest,
    CreateInvitationRequest,
)
from src.domain.model.invitation.invitation import Invitation
from src.infrastructure.adapters.primary.web.routers import invitations as router
from src.infrastructure.adapters.primary.web.routers.invitations import (
    _require_invitation_admin,
    accept_invitation,
    cancel_invitation,
    create_invitation,
    list_pending_invitations,
)
from src.infrastructure.adapters.secondary.persistence.models import Project, User, UserTenant


def _request(*, method: str, path: str) -> Request:
    return Request(
        {
            "type": "http",
            "app": FastAPI(),
            "headers": [],
            "method": method,
            "path": path,
            "path_params": {},
            "query_string": b"",
            "scheme": "http",
            "server": ("test", 80),
        }
    )


def _install_fake_authority(
    monkeypatch: pytest.MonkeyPatch,
    *,
    service: object,
) -> None:
    @asynccontextmanager
    async def authority_context(**kwargs: object):
        yield SimpleNamespace(
            db=kwargs["db"],
            current_user=kwargs["current_user"],
            services=SimpleNamespace(
                invitations=service,
                memberships=SimpleNamespace(ensure_membership=AsyncMock()),
            ),
        )

    monkeypatch.setattr(
        router,
        "invitation_application_authority_context_v2",
        authority_context,
    )


@pytest.mark.unit
class TestInvitationsRouterAuthorization:
    @pytest.mark.asyncio
    async def test_superuser_bypasses_membership_lookup(
        self,
        test_db: AsyncSession,
        another_user: User,
    ) -> None:
        another_user.is_superuser = True

        await _require_invitation_admin(test_db, another_user, "tenant-without-row")

    @pytest.mark.asyncio
    async def test_non_member_cannot_create_invitation(
        self,
        monkeypatch: pytest.MonkeyPatch,
        test_db: AsyncSession,
        test_project_db: Project,
        another_user: User,
    ) -> None:
        _install_fake_authority(monkeypatch, service=_InvitationService())
        with pytest.raises(HTTPException) as exc_info:
            await create_invitation(
                test_project_db.tenant_id,
                CreateInvitationRequest(email="invitee@example.com", role="member"),
                _request(
                    method="POST",
                    path=f"/api/v1/tenants/{test_project_db.tenant_id}/invitations",
                ),
                another_user,
                test_db,
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


class _InvitationService:
    async def create_invitation(self, **_kwargs: object) -> Invitation:
        raise ValueError("A pending invitation already exists for secret@example.com")

    async def cancel(self, invitation_id: str, tenant_id: str) -> None:
        if tenant_id == "tenant-forbidden":
            raise PermissionError("Not authorized to cancel invitation invitation-secret")
        raise ValueError(f"Invitation {invitation_id} not found")

    async def list_pending(
        self,
        _tenant_id: str,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[Invitation], int]:
        assert limit >= 1
        assert offset >= 0
        return [], 0

    async def accept_invitation(self, token: str, user_id: str) -> Invitation:
        if token == "valid-token":
            return Invitation(
                id="invitation-accepted",
                tenant_id="tenant-1",
                email="invitee@example.com",
                role="member",
                token=token,
                status="accepted",
                invited_by="owner-1",
                accepted_by=user_id,
                expires_at=datetime.now(UTC) + timedelta(days=1),
                created_at=datetime.now(UTC),
            )
        raise ValueError(f"Invalid or expired invitation token: {token}")


@pytest.mark.unit
async def test_create_invitation_sanitizes_duplicate_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def allow_admin(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(router, "_require_invitation_admin", allow_admin)
    _install_fake_authority(monkeypatch, service=_InvitationService())

    with pytest.raises(HTTPException) as exc_info:
        await create_invitation(
            tenant_id="tenant-1",
            body=CreateInvitationRequest(email="secret@example.com", role="member"),
            request=_request(method="POST", path="/api/v1/tenants/tenant-1/invitations"),
            current_user=SimpleNamespace(id="owner-1"),
            db=SimpleNamespace(commit=AsyncMock()),
        )

    assert exc_info.value.status_code == status.HTTP_409_CONFLICT
    assert exc_info.value.detail == "Invitation already exists"
    assert "secret@example.com" not in exc_info.value.detail


@pytest.mark.unit
@pytest.mark.parametrize(
    ("tenant_id", "expected_status", "expected_detail"),
    [
        ("tenant-1", status.HTTP_404_NOT_FOUND, "Invitation not found"),
        (
            "tenant-forbidden",
            status.HTTP_403_FORBIDDEN,
            "Not authorized to manage this invitation",
        ),
    ],
)
async def test_cancel_invitation_sanitizes_service_errors(
    tenant_id: str,
    expected_status: int,
    expected_detail: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def allow_admin(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(router, "_require_invitation_admin", allow_admin)
    _install_fake_authority(monkeypatch, service=_InvitationService())

    with pytest.raises(HTTPException) as exc_info:
        await cancel_invitation(
            tenant_id=tenant_id,
            invitation_id="invitation-secret",
            request=_request(
                method="DELETE",
                path=f"/api/v1/tenants/{tenant_id}/invitations/invitation-secret",
            ),
            current_user=SimpleNamespace(id="owner-1"),
            db=SimpleNamespace(commit=AsyncMock()),
        )

    assert exc_info.value.status_code == expected_status
    assert exc_info.value.detail == expected_detail
    assert "secret" not in exc_info.value.detail


@pytest.mark.unit
async def test_accept_invitation_sanitizes_invalid_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_authority(monkeypatch, service=_InvitationService())

    with pytest.raises(HTTPException) as exc_info:
        await accept_invitation(
            token="token-secret",
            body=AcceptInvitationRequest(),
            request=_request(method="POST", path="/api/v1/invitations/accept/token-secret"),
            current_user=SimpleNamespace(id="user-1"),
            db=SimpleNamespace(commit=AsyncMock()),
        )

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert exc_info.value.detail == "Invalid or expired invitation"
    assert "secret" not in exc_info.value.detail


@pytest.mark.unit
async def test_member_cannot_list_pending_invitations(
    monkeypatch: pytest.MonkeyPatch,
    test_db: AsyncSession,
    test_project_db: Project,
    another_user: User,
) -> None:
    _install_fake_authority(monkeypatch, service=_InvitationService())
    test_db.add(
        UserTenant(
            id=str(uuid4()),
            user_id=another_user.id,
            tenant_id=test_project_db.tenant_id,
            role="member",
            permissions={"read": True},
        )
    )
    await test_db.commit()

    with pytest.raises(HTTPException) as exc_info:
        await list_pending_invitations(
            test_project_db.tenant_id,
            _request(
                method="GET",
                path=f"/api/v1/tenants/{test_project_db.tenant_id}/invitations",
            ),
            another_user,
            test_db,
        )

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.unit
async def test_owner_can_list_pending_invitations(
    monkeypatch: pytest.MonkeyPatch,
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    _install_fake_authority(monkeypatch, service=_InvitationService())
    response = await list_pending_invitations(
        test_project_db.tenant_id,
        _request(
            method="GET",
            path=f"/api/v1/tenants/{test_project_db.tenant_id}/invitations",
        ),
        test_user,
        test_db,
        limit=50,
        offset=0,
    )

    assert response.items == []
    assert response.total == 0


@pytest.mark.unit
async def test_non_member_cannot_cancel_invitation(
    monkeypatch: pytest.MonkeyPatch,
    test_db: AsyncSession,
    test_project_db: Project,
    another_user: User,
) -> None:
    _install_fake_authority(monkeypatch, service=_InvitationService())
    with pytest.raises(HTTPException) as exc_info:
        await cancel_invitation(
            test_project_db.tenant_id,
            "missing-invitation",
            _request(
                method="DELETE",
                path=(
                    f"/api/v1/tenants/{test_project_db.tenant_id}/invitations/missing-invitation"
                ),
            ),
            another_user,
            test_db,
        )

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
