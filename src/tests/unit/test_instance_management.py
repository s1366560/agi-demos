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
class TestInstanceServiceCreateUpdateFields:
    """Tests for instance fields exposed by the API schema."""

    async def test_create_instance_persists_extended_fields(self) -> None:
        """create_instance carries UI-exposed deployment fields into the domain entity."""
        repo = AsyncMock()
        deploy_repo = AsyncMock()
        member_repo = AsyncMock()

        service = _make_service(
            instance_repo=repo,
            deploy_record_repo=deploy_repo,
            instance_member_repo=member_repo,
        )

        result = await service.create_instance(
            name="Agent Runtime",
            slug="agent-runtime",
            tenant_id="tenant-1",
            created_by="user-1",
            description="Runs production agents",
            cluster_id="cluster-1",
            namespace="agents",
            quota_cpu="2",
            quota_memory="4Gi",
            quota_max_pods=5,
            storage_class="fast",
            storage_size="20Gi",
            compute_provider="kubernetes",
            runtime="docker",
            workspace_id="workspace-1",
            hex_position_q=2,
            hex_position_r=-1,
            agent_display_name="Runtime Agent",
            agent_label="prod",
            theme_color="#0070f3",
        )

        assert result.description == "Runs production agents"
        assert result.cluster_id == "cluster-1"
        assert result.namespace == "agents"
        assert result.quota_cpu == "2"
        assert result.quota_memory == "4Gi"
        assert result.quota_max_pods == 5
        assert result.storage_class == "fast"
        assert result.storage_size == "20Gi"
        assert result.compute_provider == "kubernetes"
        assert result.runtime == "docker"
        assert result.workspace_id == "workspace-1"
        assert result.hex_position_q == 2
        assert result.hex_position_r == -1
        assert result.agent_display_name == "Runtime Agent"
        assert result.agent_label == "prod"
        assert result.theme_color == "#0070f3"
        repo.save.assert_awaited_once_with(result)

    async def test_update_instance_persists_extended_fields(self) -> None:
        """update_instance applies mutable fields from the API update schema."""
        instance = _make_instance()
        repo = AsyncMock()
        repo.find_by_id.return_value = instance

        service = _make_service(instance_repo=repo)
        result = await service.update_instance(
            instance_id="inst-1",
            description="Updated runtime description",
            slug="renamed-runtime",
            cluster_id="cluster-2",
            namespace="runtime",
            quota_cpu="4",
            quota_memory="8Gi",
            quota_max_pods=10,
            storage_class="standard",
            storage_size="50Gi",
            compute_provider="local",
            runtime="kubernetes",
            workspace_id="workspace-2",
            hex_position_q=4,
            hex_position_r=3,
            agent_display_name="Updated Runtime Agent",
            agent_label="staging",
            theme_color="#171717",
        )

        assert result.description == "Updated runtime description"
        assert result.slug == "renamed-runtime"
        assert result.cluster_id == "cluster-2"
        assert result.namespace == "runtime"
        assert result.quota_cpu == "4"
        assert result.quota_memory == "8Gi"
        assert result.quota_max_pods == 10
        assert result.storage_class == "standard"
        assert result.storage_size == "50Gi"
        assert result.compute_provider == "local"
        assert result.runtime == "kubernetes"
        assert result.workspace_id == "workspace-2"
        assert result.hex_position_q == 4
        assert result.hex_position_r == 3
        assert result.agent_display_name == "Updated Runtime Agent"
        assert result.agent_label == "staging"
        assert result.theme_color == "#171717"
        repo.save.assert_awaited_once_with(result)


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
