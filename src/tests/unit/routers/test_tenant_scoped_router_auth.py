"""Unit tests for shared tenant authorization wrappers in tenant-scoped routers."""

from uuid import uuid4

import pytest
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.routers.smtp_config import (
    _require_tenant_access as require_smtp_tenant_access,
)
from src.infrastructure.adapters.primary.web.routers.trust import (
    _require_tenant_access as require_trust_tenant_access,
)
from src.infrastructure.adapters.secondary.persistence.models import Project, User, UserTenant


@pytest.mark.unit
class TestTenantScopedRouterAuthorization:
    @pytest.mark.asyncio
    async def test_superuser_bypasses_membership_lookup(
        self,
        test_db: AsyncSession,
        another_user: User,
    ) -> None:
        another_user.is_superuser = True

        await require_smtp_tenant_access(test_db, another_user, "tenant-without-row")

    @pytest.mark.asyncio
    async def test_non_member_is_rejected(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        another_user: User,
    ) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await require_smtp_tenant_access(test_db, another_user, test_project_db.tenant_id)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.asyncio
    async def test_tenant_member_can_read_trust_routes(
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

        await require_trust_tenant_access(test_db, another_user, test_project_db.tenant_id)

    @pytest.mark.asyncio
    async def test_tenant_member_cannot_use_trust_admin_routes(
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
            await require_trust_tenant_access(
                test_db,
                another_user,
                test_project_db.tenant_id,
                require_admin=True,
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
