"""Unit tests for instance route audit fields."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.instance_schemas import (
    InstanceMemberCreate,
    InstanceMemberUpdate,
    InstanceUpdate,
)
from src.domain.model.instance.enums import InstanceRole, InstanceStatus, ServiceType
from src.domain.model.instance.instance import Instance, InstanceMember
from src.infrastructure.adapters.primary.web.routers import instances as instances_router
from src.infrastructure.adapters.primary.web.routers.instances import (
    PendingConfigRequest,
    ScaleRequest,
    _get_owned_instance_or_404,
    add_member,
    apply_pending_config,
    delete_instance,
    list_members,
    remove_member,
    restart_instance,
    save_pending_config,
    scale_instance,
    update_instance,
    update_member_role,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    DeployRecordModel,
    InstanceMemberModel,
    InstanceModel,
    Project,
    User,
)


@pytest.fixture
async def managed_instance(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> InstanceModel:
    instance = InstanceModel(
        id=str(uuid4()),
        name="Managed Instance",
        slug="managed-instance",
        tenant_id=test_project_db.tenant_id,
        service_type="ClusterIP",
        status="running",
        created_by=test_user.id,
    )
    test_db.add(instance)
    await test_db.commit()
    await test_db.refresh(instance)
    return instance


def _request() -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(container=SimpleNamespace(graph_service=None, redis_client=None))
        )
    )


async def _latest_deploy(test_db: AsyncSession, instance_id: str) -> DeployRecordModel:
    result = await test_db.execute(
        select(DeployRecordModel)
        .where(DeployRecordModel.instance_id == instance_id)
        .order_by(DeployRecordModel.created_at.desc())
        .limit(1)
    )
    deploy = result.scalar_one()
    return deploy


@pytest.mark.unit
class TestInstanceRouterAuditFields:
    @pytest.mark.asyncio
    async def test_scale_records_authenticated_user_as_trigger(
        self,
        test_db: AsyncSession,
        managed_instance: InstanceModel,
        test_user: User,
    ) -> None:
        await scale_instance(
            _request(),
            managed_instance.id,
            ScaleRequest(desired_replicas=3),
            tenant_id=managed_instance.tenant_id,
            current_user=test_user,
            db=test_db,
        )

        deploy = await _latest_deploy(test_db, managed_instance.id)
        assert deploy.triggered_by == test_user.id


@pytest.mark.unit
async def test_list_members_returns_paginated_active_members(
    test_db: AsyncSession,
    managed_instance: InstanceModel,
) -> None:
    users = [
        User(
            id=f"instance-member-user-{index}",
            email=f"instance-member-{index}@example.com",
            hashed_password="hash",
            full_name=f"Instance Member {index}",
        )
        for index in range(4)
    ]
    now = datetime.now(UTC)
    members = [
        InstanceMemberModel(
            id=f"instance-member-row-{index}",
            instance_id=managed_instance.id,
            user_id=users[index].id,
            role="viewer",
            created_at=now,
            deleted_at=now if index == 3 else None,
        )
        for index in range(4)
    ]
    test_db.add_all([*users, *members])
    await test_db.commit()

    response = await list_members(
        _request(),
        managed_instance.id,
        limit=2,
        offset=0,
        tenant_id=managed_instance.tenant_id,
        db=test_db,
    )

    assert response.total == 3
    assert response.limit == 2
    assert response.offset == 0
    assert response.has_more is True
    assert [member.user_email for member in response.members] == [
        "instance-member-0@example.com",
        "instance-member-1@example.com",
    ]


class _FailingInstanceService:
    async def get_instance(self, _instance_id: str) -> Instance:
        return Instance(
            id="instance-secret",
            name="Instance",
            slug="instance",
            tenant_id="tenant-1",
            service_type=ServiceType.cluster_ip,
            status=InstanceStatus.running,
            created_at=datetime.now(UTC),
        )

    async def update_instance(self, *_args: object, **_kwargs: object) -> object:
        raise ValueError("Instance instance-secret not found")

    async def delete_instance(self, _instance_id: str) -> None:
        raise ValueError("Instance instance-secret not found")

    async def scale_instance(self, **_kwargs: object) -> object:
        raise ValueError("Instance instance-secret not found")

    async def restart_instance(self, **_kwargs: object) -> object:
        raise ValueError("Instance instance-secret not found")

    async def save_pending_config(self, **_kwargs: object) -> object:
        raise ValueError("Instance instance-secret not found")

    async def apply_pending_config(self, **_kwargs: object) -> object:
        raise ValueError("Instance instance-secret has no pending config")

    async def add_member(self, **_kwargs: object) -> object:
        raise ValueError("User user-secret is already a member of instance instance-secret")

    async def update_member_role(self, **_kwargs: object) -> object:
        raise ValueError("Member member-secret not found in instance instance-secret")

    async def remove_member(self, **_kwargs: object) -> None:
        raise ValueError("User user-secret is not a member of instance instance-secret")

    async def list_members(
        self,
        _instance_id: str,
        *_args: object,
        **_kwargs: object,
    ) -> tuple[list[InstanceMember], int]:
        raise ValueError("Instance instance-secret not found")


class _Container:
    def __init__(self) -> None:
        self.service = _FailingInstanceService()

    def instance_service(self) -> _FailingInstanceService:
        return self.service


@pytest.mark.unit
async def test_get_owned_instance_sanitizes_missing_instance() -> None:
    service = SimpleNamespace(get_instance=AsyncMock(return_value=None))

    with pytest.raises(HTTPException) as exc_info:
        await _get_owned_instance_or_404(
            service=service,
            instance_id="instance-secret",
            tenant_id="tenant-1",
        )

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc_info.value.detail == "Instance not found"
    assert "secret" not in exc_info.value.detail


@pytest.mark.unit
@pytest.mark.parametrize(
    ("call", "call_args", "expected_status", "expected_detail"),
    [
        (
            update_instance,
            {
                "instance_id": "instance-secret",
                "data": InstanceUpdate(name="Updated"),
            },
            status.HTTP_404_NOT_FOUND,
            "Instance operation failed",
        ),
        (
            delete_instance,
            {"instance_id": "instance-secret"},
            status.HTTP_404_NOT_FOUND,
            "Instance operation failed",
        ),
        (
            scale_instance,
            {
                "instance_id": "instance-secret",
                "data": ScaleRequest(desired_replicas=2),
                "current_user": SimpleNamespace(id="user-current"),
            },
            status.HTTP_404_NOT_FOUND,
            "Instance operation failed",
        ),
        (
            restart_instance,
            {
                "instance_id": "instance-secret",
                "current_user": SimpleNamespace(id="user-current"),
            },
            status.HTTP_404_NOT_FOUND,
            "Instance operation failed",
        ),
        (
            save_pending_config,
            {
                "instance_id": "instance-secret",
                "data": PendingConfigRequest(pending_config={"image_version": "2.0.0"}),
            },
            status.HTTP_404_NOT_FOUND,
            "Instance operation failed",
        ),
        (
            apply_pending_config,
            {
                "instance_id": "instance-secret",
                "current_user": SimpleNamespace(id="user-current"),
            },
            status.HTTP_404_NOT_FOUND,
            "Instance operation failed",
        ),
        (
            add_member,
            {
                "instance_id": "instance-secret",
                "data": InstanceMemberCreate(
                    instance_id="instance-secret",
                    user_id="user-secret",
                    role=InstanceRole.viewer.value,
                ),
            },
            status.HTTP_400_BAD_REQUEST,
            "Invalid instance member request",
        ),
        (
            update_member_role,
            {
                "instance_id": "instance-secret",
                "member_id": "member-secret",
                "data": InstanceMemberUpdate(role=InstanceRole.editor.value),
            },
            status.HTTP_404_NOT_FOUND,
            "Instance member not found",
        ),
        (
            remove_member,
            {"instance_id": "instance-secret", "user_id": "user-secret"},
            status.HTTP_404_NOT_FOUND,
            "Instance member not found",
        ),
        (
            list_members,
            {"instance_id": "instance-secret"},
            status.HTTP_404_NOT_FOUND,
            "Instance member not found",
        ),
    ],
)
async def test_instance_routes_sanitize_service_value_errors(
    call: object,
    call_args: dict[str, object],
    expected_status: int,
    expected_detail: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(instances_router, "get_container_with_db", lambda *_args: _Container())

    with pytest.raises(HTTPException) as exc_info:
        await call(
            request=SimpleNamespace(),
            tenant_id="tenant-1",
            db=SimpleNamespace(commit=AsyncMock(), execute=AsyncMock()),
            **call_args,
        )

    assert exc_info.value.status_code == expected_status
    assert exc_info.value.detail == expected_detail
    assert "secret" not in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_restart_records_authenticated_user_as_trigger(
        self,
        test_db: AsyncSession,
        managed_instance: InstanceModel,
        test_user: User,
    ) -> None:
        await restart_instance(
            _request(),
            managed_instance.id,
            tenant_id=managed_instance.tenant_id,
            current_user=test_user,
            db=test_db,
        )

        deploy = await _latest_deploy(test_db, managed_instance.id)
        assert deploy.triggered_by == test_user.id

    @pytest.mark.asyncio
    async def test_apply_config_records_authenticated_user_as_trigger(
        self,
        test_db: AsyncSession,
        managed_instance: InstanceModel,
        test_user: User,
    ) -> None:
        managed_instance.pending_config = {"image_version": "2.0.0"}
        await test_db.commit()

        await apply_pending_config(
            _request(),
            managed_instance.id,
            tenant_id=managed_instance.tenant_id,
            current_user=test_user,
            db=test_db,
        )

        deploy = await _latest_deploy(test_db, managed_instance.id)
        assert deploy.triggered_by == test_user.id
