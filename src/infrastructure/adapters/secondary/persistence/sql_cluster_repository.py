"""SQLAlchemy implementation of ClusterRepository using BaseRepository."""

import logging
from typing import override

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.cluster.cluster import Cluster
from src.domain.model.cluster.enums import ClusterProvider, ClusterStatus
from src.domain.ports.repositories.cluster_repository import ClusterRepository
from src.infrastructure.adapters.secondary.common.base_repository import BaseRepository
from src.infrastructure.adapters.secondary.persistence.models import (
    ClusterModel,
)

logger = logging.getLogger(__name__)


class SqlClusterRepository(BaseRepository[Cluster, ClusterModel], ClusterRepository):
    """SQLAlchemy implementation of ClusterRepository."""

    _model_class = ClusterModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @override
    async def find_by_tenant(
        self, tenant_id: str, limit: int = 50, offset: int = 0
    ) -> list[Cluster]:
        return await self.list_all(limit=limit, offset=offset, tenant_id=tenant_id)

    @override
    async def find_by_name(self, tenant_id: str, name: str) -> Cluster | None:
        return await self.find_one(tenant_id=tenant_id, name=name)

    @override
    def _to_domain(self, db_model: ClusterModel | None) -> Cluster | None:
        if db_model is None:
            return None
        return Cluster(
            id=db_model.id,
            name=db_model.name,
            tenant_id=db_model.tenant_id,
            compute_provider=ClusterProvider(db_model.compute_provider),
            status=ClusterStatus(db_model.status),
            health_status=db_model.health_status,
            last_health_check=db_model.last_health_check,
            proxy_endpoint=db_model.proxy_endpoint,
            created_by=db_model.created_by,
            provider_config=db_model.provider_config or {},
            credentials_encrypted=db_model.credentials_encrypted,
            created_at=db_model.created_at,
            updated_at=db_model.updated_at,
            deleted_at=db_model.deleted_at,
        )

    @override
    def _to_db(self, domain_entity: Cluster) -> ClusterModel:
        return ClusterModel(
            id=domain_entity.id,
            name=domain_entity.name,
            tenant_id=domain_entity.tenant_id,
            compute_provider=domain_entity.compute_provider.value,
            status=domain_entity.status.value,
            health_status=domain_entity.health_status,
            last_health_check=domain_entity.last_health_check,
            proxy_endpoint=domain_entity.proxy_endpoint,
            created_by=domain_entity.created_by,
            provider_config=domain_entity.provider_config,
            credentials_encrypted=domain_entity.credentials_encrypted,
            created_at=domain_entity.created_at,
            updated_at=domain_entity.updated_at,
            deleted_at=domain_entity.deleted_at,
        )

    @override
    def _update_fields(self, db_model: ClusterModel, domain_entity: Cluster) -> None:
        db_model.name = domain_entity.name
        db_model.compute_provider = domain_entity.compute_provider.value
        db_model.status = domain_entity.status.value
        db_model.health_status = domain_entity.health_status
        db_model.last_health_check = domain_entity.last_health_check
        db_model.proxy_endpoint = domain_entity.proxy_endpoint
        db_model.provider_config = domain_entity.provider_config
        db_model.credentials_encrypted = domain_entity.credentials_encrypted
        db_model.updated_at = domain_entity.updated_at
        db_model.deleted_at = domain_entity.deleted_at
