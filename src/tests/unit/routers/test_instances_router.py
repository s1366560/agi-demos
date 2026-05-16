"""Unit tests for instance route audit fields."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.routers.instances import (
    ScaleRequest,
    apply_pending_config,
    restart_instance,
    scale_instance,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    DeployRecordModel,
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
