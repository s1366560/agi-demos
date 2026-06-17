"""Tests for SqlWorkspaceRepository."""

from datetime import UTC, datetime
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.workspace.workspace import Workspace
from src.infrastructure.adapters.secondary.persistence.models import (
    Project as DBProject,
    WorkspaceMemberModel,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_repository import (
    SqlWorkspaceRepository,
)


class _ScalarRows:
    def all(self) -> list[Any]:
        return []


class _FetchResult:
    def scalars(self) -> _ScalarRows:
        return _ScalarRows()


class _RecordingSession:
    def __init__(self) -> None:
        self.statements: list[Any] = []

    async def execute(self, statement: Any) -> _FetchResult:
        self.statements.append(statement)
        return _FetchResult()


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
    async def test_list_queries_declare_deterministic_order_by(self) -> None:
        session = _RecordingSession()
        repo = SqlWorkspaceRepository(cast(AsyncSession, session))

        await repo.find_by_project("tenant-1", "project-1")
        await repo.find_visible_by_project_for_user("tenant-1", "project-1", "user-1")

        order_fragment = "ORDER BY workspaces.created_at DESC, workspaces.id ASC"
        assert order_fragment in str(session.statements[0])
        assert order_fragment in str(session.statements[1])

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
    async def test_find_visible_by_project_for_user_paginates_after_membership_filter(
        self, v2_workspace_repo: SqlWorkspaceRepository
    ) -> None:
        older_visible = make_workspace("ws-visible-old", name="Visible Old")
        inaccessible = make_workspace("ws-hidden", name="Hidden")
        newest_visible = make_workspace("ws-visible-new", name="Visible New")
        older_visible.created_at = datetime(2026, 1, 1, tzinfo=UTC)
        inaccessible.created_at = datetime(2026, 1, 2, tzinfo=UTC)
        newest_visible.created_at = datetime(2026, 1, 3, tzinfo=UTC)
        await v2_workspace_repo.save(older_visible)
        await v2_workspace_repo.save(inaccessible)
        await v2_workspace_repo.save(newest_visible)
        v2_workspace_repo._session.add_all(
            [
                WorkspaceMemberModel(
                    id="wm-visible-new",
                    workspace_id="ws-visible-new",
                    user_id="user-1",
                    role="viewer",
                    invited_by="user-1",
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                ),
                WorkspaceMemberModel(
                    id="wm-visible-old",
                    workspace_id="ws-visible-old",
                    user_id="user-1",
                    role="viewer",
                    invited_by="user-1",
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                ),
            ]
        )
        await v2_workspace_repo._session.flush()

        first_page = await v2_workspace_repo.find_visible_by_project_for_user(
            tenant_id="tenant-1",
            project_id="project-1",
            user_id="user-1",
            limit=1,
            offset=0,
        )
        second_page = await v2_workspace_repo.find_visible_by_project_for_user(
            tenant_id="tenant-1",
            project_id="project-1",
            user_id="user-1",
            limit=1,
            offset=1,
        )

        assert [item.id for item in first_page] == ["ws-visible-new"]
        assert [item.id for item in second_page] == ["ws-visible-old"]

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
