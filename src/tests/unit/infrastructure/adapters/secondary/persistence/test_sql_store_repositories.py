"""Regression tests for graph/retrieval store SQL repositories."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.graph_store.graph_store import GraphStore
from src.domain.model.retrieval_store import RetrievalStore
from src.infrastructure.adapters.secondary.persistence.sql_graph_store_repository import (
    SqlGraphStoreRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_retrieval_store_repository import (
    SqlRetrievalStoreRepository,
)


@pytest.mark.unit
class TestSqlGraphStoreRepository:
    @pytest.mark.asyncio
    async def test_save_updates_existing_store_without_async_lazy_load(
        self,
        db_session: AsyncSession,
        test_tenant_db,
    ) -> None:
        repo = SqlGraphStoreRepository(db_session)
        created = await repo.save(
            GraphStore(
                id="graph-store-1",
                tenant_id=test_tenant_db.id,
                name="graph-old",
                engine_type="neo4j",
                connection_config={"uri": "bolt://graph.example.com:7687", "password": "old"},
            )
        )

        updated = await repo.save(
            GraphStore(
                id=created.id,
                tenant_id=test_tenant_db.id,
                name="graph-new",
                engine_type="neo4j",
                connection_config={"uri": "bolt://graph.example.com:7687", "password": "new"},
            )
        )

        assert updated.name == "graph-new"
        assert updated.updated_at is not None
        assert updated.connection_config["password"] == "new"


@pytest.mark.unit
class TestSqlRetrievalStoreRepository:
    @pytest.mark.asyncio
    async def test_save_updates_existing_store_without_async_lazy_load(
        self,
        db_session: AsyncSession,
        test_tenant_db,
    ) -> None:
        repo = SqlRetrievalStoreRepository(db_session)
        created = await repo.save(
            RetrievalStore(
                id="retrieval-store-1",
                tenant_id=test_tenant_db.id,
                name="retrieval-old",
                engine_type="weknora_remote",
                connection_config={
                    "base_url": "https://weknora.example.com/api/v1",
                    "api_key": "old",
                    "knowledge_base_id": "kb-1",
                },
            )
        )

        updated = await repo.save(
            RetrievalStore(
                id=created.id,
                tenant_id=test_tenant_db.id,
                name="retrieval-new",
                engine_type="weknora_remote",
                connection_config={
                    "base_url": "https://weknora.example.com/api/v1",
                    "api_key": "new",
                    "knowledge_base_id": "kb-1",
                },
            )
        )

        assert updated.name == "retrieval-new"
        assert updated.updated_at is not None
        assert updated.connection_config["api_key"] == "new"
