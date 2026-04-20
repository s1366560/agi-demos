"""Tests for SqlWorkspaceRepository."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.workspace.workspace import Workspace
from src.infrastructure.adapters.secondary.persistence.models import Project as DBProject
from src.infrastructure.adapters.secondary.persistence.sql_workspace_repository import (
    SqlWorkspaceRepository,
)


@pytest.fixture
async def v2_workspace_repo(
    v2_db_session: AsyncSession,
    workspace_test_seed: dict[str, str],
) -> SqlWorkspaceRepository:
    """Create a SqlWorkspaceRepository for testing."""
    return SqlWorkspaceRepository(v2_db_session)


def make_workspace(
    workspace_id: str,
    tenant_id: str = "tenant-1",
    project_id: str = "project-1",
    name: str = "Workspace One",
) -> Workspace:
    return Workspace(
        id=workspace_id,
        tenant_id=tenant_id,
        project_id=project_id,
        name=name,
        created_by="user-1",
        description="Test workspace",
        is_archived=False,
        metadata={"source": "test"},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class TestSqlWorkspaceRepository:
    """Tests for workspace repository CRUD and queries."""

    @pytest.mark.asyncio
    async def test_save_and_find_by_id(self, v2_workspace_repo: SqlWorkspaceRepository) -> None:
        workspace = make_workspace("ws-1")
        await v2_workspace_repo.save(workspace)

        found = await v2_workspace_repo.find_by_id("ws-1")
        assert found is not None
        assert found.id == "ws-1"
        assert found.tenant_id == "tenant-1"
        assert found.project_id == "project-1"
        assert found.name == "Workspace One"

    @pytest.mark.asyncio
    async def test_find_by_project_filters_tenant_and_project(
        self, v2_workspace_repo: SqlWorkspaceRepository
    ) -> None:
        v2_workspace_repo._session.add(
            DBProject(
                id="project-2",
                tenant_id="tenant-1",
                name="Another Project",
                description="for workspace repo test",
                owner_id="user-1",
                memory_rules={},
                graph_config={},
                sandbox_type="cloud",
                sandbox_config={},
                is_public=False,
            )
        )
        await v2_workspace_repo._session.flush()

        await v2_workspace_repo.save(
            make_workspace("ws-a", tenant_id="tenant-1", project_id="project-1")
        )
        await v2_workspace_repo.save(
            make_workspace(
                "ws-b", tenant_id="tenant-1", project_id="project-1", name="Workspace Two"
            )
        )
        await v2_workspace_repo.save(
            make_workspace(
                "ws-c", tenant_id="tenant-1", project_id="project-2", name="Other Project"
            )
        )

        items = await v2_workspace_repo.find_by_project("tenant-1", "project-1")
        ids = {item.id for item in items}
        assert {"ws-a", "ws-b"}.issubset(ids)
        assert "ws-c" not in ids
        assert all(item.tenant_id == "tenant-1" for item in items)
        assert all(item.project_id == "project-1" for item in items)

    @pytest.mark.asyncio
    async def test_save_updates_existing_workspace(
        self, v2_workspace_repo: SqlWorkspaceRepository
    ) -> None:
        workspace = make_workspace("ws-upd")
        await v2_workspace_repo.save(workspace)

        updated = Workspace(
            id="ws-upd",
            tenant_id="tenant-1",
            project_id="project-1",
            name="Workspace Updated",
            created_by="user-1",
            description="Updated description",
            is_archived=True,
            metadata={"updated": True},
            created_at=workspace.created_at,
            updated_at=datetime.now(UTC),
        )
        await v2_workspace_repo.save(updated)

        found = await v2_workspace_repo.find_by_id("ws-upd")
        assert found is not None
        assert found.name == "Workspace Updated"
        assert found.is_archived is True
        assert found.metadata == {"updated": True}

    @pytest.mark.asyncio
    async def test_delete_workspace(self, v2_workspace_repo: SqlWorkspaceRepository) -> None:
        await v2_workspace_repo.save(make_workspace("ws-del"))

        deleted = await v2_workspace_repo.delete("ws-del")
        assert deleted is True
        assert await v2_workspace_repo.find_by_id("ws-del") is None
