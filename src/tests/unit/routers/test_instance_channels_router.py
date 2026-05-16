"""Unit tests for instance channel route authorization."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.routers.instance_channels import (
    _require_instance_access,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    InstanceModel,
    Project,
    User,
    UserTenant,
)


def _make_instance(instance_id: str, tenant_id: str) -> InstanceModel:
    return InstanceModel(
        id=instance_id,
        name="Agent",
        slug=instance_id,
        tenant_id=tenant_id,
        created_by="test-user",
        created_at=datetime.now(UTC),
    )


@pytest.mark.unit
class TestInstanceChannelAuthorization:
    @pytest.mark.asyncio
    async def test_allows_tenant_member_to_read_channels(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        instance = _make_instance("instance-readable", test_project_db.tenant_id)
        test_db.add(instance)
        await test_db.commit()

        await _require_instance_access(instance.id, test_user, test_db)

    @pytest.mark.asyncio
    async def test_rejects_non_member(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        another_user: User,
    ) -> None:
        instance = _make_instance("instance-hidden", test_project_db.tenant_id)
        test_db.add(instance)
        await test_db.commit()

        with pytest.raises(HTTPException) as exc_info:
            await _require_instance_access(instance.id, another_user, test_db)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.asyncio
    async def test_rejects_non_admin_member_for_write(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        another_user: User,
    ) -> None:
        instance = _make_instance("instance-admin-required", test_project_db.tenant_id)
        test_db.add_all(
            [
                instance,
                UserTenant(
                    id=str(uuid4()),
                    user_id=another_user.id,
                    tenant_id=test_project_db.tenant_id,
                    role="member",
                    permissions={"read": True},
                ),
            ]
        )
        await test_db.commit()

        with pytest.raises(HTTPException) as exc_info:
            await _require_instance_access(
                instance.id,
                another_user,
                test_db,
                require_admin=True,
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.asyncio
    async def test_missing_instance_returns_404(
        self,
        test_db: AsyncSession,
        test_user: User,
    ) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await _require_instance_access("missing-instance", test_user, test_db)

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
