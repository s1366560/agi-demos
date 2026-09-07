"""Unit tests for instance channel route authorization."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.routers import instance_channels
from src.infrastructure.adapters.primary.web.routers.instance_channels import (
    UpdateChannelRequest,
    _require_instance_access,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    InstanceModel,
    Project,
    User,
    UserTenant,
)
from src.infrastructure.adapters.secondary.persistence.sql_instance_repository import (
    SqlInstanceRepository,
)
from src.infrastructure.plugins.v2.instance_channel_services import (
    InstanceChannelAccessServiceV2,
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


def _access_authority(
    db: AsyncSession,
    current_user: User,
) -> SimpleNamespace:
    return SimpleNamespace(
        db=db,
        current_user=current_user,
        services=SimpleNamespace(
            access=InstanceChannelAccessServiceV2(
                instance_repository=SqlInstanceRepository(db),
            )
        ),
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

        await _require_instance_access(_access_authority(test_db, test_user), instance.id)

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
            await _require_instance_access(
                _access_authority(test_db, another_user),
                instance.id,
            )

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
                _access_authority(test_db, another_user),
                instance.id,
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
            await _require_instance_access(
                _access_authority(test_db, test_user),
                "missing-instance",
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


class _ChannelServiceStub:
    def __init__(self, message: str = "channel channel-secret not found") -> None:
        self.update_channel = AsyncMock(side_effect=ValueError(message))
        self.delete_channel = AsyncMock(side_effect=ValueError(message))
        self.test_connection = AsyncMock(side_effect=ValueError(message))


def _route_authority(service: _ChannelServiceStub) -> tuple[SimpleNamespace, SimpleNamespace]:
    db = SimpleNamespace(commit=AsyncMock())
    authority = SimpleNamespace(
        db=db,
        current_user=SimpleNamespace(id="user-1", is_superuser=True),
        services=SimpleNamespace(
            access=SimpleNamespace(
                tenant_id_for_instance=AsyncMock(return_value="tenant-1"),
            ),
            channels=service,
        ),
    )
    return authority, db


@pytest.mark.unit
class TestInstanceChannelErrorResponses:
    @pytest.mark.asyncio
    async def test_update_channel_sanitizes_missing_channel_id(
        self,
    ) -> None:
        service = _ChannelServiceStub()
        authority, db = _route_authority(service)

        with pytest.raises(HTTPException) as exc_info:
            await instance_channels.update_channel(
                instance_id="instance-1",
                channel_id="channel-secret",
                body=UpdateChannelRequest(name="New"),
                authority=authority,
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
        assert exc_info.value.detail == "Instance channel not found"
        assert "channel-secret" not in exc_info.value.detail
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_delete_channel_sanitizes_missing_channel_id(
        self,
    ) -> None:
        service = _ChannelServiceStub()
        authority, db = _route_authority(service)

        with pytest.raises(HTTPException) as exc_info:
            await instance_channels.delete_channel(
                instance_id="instance-1",
                channel_id="channel-secret",
                authority=authority,
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
        assert exc_info.value.detail == "Instance channel not found"
        assert "channel-secret" not in exc_info.value.detail
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_test_channel_connection_sanitizes_missing_channel_id(
        self,
    ) -> None:
        service = _ChannelServiceStub()
        authority, db = _route_authority(service)

        with pytest.raises(HTTPException) as exc_info:
            await instance_channels.test_channel_connection(
                instance_id="instance-1",
                channel_id="channel-secret",
                authority=authority,
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
        assert exc_info.value.detail == "Instance channel not found"
        assert "channel-secret" not in exc_info.value.detail
        db.commit.assert_not_awaited()
