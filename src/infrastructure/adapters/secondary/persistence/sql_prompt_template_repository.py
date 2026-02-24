"""SQL repository implementation for PromptTemplate."""

import logging

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.prompt_template import (
    PromptTemplate,
    TemplateVariable,
)
from src.domain.ports.repositories.prompt_template_repository import (
    PromptTemplateRepository,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    PromptTemplateModel,
)

logger = logging.getLogger(__name__)


class SqlPromptTemplateRepository(PromptTemplateRepository):
    """SQLAlchemy implementation of PromptTemplateRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, template: PromptTemplate) -> PromptTemplate:
        existing = await self._session.get(PromptTemplateModel, template.id)
        if existing:
            existing.title = template.title
            existing.content = template.content
            existing.category = template.category
            existing.variables = [  # type: ignore[assignment]
                {
                    "name": v.name,
                    "description": v.description,
                    "default_value": v.default_value,
                    "required": v.required,
                }
                for v in template.variables
            ]
            existing.is_system = template.is_system
            existing.usage_count = template.usage_count
            existing.project_id = template.project_id
        else:
            db_model = self._to_db(template)
            self._session.add(db_model)
        await self._session.flush()
        return template

    async def find_by_id(self, template_id: str) -> PromptTemplate | None:
        result = await self._session.execute(
            select(PromptTemplateModel).where(PromptTemplateModel.id == template_id)
        )
        db_model = result.scalar_one_or_none()
        return self._to_domain(db_model) if db_model else None

    async def list_by_tenant(
        self,
        tenant_id: str,
        category: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[PromptTemplate]:
        query = select(PromptTemplateModel).where(PromptTemplateModel.tenant_id == tenant_id)
        if category:
            query = query.where(PromptTemplateModel.category == category)
        query = query.order_by(PromptTemplateModel.usage_count.desc()).offset(offset).limit(limit)
        result = await self._session.execute(query)
        return [self._to_domain(m) for m in result.scalars().all()]

    async def list_by_project(
        self,
        project_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[PromptTemplate]:
        query = (
            select(PromptTemplateModel)
            .where(PromptTemplateModel.project_id == project_id)
            .order_by(PromptTemplateModel.usage_count.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(query)
        return [self._to_domain(m) for m in result.scalars().all()]

    async def delete(self, template_id: str) -> bool:
        db_model = await self._session.get(PromptTemplateModel, template_id)
        if not db_model:
            return False
        self._session.delete(db_model)
        await self._session.flush()
        return True

    async def increment_usage(self, template_id: str) -> None:
        await self._session.execute(
            update(PromptTemplateModel)
            .where(PromptTemplateModel.id == template_id)
            .values(usage_count=PromptTemplateModel.usage_count + 1)
        )
        await self._session.flush()

    def _to_domain(self, db_model: PromptTemplateModel) -> PromptTemplate:
        variables = []
        for v in db_model.variables or []:
            variables.append(
                TemplateVariable(
                    name=v.get("name", ""),  # type: ignore[attr-defined]
                    description=v.get("description", ""),  # type: ignore[attr-defined]
                    default_value=v.get("default_value", ""),  # type: ignore[attr-defined]
                    required=v.get("required", False),  # type: ignore[attr-defined]
                )
            )
        return PromptTemplate(
            id=db_model.id,
            tenant_id=db_model.tenant_id,
            project_id=db_model.project_id,
            created_by=db_model.created_by,
            title=db_model.title,
            content=db_model.content,
            category=db_model.category,
            variables=variables,
            is_system=db_model.is_system,
            usage_count=db_model.usage_count,
            created_at=db_model.created_at,
            updated_at=db_model.updated_at or db_model.created_at,
        )

    def _to_db(self, template: PromptTemplate) -> PromptTemplateModel:
        return PromptTemplateModel(
            id=template.id,
            tenant_id=template.tenant_id,
            project_id=template.project_id,
            created_by=template.created_by,
            title=template.title,
            content=template.content,
            category=template.category,
            variables=[
                {
                    "name": v.name,
                    "description": v.description,
                    "default_value": v.default_value,
                    "required": v.required,
                }
                for v in template.variables
            ],
            is_system=template.is_system,
            usage_count=template.usage_count,
        )
