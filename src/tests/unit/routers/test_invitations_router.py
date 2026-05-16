"""Unit tests for tenant-scoped invitation route authorization."""

from uuid import uuid4

import pytest
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.invitation_schemas import CreateInvitationRequest
from src.infrastructure.adapters.primary.web.routers.invitations import (
    _require_invitation_admin,
    cancel_invitation,
    create_invitation,
    list_pending_invitations,
)
from src.infrastructure.adapters.secondary.persistence.models import Project, User, UserTenant


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
        test_db: AsyncSession,
        test_project_db: Project,
        another_user: User,
    ) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await create_invitation(
                test_project_db.tenant_id,
                CreateInvitationRequest(email="invitee@example.com", role="member"),
                another_user,
                test_db,
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.asyncio
    async def test_member_cannot_list_pending_invitations(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        another_user: User,
    ) -> None:
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
                another_user,
                test_db,
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.asyncio
    async def test_owner_can_list_pending_invitations(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        response = await list_pending_invitations(
            test_project_db.tenant_id,
            test_user,
            test_db,
            limit=50,
            offset=0,
        )

        assert response.items == []
        assert response.total == 0

    @pytest.mark.asyncio
    async def test_non_member_cannot_cancel_invitation(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        another_user: User,
    ) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await cancel_invitation(
                test_project_db.tenant_id,
                "missing-invitation",
                another_user,
                test_db,
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
