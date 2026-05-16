"""Unit tests for deploy route tenant authorization."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.deploy_schemas import DeployCreate
from src.infrastructure.adapters.primary.web.routers.deploy import (
    _require_deploy_tenant_access,
    _require_instance_tenant_access,
    create_deploy,
    list_deploys,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    DeployRecordModel,
    InstanceModel,
    Project,
    User,
)


@pytest.fixture
async def deploy_instance(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> InstanceModel:
    instance = InstanceModel(
        id=str(uuid4()),
        name="Deploy Instance",
        slug="deploy-instance",
        tenant_id=test_project_db.tenant_id,
        service_type="ClusterIP",
        created_by=test_user.id,
    )
    test_db.add(instance)
    await test_db.commit()
    await test_db.refresh(instance)
    return instance


@pytest.fixture
async def deploy_record(
    test_db: AsyncSession,
    deploy_instance: InstanceModel,
) -> DeployRecordModel:
    record = DeployRecordModel(
        id=str(uuid4()),
        instance_id=deploy_instance.id,
        revision=1,
        action="create",
        status="pending",
    )
    test_db.add(record)
    await test_db.commit()
    await test_db.refresh(record)
    return record


@pytest.mark.unit
class TestDeployRouterAuthorization:
    @pytest.mark.asyncio
    async def test_member_can_access_instance_deploys(
        self,
        test_db: AsyncSession,
        deploy_instance: InstanceModel,
        test_user: User,
    ) -> None:
        tenant_id = await _require_instance_tenant_access(test_db, test_user, deploy_instance.id)

        assert tenant_id == deploy_instance.tenant_id

    @pytest.mark.asyncio
    async def test_non_member_cannot_access_instance_deploys(
        self,
        test_db: AsyncSession,
        deploy_instance: InstanceModel,
        another_user: User,
    ) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await _require_instance_tenant_access(test_db, another_user, deploy_instance.id)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.asyncio
    async def test_missing_instance_returns_not_found(
        self,
        test_db: AsyncSession,
        test_user: User,
    ) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await _require_instance_tenant_access(test_db, test_user, "missing-instance")

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.asyncio
    async def test_non_member_cannot_access_deploy_record(
        self,
        test_db: AsyncSession,
        deploy_record: DeployRecordModel,
        another_user: User,
    ) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await _require_deploy_tenant_access(test_db, another_user, deploy_record.id)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.asyncio
    async def test_superuser_can_access_deploy_record_without_membership(
        self,
        test_db: AsyncSession,
        deploy_record: DeployRecordModel,
        another_user: User,
    ) -> None:
        another_user.is_superuser = True

        await _require_deploy_tenant_access(test_db, another_user, deploy_record.id)

    @pytest.mark.asyncio
    async def test_list_deploys_rejects_non_member_before_service_lookup(
        self,
        test_db: AsyncSession,
        deploy_instance: InstanceModel,
        another_user: User,
    ) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await list_deploys(
                SimpleNamespace(),
                instance_id=deploy_instance.id,
                current_user=another_user,
                db=test_db,
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.asyncio
    async def test_create_deploy_records_authenticated_user_as_trigger(
        self,
        test_db: AsyncSession,
        deploy_instance: InstanceModel,
        test_user: User,
        another_user: User,
    ) -> None:
        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    container=SimpleNamespace(graph_service=None, redis_client=None)
                )
            )
        )

        response = await create_deploy(
            request,
            DeployCreate(
                instance_id=deploy_instance.id,
                action="create",
                triggered_by=another_user.id,
            ),
            current_user=test_user,
            db=test_db,
        )

        assert response.triggered_by == test_user.id

    @pytest.mark.asyncio
    async def test_create_deploy_rejects_invalid_action(
        self,
        test_db: AsyncSession,
        deploy_instance: InstanceModel,
        test_user: User,
    ) -> None:
        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    container=SimpleNamespace(graph_service=None, redis_client=None)
                )
            )
        )

        with pytest.raises(HTTPException) as exc_info:
            await create_deploy(
                request,
                DeployCreate(instance_id=deploy_instance.id, action="invalid"),
                current_user=test_user,
                db=test_db,
            )

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
