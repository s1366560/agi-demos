"""
InstanceService: Business logic for instance lifecycle management.

This service handles instance CRUD, member management, scaling,
and configuration operations following the hexagonal architecture
pattern.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from src.domain.model.deploy.deploy_record import DeployRecord
from src.domain.model.deploy.enums import DeployAction, DeployStatus
from src.domain.model.instance.enums import (
    InstanceRole,
    InstanceStatus,
    ServiceType,
)
from src.domain.model.instance.instance import Instance, InstanceMember
from src.domain.ports.repositories.cluster_repository import (
    ClusterRepository,
)
from src.domain.ports.repositories.deploy_record_repository import (
    DeployRecordRepository,
)
from src.domain.ports.repositories.instance_member_repository import (
    InstanceMemberRepository,
)
from src.domain.ports.repositories.instance_repository import (
    InstanceRepository,
)

logger = logging.getLogger(__name__)


class InstanceService:
    """Service for managing instance lifecycle, members, and config."""

    def __init__(
        self,
        instance_repo: InstanceRepository,
        instance_member_repo: InstanceMemberRepository,
        deploy_record_repo: DeployRecordRepository,
        cluster_repo: ClusterRepository,
    ) -> None:
        self._instance_repo = instance_repo
        self._instance_member_repo = instance_member_repo
        self._deploy_record_repo = deploy_record_repo
        self._cluster_repo = cluster_repo

    # ------------------------------------------------------------------
    # Instance CRUD
    # ------------------------------------------------------------------

    async def create_instance(  # noqa: PLR0913
        self,
        name: str,
        slug: str,
        tenant_id: str,
        created_by: str,
        *,
        cluster_id: str | None = None,
        namespace: str | None = None,
        image_version: str = "latest",
        replicas: int = 1,
        cpu_request: str = "100m",
        cpu_limit: str = "500m",
        mem_request: str = "256Mi",
        mem_limit: str = "512Mi",
        service_type: ServiceType = ServiceType.cluster_ip,
        ingress_domain: str | None = None,
        env_vars: dict[str, Any] | None = None,
        advanced_config: dict[str, Any] | None = None,
        llm_providers: dict[str, Any] | None = None,
        workspace_id: str | None = None,
    ) -> Instance:
        """Create a new instance, add creator as admin, record deploy.

        Args:
            name: Human-readable instance name.
            slug: URL-safe identifier (unique within tenant).
            tenant_id: Owning tenant.
            created_by: User ID of the creator.
            **optional_fields: Resource limits, networking, etc.

        Returns:
            The newly created Instance.
        """
        instance = Instance(
            id=Instance.generate_id(),
            name=name,
            slug=slug,
            tenant_id=tenant_id,
            created_by=created_by,
            cluster_id=cluster_id,
            namespace=namespace,
            image_version=image_version,
            replicas=replicas,
            cpu_request=cpu_request,
            cpu_limit=cpu_limit,
            mem_request=mem_request,
            mem_limit=mem_limit,
            service_type=service_type,
            ingress_domain=ingress_domain,
            env_vars=env_vars or {},
            advanced_config=advanced_config or {},
            llm_providers=llm_providers or {},
            workspace_id=workspace_id,
            status=InstanceStatus.creating,
            created_at=datetime.now(UTC),
        )
        await self._instance_repo.save(instance)

        # Creator becomes admin member
        member = InstanceMember(
            id=InstanceMember.generate_id(),
            instance_id=instance.id,
            user_id=created_by,
            role=InstanceRole.admin,
            created_at=datetime.now(UTC),
        )
        await self._instance_member_repo.save(member)

        # Initial deploy record
        deploy = DeployRecord(
            id=DeployRecord.generate_id(),
            instance_id=instance.id,
            revision=1,
            action=DeployAction.create,
            image_version=image_version,
            replicas=replicas,
            status=DeployStatus.pending,
            triggered_by=created_by,
            created_at=datetime.now(UTC),
        )
        await self._deploy_record_repo.save(deploy)

        logger.info(
            "Created instance %s (%s) for tenant %s",
            instance.id,
            slug,
            tenant_id,
        )
        return instance

    async def get_instance(self, instance_id: str) -> Instance | None:
        """Retrieve an instance by ID.

        Returns:
            Instance if found, None otherwise.
        """
        return await self._instance_repo.find_by_id(instance_id)

    async def list_instances(
        self,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Instance], int]:
        """List instances belonging to a tenant.

        Args:
            tenant_id: Tenant scope.
            limit: Maximum results.
            offset: Pagination offset.

        Returns:
            Tuple of (list of instances, total count).
        """
        items = await self._instance_repo.find_by_tenant(tenant_id, limit=limit, offset=offset)
        total = await self._instance_repo.count_by_tenant(tenant_id)
        return items, total

    async def update_instance(  # noqa: PLR0913, C901, PLR0912
        self,
        instance_id: str,
        *,
        name: str | None = None,
        image_version: str | None = None,
        replicas: int | None = None,
        cpu_request: str | None = None,
        cpu_limit: str | None = None,
        mem_request: str | None = None,
        mem_limit: str | None = None,
        service_type: ServiceType | None = None,
        ingress_domain: str | None = None,
        env_vars: dict[str, Any] | None = None,
        advanced_config: dict[str, Any] | None = None,
        llm_providers: dict[str, Any] | None = None,
        workspace_id: str | None = None,
        agent_display_name: str | None = None,
        agent_label: str | None = None,
        theme_color: str | None = None,
    ) -> Instance:
        """Update mutable fields of an instance.

        Args:
            instance_id: Target instance.
            **optional_fields: Fields to update (None = skip).

        Returns:
            The updated Instance.

        Raises:
            ValueError: If instance does not exist.
        """
        instance = await self._instance_repo.find_by_id(instance_id)
        if not instance:
            raise ValueError(f"Instance {instance_id} not found")

        if name is not None:
            instance.name = name
        if image_version is not None:
            instance.image_version = image_version
        if replicas is not None:
            instance.replicas = replicas
        if cpu_request is not None:
            instance.cpu_request = cpu_request
        if cpu_limit is not None:
            instance.cpu_limit = cpu_limit
        if mem_request is not None:
            instance.mem_request = mem_request
        if mem_limit is not None:
            instance.mem_limit = mem_limit
        if service_type is not None:
            instance.service_type = service_type
        if ingress_domain is not None:
            instance.ingress_domain = ingress_domain
        if env_vars is not None:
            instance.env_vars = env_vars
        if advanced_config is not None:
            instance.advanced_config = advanced_config
        if llm_providers is not None:
            instance.llm_providers = llm_providers
        if workspace_id is not None:
            instance.workspace_id = workspace_id
        if agent_display_name is not None:
            instance.agent_display_name = agent_display_name
        if agent_label is not None:
            instance.agent_label = agent_label
        if theme_color is not None:
            instance.theme_color = theme_color

        instance.updated_at = datetime.now(UTC)
        await self._instance_repo.save(instance)
        logger.info("Updated instance %s", instance_id)
        return instance

    async def delete_instance(self, instance_id: str) -> None:
        """Soft-delete an instance.

        Args:
            instance_id: Target instance.

        Raises:
            ValueError: If instance does not exist.
        """
        instance = await self._instance_repo.find_by_id(instance_id)
        if not instance:
            raise ValueError(f"Instance {instance_id} not found")

        instance.soft_delete()
        await self._instance_repo.save(instance)
        logger.info("Soft-deleted instance %s", instance_id)

    # ------------------------------------------------------------------
    # Scaling & Restart
    # ------------------------------------------------------------------

    async def scale_instance(
        self,
        instance_id: str,
        replicas: int,
        triggered_by: str,
    ) -> DeployRecord:
        """Create a scale deploy record and update replica count.

        Args:
            instance_id: Target instance.
            replicas: Desired replica count.
            triggered_by: User who initiated scaling.

        Returns:
            The created DeployRecord.

        Raises:
            ValueError: If instance does not exist.
        """
        instance = await self._instance_repo.find_by_id(instance_id)
        if not instance:
            raise ValueError(f"Instance {instance_id} not found")

        instance.replicas = replicas
        instance.status = InstanceStatus.scaling
        instance.updated_at = datetime.now(UTC)
        await self._instance_repo.save(instance)

        deploy = DeployRecord(
            id=DeployRecord.generate_id(),
            instance_id=instance_id,
            revision=instance.current_revision + 1,
            action=DeployAction.scale,
            replicas=replicas,
            status=DeployStatus.pending,
            triggered_by=triggered_by,
            created_at=datetime.now(UTC),
        )
        await self._deploy_record_repo.save(deploy)

        logger.info(
            "Scaling instance %s to %d replicas",
            instance_id,
            replicas,
        )
        return deploy

    async def restart_instance(
        self,
        instance_id: str,
        triggered_by: str,
    ) -> DeployRecord:
        """Create a restart deploy record.

        Args:
            instance_id: Target instance.
            triggered_by: User who initiated restart.

        Returns:
            The created DeployRecord.

        Raises:
            ValueError: If instance does not exist.
        """
        instance = await self._instance_repo.find_by_id(instance_id)
        if not instance:
            raise ValueError(f"Instance {instance_id} not found")

        instance.status = InstanceStatus.restarting
        instance.updated_at = datetime.now(UTC)
        await self._instance_repo.save(instance)

        deploy = DeployRecord(
            id=DeployRecord.generate_id(),
            instance_id=instance_id,
            revision=instance.current_revision + 1,
            action=DeployAction.restart,
            status=DeployStatus.pending,
            triggered_by=triggered_by,
            created_at=datetime.now(UTC),
        )
        await self._deploy_record_repo.save(deploy)

        logger.info("Restarting instance %s", instance_id)
        return deploy

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    async def update_config(
        self,
        instance_id: str,
        env_vars: dict[str, Any] | None = None,
        advanced_config: dict[str, Any] | None = None,
        llm_providers: dict[str, Any] | None = None,
    ) -> Instance:
        """Update instance configuration fields directly.

        Args:
            instance_id: Target instance.
            env_vars: Environment variables to set (if provided).
            advanced_config: Advanced config to set (if provided).
            llm_providers: LLM provider config to set (if provided).

        Returns:
            The updated Instance.

        Raises:
            ValueError: If instance does not exist.
        """
        instance = await self._instance_repo.find_by_id(instance_id)
        if not instance:
            raise ValueError(f"Instance {instance_id} not found")

        if env_vars is not None:
            instance.env_vars = env_vars
        if advanced_config is not None:
            instance.advanced_config = advanced_config
        if llm_providers is not None:
            instance.llm_providers = llm_providers
        instance.updated_at = datetime.now(UTC)
        await self._instance_repo.save(instance)

        logger.info("Updated config for instance %s", instance_id)
        return instance

    async def save_pending_config(
        self,
        instance_id: str,
        config: dict[str, Any],
    ) -> Instance:
        """Save configuration to the pending_config field.

        The pending config is not applied until apply_pending_config
        is called.

        Args:
            instance_id: Target instance.
            config: Configuration dict to stage.

        Returns:
            The updated Instance.

        Raises:
            ValueError: If instance does not exist.
        """
        instance = await self._instance_repo.find_by_id(instance_id)
        if not instance:
            raise ValueError(f"Instance {instance_id} not found")

        instance.pending_config = config
        instance.updated_at = datetime.now(UTC)
        await self._instance_repo.save(instance)

        logger.info("Saved pending config for instance %s", instance_id)
        return instance

    async def apply_pending_config(
        self,
        instance_id: str,
        triggered_by: str,
    ) -> DeployRecord:
        """Apply pending_config and create a config_apply deploy record.

        Args:
            instance_id: Target instance.
            triggered_by: User who initiated the config apply.

        Returns:
            The created DeployRecord.

        Raises:
            ValueError: If instance does not exist or has no pending
                config.
        """
        instance = await self._instance_repo.find_by_id(instance_id)
        if not instance:
            raise ValueError(f"Instance {instance_id} not found")

        if not instance.pending_config:
            raise ValueError(f"Instance {instance_id} has no pending config")

        config_snapshot = dict(instance.pending_config)
        instance.pending_config = {}
        instance.updated_at = datetime.now(UTC)
        await self._instance_repo.save(instance)

        deploy = DeployRecord(
            id=DeployRecord.generate_id(),
            instance_id=instance_id,
            revision=instance.current_revision + 1,
            action=DeployAction.config_apply,
            config_snapshot=config_snapshot,
            status=DeployStatus.pending,
            triggered_by=triggered_by,
            created_at=datetime.now(UTC),
        )
        await self._deploy_record_repo.save(deploy)

        logger.info("Applied pending config for instance %s", instance_id)
        return deploy

    # ------------------------------------------------------------------
    # Member Management
    # ------------------------------------------------------------------

    async def add_member(
        self,
        instance_id: str,
        user_id: str,
        role: str = "viewer",
    ) -> InstanceMember:
        """Add a user as a member of an instance.

        Args:
            instance_id: Target instance.
            user_id: User to add.
            role: Member role (default: viewer).

        Returns:
            The created InstanceMember.

        Raises:
            ValueError: If instance does not exist or user is
                already a member.
        """
        instance = await self._instance_repo.find_by_id(instance_id)
        if not instance:
            raise ValueError(f"Instance {instance_id} not found")

        existing = await self._instance_member_repo.find_by_user_and_instance(user_id, instance_id)
        if existing:
            raise ValueError(f"User {user_id} is already a member of instance {instance_id}")

        member = InstanceMember(
            id=InstanceMember.generate_id(),
            instance_id=instance_id,
            user_id=user_id,
            role=InstanceRole(role),
            created_at=datetime.now(UTC),
        )
        await self._instance_member_repo.save(member)

        logger.info(
            "Added user %s to instance %s as %s",
            user_id,
            instance_id,
            role,
        )
        return member

    async def remove_member(
        self,
        instance_id: str,
        user_id: str,
    ) -> None:
        """Soft-delete a member from an instance.

        Args:
            instance_id: Target instance.
            user_id: User to remove.

        Raises:
            ValueError: If instance does not exist or user is not a
                member.
        """
        instance = await self._instance_repo.find_by_id(instance_id)
        if not instance:
            raise ValueError(f"Instance {instance_id} not found")

        member = await self._instance_member_repo.find_by_user_and_instance(user_id, instance_id)
        if not member:
            raise ValueError(f"User {user_id} is not a member of instance {instance_id}")

        member.deleted_at = datetime.now(UTC)
        await self._instance_member_repo.save(member)

        logger.info(
            "Removed user %s from instance %s",
            user_id,
            instance_id,
        )

    async def update_member_role(
        self,
        instance_id: str,
        member_id: str,
        role: str,
    ) -> InstanceMember:
        """Update the role of an existing instance member.

        Args:
            instance_id: Target instance.
            member_id: Member record ID.
            role: New role value.

        Returns:
            The updated InstanceMember.

        Raises:
            ValueError: If instance or member does not exist.
        """
        instance = await self._instance_repo.find_by_id(instance_id)
        if not instance:
            raise ValueError(f"Instance {instance_id} not found")

        member = await self._instance_member_repo.find_by_id(member_id)
        if not member or member.instance_id != instance_id:
            raise ValueError(f"Member {member_id} not found in instance {instance_id}")

        member.role = InstanceRole(role)
        await self._instance_member_repo.save(member)

        logger.info(
            "Updated member %s role to %s in instance %s",
            member_id,
            role,
            instance_id,
        )
        return member

    async def list_members(self, instance_id: str) -> list[InstanceMember]:
        """List all members of an instance.

        Args:
            instance_id: Target instance.

        Returns:
            List of InstanceMember entities.

        Raises:
            ValueError: If instance does not exist.
        """
        instance = await self._instance_repo.find_by_id(instance_id)
        if not instance:
            raise ValueError(f"Instance {instance_id} not found")

        return await self._instance_member_repo.find_by_instance(instance_id)
