"""Unit tests for memory edit permission checks."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import BackgroundTasks, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.routers.memories import (
    MemoryCreate,
    _check_memory_edit_permission,
    create_memory,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Memory,
    MemoryShare,
    Project,
    User,
)


def _make_memory(memory_id: str, project: Project, author: User) -> Memory:
    now = datetime.now(UTC)
    return Memory(
        id=memory_id,
        project_id=project.id,
        title="Shared memory",
        content="Editable content",
        content_type="text",
        tags=[],
        entities=[],
        relationships=[],
        version=1,
        author_id=author.id,
        collaborators=[],
        is_public=False,
        status="ENABLED",
        processing_status="COMPLETED",
        meta={},
        created_at=now,
        updated_at=now,
    )


@pytest.mark.unit
class TestMemoryEditPermission:
    @pytest.mark.asyncio
    async def test_allows_user_with_direct_edit_share(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
        another_user: User,
    ) -> None:
        memory = _make_memory("memory-edit-share-allowed", test_project_db, test_user)
        share = MemoryShare(
            id="share-edit-allowed",
            memory_id=memory.id,
            shared_with_user_id=another_user.id,
            permissions={"view": True, "edit": True},
            shared_by=test_user.id,
            created_at=datetime.now(UTC),
        )
        test_db.add_all([memory, share])
        await test_db.commit()

        await _check_memory_edit_permission(memory, another_user, test_db)

    @pytest.mark.asyncio
    async def test_rejects_user_with_view_only_share(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
        another_user: User,
    ) -> None:
        memory = _make_memory("memory-edit-share-denied", test_project_db, test_user)
        share = MemoryShare(
            id="share-view-only-denied",
            memory_id=memory.id,
            shared_with_user_id=another_user.id,
            permissions={"view": True, "edit": False},
            shared_by=test_user.id,
            created_at=datetime.now(UTC),
        )
        test_db.add_all([memory, share])
        await test_db.commit()

        with pytest.raises(HTTPException) as exc_info:
            await _check_memory_edit_permission(memory, another_user, test_db)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.unit
class TestMemoryCreateRouter:
    @pytest.mark.asyncio
    async def test_create_memory_failure_returns_sanitized_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        """Memory creation failures do not expose internal exception text."""
        graphiti_client = Mock()
        graphiti_client.driver = Mock()
        graphiti_client.driver.execute_query = AsyncMock(side_effect=RuntimeError("neo4j secret"))
        workflow_engine = Mock()
        workflow_engine.start_workflow = AsyncMock()
        monkeypatch.setattr(test_db, "commit", AsyncMock(side_effect=RuntimeError("db secret")))

        with pytest.raises(HTTPException) as exc_info:
            await create_memory(
                MemoryCreate(
                    project_id=test_project_db.id,
                    title="Memory",
                    content="Private content",
                ),
                background_tasks=BackgroundTasks(),
                current_user=test_user,
                db=test_db,
                graphiti_client=graphiti_client,
                graph_service=None,
                workflow_engine=workflow_engine,
            )

        assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert exc_info.value.detail == "Failed to create memory"
