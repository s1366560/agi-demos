"""Unit tests for instance management fixes."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.application.services.instance_service import InstanceService
from src.domain.model.instance.enums import InstanceStatus, ServiceType
from src.domain.model.instance.instance import Instance


def _make_instance(
    *,
    instance_id: str = "inst-1",
    name: str = "test-instance",
    tenant_id: str = "tenant-1",
    status: InstanceStatus = InstanceStatus.running,
) -> Instance:
    return Instance(
        id=instance_id,
        name=name,
        slug=name,
        tenant_id=tenant_id,
        created_by="user-1",
        status=status,
        image_version="latest",
        replicas=1,
        cpu_request="100m",
        cpu_limit="500m",
        mem_request="256Mi",
        mem_limit="512Mi",
        service_type=ServiceType.cluster_ip,
        env_vars={},
        advanced_config={},
        llm_providers={},
        pending_config={},
        runtime="default",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_service(
    *,
    instance_repo: AsyncMock | None = None,
    deploy_record_repo: AsyncMock | None = None,
    instance_member_repo: AsyncMock | None = None,
    cluster_repo: AsyncMock | None = None,
) -> InstanceService:
    if instance_repo is None:
        instance_repo = AsyncMock()
    if deploy_record_repo is None:
        deploy_record_repo = AsyncMock()
    if instance_member_repo is None:
        instance_member_repo = AsyncMock()
    if cluster_repo is None:
        cluster_repo = AsyncMock()
    return InstanceService(
        instance_repo=instance_repo,
        deploy_record_repo=deploy_record_repo,
        instance_member_repo=instance_member_repo,
        cluster_repo=cluster_repo,
    )


@pytest.mark.unit
class TestInstanceServiceListPagination:
    """Tests for list_instances returning (items, total) tuple."""

    async def test_list_instances_returns_tuple_with_total(self) -> None:
        """list_instances returns (list, total_count) not just list."""
        instances = [_make_instance(instance_id=f"inst-{i}") for i in range(3)]
        repo = AsyncMock()
        repo.find_by_tenant.return_value = instances
        repo.count_by_tenant.return_value = 10

        service = _make_service(instance_repo=repo)
        result = await service.list_instances(tenant_id="tenant-1", limit=3, offset=0)

        assert isinstance(result, tuple)
        items, total = result
        assert len(items) == 3
        assert total == 10
        repo.count_by_tenant.assert_awaited_once_with("tenant-1")

    async def test_list_instances_empty(self) -> None:
        """list_instances returns empty list with zero total."""
        repo = AsyncMock()
        repo.find_by_tenant.return_value = []
        repo.count_by_tenant.return_value = 0

        service = _make_service(instance_repo=repo)
        items, total = await service.list_instances(tenant_id="tenant-1", limit=10, offset=0)

        assert items == []
        assert total == 0


@pytest.mark.unit
class TestInstanceServiceUpdateConfig:
    """Tests for the new update_config service method."""

    async def test_update_config_all_fields(self) -> None:
        """update_config sets all three config fields."""
        instance = _make_instance()
        repo = AsyncMock()
        repo.find_by_id.return_value = instance

        service = _make_service(instance_repo=repo)
        result = await service.update_config(
            instance_id="inst-1",
            env_vars={"KEY": "val"},
            advanced_config={"debug": True},
            llm_providers={"openai": {"key": "x"}},
        )

        assert result.env_vars == {"KEY": "val"}
        assert result.advanced_config == {"debug": True}
        assert result.llm_providers == {"openai": {"key": "x"}}
        repo.save.assert_awaited_once()

    async def test_update_config_partial(self) -> None:
        """update_config only updates provided fields."""
        instance = _make_instance()
        instance.env_vars = {"OLD": "val"}
        instance.advanced_config = {"old": True}
        repo = AsyncMock()
        repo.find_by_id.return_value = instance

        service = _make_service(instance_repo=repo)
        result = await service.update_config(
            instance_id="inst-1",
            env_vars={"NEW": "val"},
        )

        assert result.env_vars == {"NEW": "val"}
        assert result.advanced_config == {"old": True}

    async def test_update_config_not_found(self) -> None:
        """update_config raises ValueError for missing instance."""
        repo = AsyncMock()
        repo.find_by_id.return_value = None

        service = _make_service(instance_repo=repo)
        with pytest.raises(ValueError, match="not found"):
            await service.update_config(instance_id="missing")


@pytest.mark.unit
class TestInstanceServiceScaleRestart:
    """Tests for scale/restart returning DeployRecord."""

    async def test_scale_instance_updates_replicas_and_status(self) -> None:
        """scale_instance sets instance replicas and status to scaling."""
        instance = _make_instance()
        repo = AsyncMock()
        repo.find_by_id.return_value = instance
        deploy_repo = AsyncMock()

        service = _make_service(instance_repo=repo, deploy_record_repo=deploy_repo)
        await service.scale_instance(
            instance_id="inst-1",
            replicas=5,
            triggered_by="user-1",
        )

        assert instance.replicas == 5
        assert instance.status == InstanceStatus.scaling
        repo.save.assert_awaited_once()
        deploy_repo.save.assert_awaited_once()

    async def test_restart_instance_sets_restarting_status(self) -> None:
        """restart_instance sets status to restarting."""
        instance = _make_instance()
        repo = AsyncMock()
        repo.find_by_id.return_value = instance
        deploy_repo = AsyncMock()

        service = _make_service(instance_repo=repo, deploy_record_repo=deploy_repo)
        await service.restart_instance(
            instance_id="inst-1",
            triggered_by="user-1",
        )

        assert instance.status == InstanceStatus.restarting
        repo.save.assert_awaited_once()
        deploy_repo.save.assert_awaited_once()

    async def test_scale_instance_not_found(self) -> None:
        """scale_instance raises ValueError for missing instance."""
        repo = AsyncMock()
        repo.find_by_id.return_value = None

        service = _make_service(instance_repo=repo)
        with pytest.raises(ValueError, match="not found"):
            await service.scale_instance("missing", 2, "user-1")

    async def test_restart_instance_not_found(self) -> None:
        """restart_instance raises ValueError for missing instance."""
        repo = AsyncMock()
        repo.find_by_id.return_value = None

        service = _make_service(instance_repo=repo)
        with pytest.raises(ValueError, match="not found"):
            await service.restart_instance("missing", "user-1")


@pytest.mark.unit
class TestChannelRepoNoneHandling:
    """Tests that verify channel repo returns None instead of raising."""

    async def test_to_domain_handles_none(self) -> None:
        """_to_domain with None db_model is no longer called; find_by_id returns None."""
        from src.infrastructure.adapters.secondary.persistence.sql_instance_channel_repository import (
            SqlInstanceChannelRepository,
        )

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        repo = SqlInstanceChannelRepository(mock_session)
        result = await repo.find_by_id("nonexistent-id")

        assert result is None
