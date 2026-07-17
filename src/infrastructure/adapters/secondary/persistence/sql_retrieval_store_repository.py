"""SQLAlchemy implementation of RetrievalStoreRepository."""

from __future__ import annotations

import json
import logging
from typing import Any, cast, override

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.retrieval_store import RetrievalStore
from src.domain.ports.repositories.retrieval_store_repository import (
    RetrievalStoreRepository,
)
from src.infrastructure.adapters.secondary.common.base_repository import (
    refresh_select_statement,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Project,
    RetrievalStoreModel,
)
from src.infrastructure.security.encryption_service import get_encryption_service

logger = logging.getLogger(__name__)


class SqlRetrievalStoreRepository(RetrievalStoreRepository):
    """SQLAlchemy repository for retrieval backend registrations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._encryption = get_encryption_service()

    def _encrypt_config(self, config: dict[str, Any]) -> str | None:
        if not config:
            return None
        return self._encryption.encrypt(json.dumps(config))

    def _decrypt_config(self, encrypted: str | None) -> dict[str, Any]:
        if not encrypted:
            return {}
        try:
            data = json.loads(self._encryption.decrypt(encrypted))
            return cast(dict[str, Any], data) if isinstance(data, dict) else {}
        except Exception as exc:
            logger.warning("Failed to decrypt retrieval store config: %s", exc)
            return {}

    def _to_domain(self, model: RetrievalStoreModel | None) -> RetrievalStore | None:
        if model is None:
            return None
        return RetrievalStore(
            id=model.id,
            tenant_id=model.tenant_id,
            name=model.name,
            engine_type=model.engine_type,
            connection_config=self._decrypt_config(model.connection_config_encrypted),
            index_config=dict(model.index_config or {}),
            status=model.status,
            health_status=model.health_status,
            last_health_check=model.last_health_check,
            detected_version=model.detected_version,
            created_by=model.created_by,
            created_at=model.created_at,
            updated_at=model.updated_at,
            deleted_at=model.deleted_at,
        )

    def _apply_to_model(self, model: RetrievalStoreModel, entity: RetrievalStore) -> None:
        model.name = entity.name
        model.tenant_id = entity.tenant_id
        model.engine_type = entity.engine_type
        model.connection_config_encrypted = self._encrypt_config(entity.connection_config)
        model.index_config = entity.index_config
        model.status = entity.status
        model.health_status = entity.health_status
        model.last_health_check = entity.last_health_check
        model.detected_version = entity.detected_version
        model.created_by = entity.created_by

    @override
    async def save(self, entity: RetrievalStore) -> RetrievalStore:
        if entity.id:
            existing = await self._session.get(RetrievalStoreModel, entity.id)
            if existing is not None:
                self._apply_to_model(existing, entity)
                await self._session.flush()
                await self._session.refresh(existing)
                return self._to_domain(existing)  # type: ignore[return-value]
        model = RetrievalStoreModel(id=entity.id)
        self._apply_to_model(model, entity)
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_domain(model)  # type: ignore[return-value]

    @override
    async def find_by_id(self, tenant_id: str, store_id: str) -> RetrievalStore | None:
        query = (
            select(RetrievalStoreModel)
            .where(
                RetrievalStoreModel.id == store_id,
                RetrievalStoreModel.tenant_id == tenant_id,
                RetrievalStoreModel.deleted_at.is_(None),
            )
            .limit(1)
        )
        result = await self._session.execute(refresh_select_statement(query))
        return self._to_domain(result.scalar_one_or_none())

    @override
    async def find_by_ids(self, tenant_id: str, store_ids: list[str]) -> dict[str, RetrievalStore]:
        unique_ids = list(dict.fromkeys(store_ids))
        if not unique_ids:
            return {}
        query = select(RetrievalStoreModel).where(
            RetrievalStoreModel.id.in_(unique_ids),
            RetrievalStoreModel.tenant_id == tenant_id,
            RetrievalStoreModel.deleted_at.is_(None),
        )
        result = await self._session.execute(refresh_select_statement(query))
        stores: dict[str, RetrievalStore] = {}
        for row in result.scalars().all():
            store = self._to_domain(row)
            if store is not None:
                stores[store.id] = store
        return stores

    @override
    async def find_by_name(self, tenant_id: str, name: str) -> RetrievalStore | None:
        query = (
            select(RetrievalStoreModel)
            .where(
                RetrievalStoreModel.tenant_id == tenant_id,
                RetrievalStoreModel.name == name,
                RetrievalStoreModel.deleted_at.is_(None),
            )
            .limit(1)
        )
        result = await self._session.execute(refresh_select_statement(query))
        return self._to_domain(result.scalar_one_or_none())

    @override
    async def find_by_tenant(
        self, tenant_id: str, limit: int = 50, offset: int = 0
    ) -> list[RetrievalStore]:
        query = (
            select(RetrievalStoreModel)
            .where(
                RetrievalStoreModel.tenant_id == tenant_id,
                RetrievalStoreModel.deleted_at.is_(None),
            )
            .order_by(RetrievalStoreModel.created_at.desc(), RetrievalStoreModel.id.asc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(refresh_select_statement(query))
        return [d for m in result.scalars().all() if (d := self._to_domain(m)) is not None]

    @override
    async def count_projects_bound(self, store_id: str) -> int:
        query = select(func.count(Project.id)).where(
            Project.retrieval_store_id == store_id,
            Project.retrieval_store_id.isnot(None),
        )
        result = await self._session.execute(refresh_select_statement(query))
        return int(result.scalar() or 0)

    @override
    async def soft_delete(self, tenant_id: str, store_id: str) -> bool:
        result = await self._session.execute(
            update(RetrievalStoreModel)
            .where(
                RetrievalStoreModel.id == store_id,
                RetrievalStoreModel.tenant_id == tenant_id,
                RetrievalStoreModel.deleted_at.is_(None),
            )
            .values(deleted_at=func.now())
        )
        return bool(getattr(result, "rowcount", 0))
