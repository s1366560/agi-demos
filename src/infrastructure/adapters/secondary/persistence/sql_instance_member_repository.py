"""SQLAlchemy implementation of InstanceMemberRepository using BaseRepository."""

import logging
from typing import override

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.instance.enums import InstanceRole
from src.domain.model.instance.instance import InstanceMember
from src.domain.ports.repositories.instance_member_repository import (
    InstanceMemberRepository,
)
from src.infrastructure.adapters.secondary.common.base_repository import BaseRepository
from src.infrastructure.adapters.secondary.persistence.models import (
    InstanceMemberModel,
)

logger = logging.getLogger(__name__)


class SqlInstanceMemberRepository(
    BaseRepository[InstanceMember, InstanceMemberModel], InstanceMemberRepository
):
    """SQLAlchemy implementation of InstanceMemberRepository."""

    _model_class = InstanceMemberModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @override
    async def find_by_instance(self, instance_id: str) -> list[InstanceMember]:
        return await self.list_all(instance_id=instance_id)

    @override
    async def find_by_user_and_instance(
        self, user_id: str, instance_id: str
    ) -> InstanceMember | None:
        return await self.find_one(user_id=user_id, instance_id=instance_id)

    @override
    def _to_domain(self, db_model: InstanceMemberModel | None) -> InstanceMember | None:
        if db_model is None:
            return None
        return InstanceMember(
            id=db_model.id,
            instance_id=db_model.instance_id,
            user_id=db_model.user_id,
            role=InstanceRole(db_model.role),
            created_at=db_model.created_at,
            deleted_at=db_model.deleted_at,
        )

    @override
    def _to_db(self, domain_entity: InstanceMember) -> InstanceMemberModel:
        return InstanceMemberModel(
            id=domain_entity.id,
            instance_id=domain_entity.instance_id,
            user_id=domain_entity.user_id,
            role=domain_entity.role.value,
            created_at=domain_entity.created_at,
            deleted_at=domain_entity.deleted_at,
        )

    @override
    def _update_fields(self, db_model: InstanceMemberModel, domain_entity: InstanceMember) -> None:
        db_model.role = domain_entity.role.value
        db_model.deleted_at = domain_entity.deleted_at
