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
    search_users,
    update_instance,
    update_member_role,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    DeployRecordModel,
    InstanceMemberModel,
    InstanceModel,
    Project,
    Tenant,
    User,
    UserTenant,
)
from src.infrastructure.plugins.v2.instance_deploy_services import (
    SqlInstanceDeployServiceFactoryV2,
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


def _authority(
    *,
    db: object,
    user: object,
    tenant_id: str,
    instance_service: object | None = None,
) -> SimpleNamespace:
    if instance_service is None:
        operation = SimpleNamespace(require=lambda _service: db)
        services = SqlInstanceDeployServiceFactoryV2().build(operation)  # type: ignore[arg-type]
    else:
        services = SimpleNamespace(
            instances=instance_service,
            directory=SimpleNamespace(
                get_user=AsyncMock(
                    return_value=SimpleNamespace(
                        email="member@example.com",
                        full_name="Member",
                    )
                )
            ),
        )
    return SimpleNamespace(
        db=db,
        current_user=user,
        tenant_id=tenant_id,
        services=services,
        require_tenant_id=lambda: tenant_id,
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
            managed_instance.id,
            ScaleRequest(desired_replicas=3),
            authority=_authority(
                db=test_db,
                user=test_user,
                tenant_id=managed_instance.tenant_id,
            ),
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
    tenant_memberships = [
        UserTenant(
            id=f"instance-member-tenant-row-{index}",
            user_id=users[index].id,
            tenant_id=managed_instance.tenant_id,
        )
        for index in range(3)
    ]
    test_db.add_all([*users, *members, *tenant_memberships])
    await test_db.commit()

    response = await list_members(
        managed_instance.id,
        limit=2,
        offset=0,
        authority=_authority(
            db=test_db,
            user=SimpleNamespace(id="user-a"),
            tenant_id=managed_instance.tenant_id,
        ),
    )

    assert response.total == 3
    assert response.limit == 2
    assert response.offset == 0
    assert response.has_more is True
    assert [member.user_email for member in response.members] == [
        "instance-member-0@example.com",
        "instance-member-1@example.com",
    ]


@pytest.mark.unit
async def test_search_users_only_returns_current_tenant_members(
    test_db: AsyncSession,
    managed_instance: InstanceModel,
    test_project_db: Project,
) -> None:
    same_tenant_user = User(
        id="instance-search-same-tenant",
        email="candidate-current@example.com",
        hashed_password="hash",
        full_name="Candidate Current",
    )
    inactive_same_tenant_user = User(
        id="instance-search-inactive",
        email="candidate-inactive@example.com",
        hashed_password="hash",
        full_name="Candidate Inactive",
        is_active=False,
    )
    other_tenant_user = User(
        id="instance-search-other-tenant",
        email="candidate-other@example.com",
        hashed_password="hash",
        full_name="Candidate Other",
    )
    other_tenant = Tenant(
        id="instance-search-other-tenant-id",
        name="Other Tenant",
        slug="instance-search-other-tenant",
        owner_id=other_tenant_user.id,
    )
    test_db.add_all(
        [
            same_tenant_user,
            inactive_same_tenant_user,
            other_tenant_user,
            other_tenant,
            UserTenant(
                id="instance-search-current-membership",
                user_id=same_tenant_user.id,
                tenant_id=test_project_db.tenant_id,
            ),
            UserTenant(
                id="instance-search-inactive-membership",
                user_id=inactive_same_tenant_user.id,
                tenant_id=test_project_db.tenant_id,
            ),
            UserTenant(
                id="instance-search-other-membership",
                user_id=other_tenant_user.id,
                tenant_id=other_tenant.id,
            ),
        ]
    )
    await test_db.commit()

    results = await search_users(
        managed_instance.id,
        q="candidate",
        limit=20,
        authority=_authority(
            db=test_db,
            user=SimpleNamespace(id="user-a"),
            tenant_id=managed_instance.tenant_id,
        ),
    )

    assert [(user.id, user.email) for user in results] == [
        (same_tenant_user.id, same_tenant_user.email)
    ]


@pytest.mark.unit
async def test_add_member_rejects_user_outside_instance_tenant(
    test_db: AsyncSession,
    managed_instance: InstanceModel,
) -> None:
    foreign_user = User(
        id="instance-member-foreign-user",
        email="instance-member-foreign@example.com",
        hashed_password="hash",
        full_name="Foreign Member",
    )
    foreign_tenant = Tenant(
        id="instance-member-foreign-tenant",
        name="Foreign Tenant",
        slug="instance-member-foreign-tenant",
        owner_id=foreign_user.id,
    )
    test_db.add_all(
        [
            foreign_user,
            foreign_tenant,
            UserTenant(
                id="instance-member-foreign-membership",
                user_id=foreign_user.id,
                tenant_id=foreign_tenant.id,
            ),
        ]
    )
    await test_db.commit()

    with pytest.raises(HTTPException) as exc_info:
        await add_member(
            managed_instance.id,
            InstanceMemberCreate(
                instance_id=managed_instance.id,
                user_id=foreign_user.id,
                role=InstanceRole.viewer.value,
            ),
            authority=_authority(
                db=test_db,
                user=SimpleNamespace(id="user-a"),
                tenant_id=managed_instance.tenant_id,
            ),
        )

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    result = await test_db.execute(
        select(InstanceMemberModel).where(
            InstanceMemberModel.instance_id == managed_instance.id,
            InstanceMemberModel.user_id == foreign_user.id,
        )
    )
    assert result.scalar_one_or_none() is None


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
            },
            status.HTTP_404_NOT_FOUND,
            "Instance operation failed",
        ),
        (
            restart_instance,
            {
                "instance_id": "instance-secret",
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
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await call(
            authority=_authority(
                db=SimpleNamespace(commit=AsyncMock(), execute=AsyncMock()),
                user=SimpleNamespace(id="user-current"),
                tenant_id="tenant-1",
                instance_service=_FailingInstanceService(),
            ),
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
            managed_instance.id,
            authority=_authority(
                db=test_db,
                user=test_user,
                tenant_id=managed_instance.tenant_id,
            ),
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
            managed_instance.id,
            authority=_authority(
                db=test_db,
                user=test_user,
                tenant_id=managed_instance.tenant_id,
            ),
        )

        deploy = await _latest_deploy(test_db, managed_instance.id)
        assert deploy.triggered_by == test_user.id
