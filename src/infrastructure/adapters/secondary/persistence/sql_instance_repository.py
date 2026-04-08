"""SQLAlchemy implementation of InstanceRepository using BaseRepository."""

import logging
from typing import override

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.instance.enums import InstanceStatus, ServiceType
from src.domain.model.instance.instance import Instance
from src.domain.ports.repositories.instance_repository import InstanceRepository
from src.infrastructure.adapters.secondary.common.base_repository import BaseRepository
from src.infrastructure.adapters.secondary.persistence.models import (
    InstanceModel,
)

logger = logging.getLogger(__name__)


class SqlInstanceRepository(BaseRepository[Instance, InstanceModel], InstanceRepository):
    """SQLAlchemy implementation of InstanceRepository."""

    _model_class = InstanceModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @override
    async def find_by_tenant(
        self, tenant_id: str, limit: int = 50, offset: int = 0
    ) -> list[Instance]:
        return await self.list_all(limit=limit, offset=offset, tenant_id=tenant_id)

    @override
    async def find_by_slug(self, tenant_id: str, slug: str) -> Instance | None:
        return await self.find_one(tenant_id=tenant_id, slug=slug)

    @override
    async def find_by_workspace(self, workspace_id: str) -> list[Instance]:
        return await self.list_all(workspace_id=workspace_id)

    @override
    async def find_by_cluster(self, cluster_id: str) -> list[Instance]:
        return await self.list_all(cluster_id=cluster_id)

    @override
    async def count_by_tenant(self, tenant_id: str) -> int:
        return await self.count(tenant_id=tenant_id)

    @override
    def _to_domain(self, db_model: InstanceModel | None) -> Instance | None:
        if db_model is None:
            return None
        return Instance(
            id=db_model.id,
            name=db_model.name,
            slug=db_model.slug,
            tenant_id=db_model.tenant_id,
            cluster_id=db_model.cluster_id,
            namespace=db_model.namespace,
            image_version=db_model.image_version,
            replicas=db_model.replicas,
            cpu_request=db_model.cpu_request,
            cpu_limit=db_model.cpu_limit,
            mem_request=db_model.mem_request,
            mem_limit=db_model.mem_limit,
            service_type=ServiceType(db_model.service_type),
            ingress_domain=db_model.ingress_domain,
            proxy_token=db_model.proxy_token,
            env_vars=db_model.env_vars or {},
            quota_cpu=db_model.quota_cpu,
            quota_memory=db_model.quota_memory,
            quota_max_pods=db_model.quota_max_pods,
            storage_class=db_model.storage_class,
            storage_size=db_model.storage_size,
            advanced_config=db_model.advanced_config or {},
            llm_providers=db_model.llm_providers or {},
            pending_config=db_model.pending_config or {},
            available_replicas=db_model.available_replicas,
            status=InstanceStatus(db_model.status),
            health_status=db_model.health_status,
            current_revision=db_model.current_revision,
            compute_provider=db_model.compute_provider,
            runtime=db_model.runtime,
            created_by=db_model.created_by,
            workspace_id=db_model.workspace_id,
            hex_position_q=db_model.hex_position_q,
            hex_position_r=db_model.hex_position_r,
            agent_display_name=db_model.agent_display_name,
            agent_label=db_model.agent_label,
            theme_color=db_model.theme_color,
            created_at=db_model.created_at,
            updated_at=db_model.updated_at,
            deleted_at=db_model.deleted_at,
        )

    @override
    def _to_db(self, domain_entity: Instance) -> InstanceModel:
        return InstanceModel(
            id=domain_entity.id,
            name=domain_entity.name,
            slug=domain_entity.slug,
            tenant_id=domain_entity.tenant_id,
            cluster_id=domain_entity.cluster_id,
            namespace=domain_entity.namespace,
            image_version=domain_entity.image_version,
            replicas=domain_entity.replicas,
            cpu_request=domain_entity.cpu_request,
            cpu_limit=domain_entity.cpu_limit,
            mem_request=domain_entity.mem_request,
            mem_limit=domain_entity.mem_limit,
            service_type=domain_entity.service_type.value,
            ingress_domain=domain_entity.ingress_domain,
            proxy_token=domain_entity.proxy_token,
            env_vars=domain_entity.env_vars,
            quota_cpu=domain_entity.quota_cpu,
            quota_memory=domain_entity.quota_memory,
            quota_max_pods=domain_entity.quota_max_pods,
            storage_class=domain_entity.storage_class,
            storage_size=domain_entity.storage_size,
            advanced_config=domain_entity.advanced_config,
            llm_providers=domain_entity.llm_providers,
            pending_config=domain_entity.pending_config,
            available_replicas=domain_entity.available_replicas,
            status=domain_entity.status.value,
            health_status=domain_entity.health_status,
            current_revision=domain_entity.current_revision,
            compute_provider=domain_entity.compute_provider,
            runtime=domain_entity.runtime,
            created_by=domain_entity.created_by,
            workspace_id=domain_entity.workspace_id,
            hex_position_q=domain_entity.hex_position_q,
            hex_position_r=domain_entity.hex_position_r,
            agent_display_name=domain_entity.agent_display_name,
            agent_label=domain_entity.agent_label,
            theme_color=domain_entity.theme_color,
            created_at=domain_entity.created_at,
            updated_at=domain_entity.updated_at,
            deleted_at=domain_entity.deleted_at,
        )

    @override
    def _update_fields(self, db_model: InstanceModel, domain_entity: Instance) -> None:
        db_model.name = domain_entity.name
        db_model.slug = domain_entity.slug
        db_model.cluster_id = domain_entity.cluster_id
        db_model.namespace = domain_entity.namespace
        db_model.image_version = domain_entity.image_version
        db_model.replicas = domain_entity.replicas
        db_model.cpu_request = domain_entity.cpu_request
        db_model.cpu_limit = domain_entity.cpu_limit
        db_model.mem_request = domain_entity.mem_request
        db_model.mem_limit = domain_entity.mem_limit
        db_model.service_type = domain_entity.service_type.value
        db_model.ingress_domain = domain_entity.ingress_domain
        db_model.proxy_token = domain_entity.proxy_token
        db_model.env_vars = domain_entity.env_vars
        db_model.quota_cpu = domain_entity.quota_cpu
        db_model.quota_memory = domain_entity.quota_memory
        db_model.quota_max_pods = domain_entity.quota_max_pods
        db_model.storage_class = domain_entity.storage_class
        db_model.storage_size = domain_entity.storage_size
        db_model.advanced_config = domain_entity.advanced_config
        db_model.llm_providers = domain_entity.llm_providers
        db_model.pending_config = domain_entity.pending_config
        db_model.available_replicas = domain_entity.available_replicas
        db_model.status = domain_entity.status.value
        db_model.health_status = domain_entity.health_status
        db_model.current_revision = domain_entity.current_revision
        db_model.compute_provider = domain_entity.compute_provider
        db_model.runtime = domain_entity.runtime
        db_model.workspace_id = domain_entity.workspace_id
        db_model.hex_position_q = domain_entity.hex_position_q
        db_model.hex_position_r = domain_entity.hex_position_r
        db_model.agent_display_name = domain_entity.agent_display_name
        db_model.agent_label = domain_entity.agent_label
        db_model.theme_color = domain_entity.theme_color
        db_model.updated_at = domain_entity.updated_at
        db_model.deleted_at = domain_entity.deleted_at
