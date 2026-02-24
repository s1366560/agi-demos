"""
SQLAlchemy implementation of SubAgentTemplateRepository.

Persists SubAgent templates to PostgreSQL for the Template Marketplace.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.ports.repositories.subagent_template_repository import (
    SubAgentTemplateRepositoryPort,
)

logger = logging.getLogger(__name__)


def _generate_id() -> str:
    return str(uuid.uuid4())


class SqlSubAgentTemplateRepository(SubAgentTemplateRepositoryPort):
    """SQLAlchemy implementation of SubAgentTemplateRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _get_model(self) -> None:
        from src.infrastructure.adapters.secondary.persistence.models import (
            SubAgentTemplate as DBTemplate,
        )

        return DBTemplate

    def _row_to_dict(self, row: Any) -> dict[str, Any]:
        return {
            "id": row.id,
            "tenant_id": row.tenant_id,
            "name": row.name,
            "version": row.version,
            "display_name": row.display_name,
            "description": row.description,
            "category": row.category,
            "tags": row.tags or [],
            "system_prompt": row.system_prompt,
            "trigger_description": row.trigger_description,
            "trigger_keywords": row.trigger_keywords or [],
            "trigger_examples": row.trigger_examples or [],
            "model": row.model,
            "max_tokens": row.max_tokens,
            "temperature": row.temperature,
            "max_iterations": row.max_iterations,
            "allowed_tools": row.allowed_tools or ["*"],
            "author": row.author,
            "is_builtin": row.is_builtin,
            "is_published": row.is_published,
            "install_count": row.install_count,
            "rating": row.rating,
            "metadata": row.metadata_json,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    async def create(self, template: dict[str, Any]) -> dict[str, Any]:
        DBTemplate = self._get_model()
        template_id = template.get("id") or _generate_id()

        db_obj = DBTemplate(
            id=template_id,
            tenant_id=template["tenant_id"],
            name=template["name"],
            version=template.get("version", "1.0.0"),
            display_name=template.get("display_name"),
            description=template.get("description"),
            category=template.get("category", "general"),
            tags=template.get("tags", []),
            system_prompt=template["system_prompt"],
            trigger_description=template.get("trigger_description"),
            trigger_keywords=template.get("trigger_keywords", []),
            trigger_examples=template.get("trigger_examples", []),
            model=template.get("model", "inherit"),
            max_tokens=template.get("max_tokens", 4096),
            temperature=template.get("temperature", 0.7),
            max_iterations=template.get("max_iterations", 10),
            allowed_tools=template.get("allowed_tools", ["*"]),
            author=template.get("author"),
            is_builtin=template.get("is_builtin", False),
            is_published=template.get("is_published", True),
            install_count=template.get("install_count", 0),
            rating=template.get("rating", 0.0),
            metadata_json=template.get("metadata"),
        )

        self._session.add(db_obj)
        await self._session.flush()
        await self._session.refresh(db_obj)
        return self._row_to_dict(db_obj)

    async def get_by_id(self, template_id: str) -> dict[str, Any] | None:
        DBTemplate = self._get_model()
        query = select(DBTemplate).where(DBTemplate.id == template_id)
        result = await self._session.execute(query)
        row = result.scalar_one_or_none()
        return self._row_to_dict(row) if row else None

    async def get_by_name(
        self, tenant_id: str, name: str, version: str | None = None
    ) -> dict[str, Any] | None:
        DBTemplate = self._get_model()
        query = select(DBTemplate).where(
            DBTemplate.tenant_id == tenant_id,
            DBTemplate.name == name,
        )
        if version:
            query = query.where(DBTemplate.version == version)
        else:
            query = query.order_by(DBTemplate.created_at.desc())
        query = query.limit(1)
        result = await self._session.execute(query)
        row = result.scalar_one_or_none()
        return self._row_to_dict(row) if row else None

    async def update(self, template_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        DBTemplate = self._get_model()

        # Build update values, excluding None
        values = {}
        field_map = {
            "name": "name",
            "version": "version",
            "display_name": "display_name",
            "description": "description",
            "category": "category",
            "tags": "tags",
            "system_prompt": "system_prompt",
            "trigger_description": "trigger_description",
            "trigger_keywords": "trigger_keywords",
            "trigger_examples": "trigger_examples",
            "model": "model",
            "max_tokens": "max_tokens",
            "temperature": "temperature",
            "max_iterations": "max_iterations",
            "allowed_tools": "allowed_tools",
            "author": "author",
            "is_published": "is_published",
            "metadata": "metadata_json",
        }

        for key, col in field_map.items():
            if key in data and data[key] is not None:
                values[col] = data[key]

        if not values:
            return await self.get_by_id(template_id)

        values["updated_at"] = datetime.now(UTC)

        stmt = update(DBTemplate).where(DBTemplate.id == template_id).values(**values)
        await self._session.execute(stmt)
        await self._session.flush()
        return await self.get_by_id(template_id)

    async def delete(self, template_id: str) -> bool:
        DBTemplate = self._get_model()
        stmt = delete(DBTemplate).where(DBTemplate.id == template_id)
        result = await self._session.execute(stmt)
        return cast(bool, result.rowcount > 0)

    async def list_templates(
        self,
        tenant_id: str,
        category: str | None = None,
        tags: list[str] | None = None,
        query: str | None = None,
        published_only: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        DBTemplate = self._get_model()
        stmt = select(DBTemplate).where(DBTemplate.tenant_id == tenant_id)

        if published_only:
            stmt = stmt.where(DBTemplate.is_published.is_(True))
        if category:
            stmt = stmt.where(DBTemplate.category == category)
        if query:
            stmt = stmt.where(
                DBTemplate.name.ilike(f"%{query}%") | DBTemplate.description.ilike(f"%{query}%")
            )

        stmt = stmt.order_by(DBTemplate.install_count.desc(), DBTemplate.created_at.desc())
        stmt = stmt.limit(limit).offset(offset)

        result = await self._session.execute(stmt)
        return [self._row_to_dict(row) for row in result.scalars().all()]

    async def count_templates(
        self,
        tenant_id: str,
        category: str | None = None,
        published_only: bool = True,
    ) -> int:
        DBTemplate = self._get_model()
        stmt = select(func.count(DBTemplate.id)).where(DBTemplate.tenant_id == tenant_id)
        if published_only:
            stmt = stmt.where(DBTemplate.is_published.is_(True))
        if category:
            stmt = stmt.where(DBTemplate.category == category)

        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def list_categories(self, tenant_id: str) -> list[str]:
        DBTemplate = self._get_model()
        stmt = (
            select(DBTemplate.category)
            .where(
                DBTemplate.tenant_id == tenant_id,
                DBTemplate.is_published.is_(True),
            )
            .distinct()
            .order_by(DBTemplate.category)
        )
        result = await self._session.execute(stmt)
        return [row[0] for row in result.all()]

    async def increment_install_count(self, template_id: str) -> None:
        DBTemplate = self._get_model()
        stmt = (
            update(DBTemplate)
            .where(DBTemplate.id == template_id)
            .values(install_count=DBTemplate.install_count + 1)
        )
        await self._session.execute(stmt)
