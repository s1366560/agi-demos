"""SQLAlchemy implementation of InstanceTemplateRepository using BaseRepository."""

import logging
from typing import override

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.instance_template.enums import TemplateItemType
from src.domain.model.instance_template.instance_template import (
    InstanceTemplate,
    TemplateItem,
)
from src.domain.ports.repositories.instance_template_repository import (
    InstanceTemplateRepository,
)
from src.infrastructure.adapters.secondary.common.base_repository import BaseRepository
from src.infrastructure.adapters.secondary.persistence.models import (
    InstanceTemplateModel,
    TemplateItemModel,
)

logger = logging.getLogger(__name__)


class SqlInstanceTemplateRepository(
    BaseRepository[InstanceTemplate, InstanceTemplateModel], InstanceTemplateRepository
):
    """SQLAlchemy implementation of InstanceTemplateRepository."""

    _model_class = InstanceTemplateModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @override
    async def find_by_slug(self, slug: str) -> InstanceTemplate | None:
        return await self.find_one(slug=slug)

    @override
    async def find_by_tenant(
        self, tenant_id: str, limit: int = 50, offset: int = 0
    ) -> list[InstanceTemplate]:
        return await self.list_all(limit=limit, offset=offset, tenant_id=tenant_id)

    @override
    async def find_featured(self, limit: int = 20) -> list[InstanceTemplate]:
        return await self.list_all(limit=limit, is_featured=True, is_published=True)

    @override
    async def save_item(self, item: TemplateItem) -> TemplateItem:
        query = select(TemplateItemModel).where(TemplateItemModel.id == item.id).limit(1)
        result = await self._session.execute(query)
        existing = result.scalar_one_or_none()
        if existing is not None:
            existing.item_type = item.item_type.value
            existing.item_slug = item.item_slug
            existing.display_order = item.display_order
            existing.deleted_at = item.deleted_at
        else:
            db_item = TemplateItemModel(
                id=item.id,
                template_id=item.template_id,
                item_type=item.item_type.value,
                item_slug=item.item_slug,
                display_order=item.display_order,
                created_at=item.created_at,
                deleted_at=item.deleted_at,
            )
            self._session.add(db_item)
        await self._session.flush()
        return item

    @override
    async def find_items_by_template(self, template_id: str) -> list[TemplateItem]:
        query = (
            select(TemplateItemModel)
            .where(TemplateItemModel.template_id == template_id)
            .order_by(TemplateItemModel.display_order)
        )
        result = await self._session.execute(query)
        db_items = result.scalars().all()
        return [self._item_to_domain(i) for i in db_items]

    @override
    async def delete_item(self, item_id: str) -> bool:
        query = select(TemplateItemModel).where(TemplateItemModel.id == item_id)
        result = await self._session.execute(query)
        db_item = result.scalar_one_or_none()
        if db_item is not None:
            await self._session.delete(db_item)
            await self._session.flush()
            return True
        return False

    @override
    def _to_domain(self, db_model: InstanceTemplateModel | None) -> InstanceTemplate | None:
        if db_model is None:
            return None
        return InstanceTemplate(
            id=db_model.id,
            name=db_model.name,
            slug=db_model.slug,
            tenant_id=db_model.tenant_id,
            description=db_model.description,
            icon=db_model.icon,
            image_version=db_model.image_version,
            default_config=db_model.default_config or {},
            is_published=db_model.is_published,
            is_featured=db_model.is_featured,
            install_count=db_model.install_count,
            created_by=db_model.created_by,
            created_at=db_model.created_at,
            updated_at=db_model.updated_at,
            deleted_at=db_model.deleted_at,
        )

    @override
    def _to_db(self, domain_entity: InstanceTemplate) -> InstanceTemplateModel:
        return InstanceTemplateModel(
            id=domain_entity.id,
            name=domain_entity.name,
            slug=domain_entity.slug,
            tenant_id=domain_entity.tenant_id,
            description=domain_entity.description,
            icon=domain_entity.icon,
            image_version=domain_entity.image_version,
            default_config=domain_entity.default_config,
            is_published=domain_entity.is_published,
            is_featured=domain_entity.is_featured,
            install_count=domain_entity.install_count,
            created_by=domain_entity.created_by,
            created_at=domain_entity.created_at,
            updated_at=domain_entity.updated_at,
            deleted_at=domain_entity.deleted_at,
        )

    @override
    def _update_fields(
        self, db_model: InstanceTemplateModel, domain_entity: InstanceTemplate
    ) -> None:
        db_model.name = domain_entity.name
        db_model.slug = domain_entity.slug
        db_model.tenant_id = domain_entity.tenant_id
        db_model.description = domain_entity.description
        db_model.icon = domain_entity.icon
        db_model.image_version = domain_entity.image_version
        db_model.default_config = domain_entity.default_config
        db_model.is_published = domain_entity.is_published
        db_model.is_featured = domain_entity.is_featured
        db_model.install_count = domain_entity.install_count
        db_model.updated_at = domain_entity.updated_at
        db_model.deleted_at = domain_entity.deleted_at

    @staticmethod
    def _item_to_domain(db_item: TemplateItemModel) -> TemplateItem:
        return TemplateItem(
            id=db_item.id,
            template_id=db_item.template_id,
            item_type=TemplateItemType(db_item.item_type),
            item_slug=db_item.item_slug,
            display_order=db_item.display_order,
            created_at=db_item.created_at,
            deleted_at=db_item.deleted_at,
        )
