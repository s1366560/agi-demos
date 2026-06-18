"""Unit tests for deploy route tenant authorization."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.deploy_schemas import DeployCreate
from src.infrastructure.adapters.primary.web.routers import deploy as deploy_router
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
    async def test_list_deploys_returns_total_count_not_page_size(
        self,
        test_db: AsyncSession,
        deploy_instance: InstanceModel,
        test_user: User,
    ) -> None:
        for revision in range(1, 4):
            test_db.add(
                DeployRecordModel(
                    id=str(uuid4()),
                    instance_id=deploy_instance.id,
                    revision=revision,
                    action="update",
                    status="pending",
                    triggered_by=test_user.id,
                )
            )
        await test_db.commit()

        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    container=SimpleNamespace(graph_service=None, redis_client=None)
                )
            )
        )

        response = await list_deploys(
            request,
            instance_id=deploy_instance.id,
            page=2,
            page_size=1,
            current_user=test_user,
            db=test_db,
        )

        assert len(response.deploys) == 1
        assert response.total == 3
        assert response.page == 2
        assert response.page_size == 1

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


class _FailingDeployService:
    async def create_deploy(self, **_kwargs: object) -> object:
        raise ValueError("Instance instance-secret not found")

    async def get_latest_deploy(self, **_kwargs: object) -> object | None:
        return None

    async def get_deploy(self, **_kwargs: object) -> object | None:
        return None

    async def mark_deploy_success(self, **_kwargs: object) -> object:
        raise ValueError("Deploy record deploy-secret not found")

    async def mark_deploy_failed(self, **_kwargs: object) -> object:
        raise ValueError("Instance instance-secret not found")

    async def cancel_deploy(self, **_kwargs: object) -> object:
        raise ValueError("Deploy deploy-secret is already terminal")


class _FailingContainer:
    def __init__(self) -> None:
        self.service = _FailingDeployService()
        self.redis_client = SimpleNamespace()

    def deploy_service(self) -> _FailingDeployService:
        return self.service


@pytest.mark.unit
@pytest.mark.parametrize(
    ("call_name", "call_args", "expected_status", "expected_detail"),
    [
        (
            "create_deploy",
            {
                "data": DeployCreate(instance_id="instance-secret", action="create"),
            },
            status.HTTP_400_BAD_REQUEST,
            "Deploy operation failed",
        ),
        (
            "get_latest_deploy",
            {
                "instance_id": "instance-secret",
            },
            status.HTTP_404_NOT_FOUND,
            "Deploy not found",
        ),
        (
            "get_deploy",
            {
                "deploy_id": "deploy-secret",
            },
            status.HTTP_404_NOT_FOUND,
            "Deploy not found",
        ),
        (
            "mark_deploy_success",
            {
                "deploy_id": "deploy-secret",
                "data": deploy_router.DeploySuccessRequest(message="ok"),
            },
            status.HTTP_400_BAD_REQUEST,
            "Deploy operation failed",
        ),
        (
            "mark_deploy_failed",
            {
                "deploy_id": "deploy-secret",
                "data": deploy_router.DeployFailedRequest(message="failed"),
            },
            status.HTTP_400_BAD_REQUEST,
            "Deploy operation failed",
        ),
        (
            "cancel_deploy",
            {
                "deploy_id": "deploy-secret",
            },
            status.HTTP_400_BAD_REQUEST,
            "Deploy operation failed",
        ),
        (
            "stream_deploy_progress",
            {
                "deploy_id": "deploy-secret",
            },
            status.HTTP_404_NOT_FOUND,
            "Deploy not found",
        ),
    ],
)
async def test_deploy_routes_sanitize_missing_resource_errors(
    call_name: str,
    call_args: dict[str, object],
    expected_status: int,
    expected_detail: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def allow_instance_access(*_args: object, **_kwargs: object) -> str:
        return "tenant-1"

    async def allow_deploy_access(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(deploy_router, "_require_instance_tenant_access", allow_instance_access)
    monkeypatch.setattr(deploy_router, "_require_deploy_tenant_access", allow_deploy_access)
    monkeypatch.setattr(deploy_router, "get_container_with_db", lambda *_args: _FailingContainer())

    with pytest.raises(HTTPException) as exc_info:
        await getattr(deploy_router, call_name)(
            request=SimpleNamespace(),
            current_user=SimpleNamespace(id="user-1", is_superuser=False),
            db=SimpleNamespace(commit=AsyncMock()),
            **call_args,
        )

    assert exc_info.value.status_code == expected_status
    assert exc_info.value.detail == expected_detail
    assert "secret" not in exc_info.value.detail
