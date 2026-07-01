"""Unit tests for memory edit permission checks."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import BackgroundTasks, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.routers.memories import (
    MemoryCreate,
    _check_memory_edit_permission,
    _get_memory_graph_context,
    create_memory,
    delete_memory,
    get_memory,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Memory,
    MemoryShare,
    Project,
    User,
    UserTenant,
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
                graph_service=None,
                workflow_engine=workflow_engine,
            )

        assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert exc_info.value.detail == "Failed to create memory"


def _graph_context_entities() -> list[dict]:
    return [
        {
            "id": "entity-1",
            "uuid": "entity-1",
            "name": "Alice",
            "type": "Person",
            "entity_type": "Person",
            "summary": "Researcher",
            "properties": {"role": "researcher"},
            "confidence": 1.0,
        },
        {
            "id": "entity-2",
            "uuid": "entity-2",
            "name": "OpenAI",
            "type": "Organization",
            "entity_type": "Organization",
            "summary": "",
            "properties": {},
            "confidence": 1.0,
        },
    ]


def _graph_context_relationships() -> list[dict]:
    return [
        {
            "id": "relationship-1",
            "uuid": "relationship-1",
            "source_id": "entity-1",
            "target_id": "entity-2",
            "source_uuid": "entity-1",
            "target_uuid": "entity-2",
            "type": "WORKS_AT",
            "relationship_type": "WORKS_AT",
            "properties": {
                "fact": "Alice works at OpenAI",
                "summary": "",
                "weight": 0.9,
                "episodes": ["memory-read-graph"],
            },
            "confidence": 0.9,
        }
    ]


@pytest.mark.unit
class TestMemoryReadRouter:
    @pytest.mark.asyncio
    async def test_loads_graph_context_from_memory_episode(self) -> None:
        graph_service = Mock()
        graph_service.get_memory_graph_context = AsyncMock(
            return_value=(_graph_context_entities(), _graph_context_relationships())
        )

        entities, relationships = await _get_memory_graph_context(
            "memory-read-graph",
            graph_service,
        )

        assert [entity["name"] for entity in entities] == ["Alice", "OpenAI"]
        assert entities[0]["id"] == "entity-1"
        assert entities[0]["properties"] == {"role": "researcher"}
        assert relationships == _graph_context_relationships()

    @pytest.mark.asyncio
    async def test_get_memory_merges_graph_context_into_response(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        memory = _make_memory("memory-read-graph", test_project_db, test_user)
        test_db.add(memory)
        await test_db.commit()

        graph_service = Mock()
        graph_service.get_memory_graph_context = AsyncMock(
            return_value=(_graph_context_entities(), _graph_context_relationships())
        )

        response = await get_memory(
            memory.id,
            current_user=test_user,
            db=test_db,
            graph_service=graph_service,
        )

        assert len(response.entities) == 2
        assert response.entities[0]["name"] == "Alice"
        assert len(response.relationships) == 1
        assert response.relationships[0]["type"] == "WORKS_AT"


@pytest.mark.unit
class TestMemoryDeletePermission:
    @pytest.mark.asyncio
    async def test_allows_tenant_admin_without_project_membership(
        self,
        monkeypatch: pytest.MonkeyPatch,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
        another_user: User,
    ) -> None:
        memory = _make_memory("memory-delete-tenant-admin", test_project_db, test_user)
        tenant_membership = UserTenant(
            id="tenant-admin-delete-memory",
            user_id=another_user.id,
            tenant_id=test_project_db.tenant_id,
            role="admin",
            permissions={"read": True, "write": True, "admin": True},
        )
        test_db.add_all([memory, tenant_membership])
        await test_db.commit()

        graph_service = Mock()
        graph_service.delete_episode_by_memory_id = AsyncMock()
        monkeypatch.setattr(
            "src.infrastructure.adapters.primary.web.routers.memories._delete_memory_chunks_for_request",
            AsyncMock(return_value=0),
        )

        response = await delete_memory(
            memory.id,
            current_user=another_user,
            db=test_db,
            graph_service=graph_service,
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT
        graph_service.delete_episode_by_memory_id.assert_awaited_once_with(memory.id)

    @pytest.mark.asyncio
    async def test_allows_superuser_without_project_or_tenant_membership(
        self,
        monkeypatch: pytest.MonkeyPatch,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
        another_user: User,
    ) -> None:
        memory = _make_memory("memory-delete-superuser", test_project_db, test_user)
        another_user.is_superuser = True
        test_db.add_all([memory, another_user])
        await test_db.commit()

        graph_service = Mock()
        graph_service.delete_episode_by_memory_id = AsyncMock()
        monkeypatch.setattr(
            "src.infrastructure.adapters.primary.web.routers.memories._delete_memory_chunks_for_request",
            AsyncMock(return_value=0),
        )

        response = await delete_memory(
            memory.id,
            current_user=another_user,
            db=test_db,
            graph_service=graph_service,
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT
        graph_service.delete_episode_by_memory_id.assert_awaited_once_with(memory.id)
