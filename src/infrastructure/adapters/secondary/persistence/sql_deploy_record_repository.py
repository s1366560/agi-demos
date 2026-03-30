"""SQLAlchemy implementation of DeployRecordRepository using BaseRepository."""

import logging
from typing import override

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.deploy.deploy_record import DeployRecord
from src.domain.model.deploy.enums import DeployAction, DeployStatus
from src.domain.ports.repositories.deploy_record_repository import (
    DeployRecordRepository,
)
from src.infrastructure.adapters.secondary.common.base_repository import BaseRepository
from src.infrastructure.adapters.secondary.persistence.models import (
    DeployRecordModel,
)

logger = logging.getLogger(__name__)


class SqlDeployRecordRepository(
    BaseRepository[DeployRecord, DeployRecordModel], DeployRecordRepository
):
    """SQLAlchemy implementation of DeployRecordRepository."""

    _model_class = DeployRecordModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @override
    async def find_by_instance(
        self, instance_id: str, limit: int = 50, offset: int = 0
    ) -> list[DeployRecord]:
        query = self._build_query(
            filters={"instance_id": instance_id},
            order_by="created_at",
            order_desc=True,
        )
        query = query.offset(offset).limit(limit)
        result = await self._session.execute(query)
        db_records = result.scalars().all()
        return [d for r in db_records if (d := self._to_domain(r)) is not None]

    @override
    async def find_latest_by_instance(self, instance_id: str) -> DeployRecord | None:
        query = self._build_query(
            filters={"instance_id": instance_id},
            order_by="created_at",
            order_desc=True,
        )
        query = query.limit(1)
        result = await self._session.execute(query)
        db_record = result.scalar_one_or_none()
        return self._to_domain(db_record)

    @override
    def _to_domain(self, db_model: DeployRecordModel | None) -> DeployRecord | None:
        if db_model is None:
            return None
        return DeployRecord(
            id=db_model.id,
            instance_id=db_model.instance_id,
            revision=db_model.revision,
            action=DeployAction(db_model.action),
            image_version=db_model.image_version,
            replicas=db_model.replicas,
            config_snapshot=db_model.config_snapshot or {},
            status=DeployStatus(db_model.status),
            message=db_model.message,
            triggered_by=db_model.triggered_by,
            started_at=db_model.started_at,
            finished_at=db_model.finished_at,
            created_at=db_model.created_at,
            deleted_at=db_model.deleted_at,
        )

    @override
    def _to_db(self, domain_entity: DeployRecord) -> DeployRecordModel:
        return DeployRecordModel(
            id=domain_entity.id,
            instance_id=domain_entity.instance_id,
            revision=domain_entity.revision,
            action=domain_entity.action.value,
            image_version=domain_entity.image_version,
            replicas=domain_entity.replicas,
            config_snapshot=domain_entity.config_snapshot,
            status=domain_entity.status.value,
            message=domain_entity.message,
            triggered_by=domain_entity.triggered_by,
            started_at=domain_entity.started_at,
            finished_at=domain_entity.finished_at,
            created_at=domain_entity.created_at,
            deleted_at=domain_entity.deleted_at,
        )

    @override
    def _update_fields(self, db_model: DeployRecordModel, domain_entity: DeployRecord) -> None:
        db_model.revision = domain_entity.revision
        db_model.action = domain_entity.action.value
        db_model.image_version = domain_entity.image_version
        db_model.replicas = domain_entity.replicas
        db_model.config_snapshot = domain_entity.config_snapshot
        db_model.status = domain_entity.status.value
        db_model.message = domain_entity.message
        db_model.triggered_by = domain_entity.triggered_by
        db_model.started_at = domain_entity.started_at
        db_model.finished_at = domain_entity.finished_at
        db_model.deleted_at = domain_entity.deleted_at
