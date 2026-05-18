"""Unit tests for memory extraction endpoint input compatibility and access checks."""

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.routers.memories import (
    extract_entities,
    extract_relationships,
)
from src.infrastructure.adapters.secondary.persistence.models import Memory, Project, User


@pytest.mark.unit
class TestMemoryExtractionRouter:
    @pytest.mark.asyncio
    async def test_extract_entities_accepts_frontend_text_payload(
        self,
        test_db: AsyncSession,
        test_user: User,
        mock_graph_service,
    ) -> None:
        response = await extract_entities(
            {"text": "Alice met Bob in Paris"},
            current_user=test_user,
            db=test_db,
            graph_service=mock_graph_service,
        )

        assert [entity["name"] for entity in response["entities"]] == ["Alice", "Bob", "Paris"]
        assert response["source"] == "knowledge_graph"
        mock_graph_service.extract_entities.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_extract_relationships_accepts_frontend_text_payload(
        self,
        test_db: AsyncSession,
        test_user: User,
        mock_graph_service,
    ) -> None:
        response = await extract_relationships(
            {"text": "Alice met Bob in Paris"},
            current_user=test_user,
            db=test_db,
            graph_service=mock_graph_service,
        )

        assert response["relationships"] == [
            {
                "source": "Alice",
                "target": "Bob",
                "type": "MET",
                "relationship_type": "MET",
            }
        ]
        assert response["source"] == "knowledge_graph"
        mock_graph_service.extract_relationships.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_extract_entities_rejects_inaccessible_memory_id(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        another_user: User,
        mock_graph_service,
    ) -> None:
        memory = Memory(
            id="memory-extract-private",
            project_id=test_project_db.id,
            title="Private memory",
            content="Private Alice content",
            content_type="text",
            tags=[],
            entities=[],
            relationships=[],
            version=1,
            author_id=test_project_db.owner_id,
            collaborators=[],
            is_public=False,
            status="ENABLED",
            processing_status="COMPLETED",
            meta={},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        test_db.add(memory)
        await test_db.commit()

        with pytest.raises(HTTPException) as exc_info:
            await extract_entities(
                {"memory_id": memory.id},
                current_user=another_user,
                db=test_db,
                graph_service=mock_graph_service,
            )

        assert exc_info.value.status_code == 403
