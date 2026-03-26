"""Tests for SqlWorkspaceMemberRepository."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.workspace.workspace_member import WorkspaceMember
from src.domain.model.workspace.workspace_role import WorkspaceRole
from src.infrastructure.adapters.secondary.persistence.sql_workspace_member_repository import (
    SqlWorkspaceMemberRepository,
)


@pytest.fixture
async def v2_workspace_member_repo(
    v2_db_session: AsyncSession,
    workspace_test_seed: dict[str, str],
) -> SqlWorkspaceMemberRepository:
    """Create a SqlWorkspaceMemberRepository for testing."""
    return SqlWorkspaceMemberRepository(v2_db_session)


def make_member(
    member_id: str,
    workspace_id: str = "workspace-1",
    user_id: str = "user-1",
    role: WorkspaceRole = WorkspaceRole.VIEWER,
) -> WorkspaceMember:
    return WorkspaceMember(
        id=member_id,
        workspace_id=workspace_id,
        user_id=user_id,
        role=role,
        invited_by="user-1",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class TestSqlWorkspaceMemberRepository:
    """Tests for workspace member repository behavior."""

    @pytest.mark.asyncio
    async def test_save_and_find_by_id(
        self, v2_workspace_member_repo: SqlWorkspaceMemberRepository
    ) -> None:
        member = make_member("wm-1")
        await v2_workspace_member_repo.save(member)

        found = await v2_workspace_member_repo.find_by_id("wm-1")
        assert found is not None
        assert found.id == "wm-1"
        assert found.workspace_id == "workspace-1"
        assert found.user_id == "user-1"
        assert found.role == WorkspaceRole.VIEWER

    @pytest.mark.asyncio
    async def test_find_by_workspace_and_user(
        self, v2_workspace_member_repo: SqlWorkspaceMemberRepository
    ) -> None:
        await v2_workspace_member_repo.save(make_member("wm-a", workspace_id="workspace-a", user_id="user-a"))
        await v2_workspace_member_repo.save(make_member("wm-b", workspace_id="workspace-a", user_id="user-b"))

        found = await v2_workspace_member_repo.find_by_workspace_and_user("workspace-a", "user-b")
        assert found is not None
        assert found.id == "wm-b"

    @pytest.mark.asyncio
    async def test_find_by_workspace_lists_members(
        self, v2_workspace_member_repo: SqlWorkspaceMemberRepository
    ) -> None:
        await v2_workspace_member_repo.save(
            make_member("wm-1", workspace_id="workspace-list", user_id="user-1")
        )
        await v2_workspace_member_repo.save(
            make_member("wm-2", workspace_id="workspace-list", user_id="user-2")
        )
        await v2_workspace_member_repo.save(
            make_member("wm-3", workspace_id="workspace-other", user_id="user-3")
        )

        members = await v2_workspace_member_repo.find_by_workspace("workspace-list")
        assert len(members) == 2
        assert {member.user_id for member in members} == {"user-1", "user-2"}

    @pytest.mark.asyncio
    async def test_save_updates_member_role(
        self, v2_workspace_member_repo: SqlWorkspaceMemberRepository
    ) -> None:
        await v2_workspace_member_repo.save(
            make_member("wm-upd", workspace_id="workspace-upd", user_id="user-upd")
        )
        updated = make_member(
            "wm-upd",
            workspace_id="workspace-upd",
            user_id="user-upd",
            role=WorkspaceRole.EDITOR,
        )
        await v2_workspace_member_repo.save(updated)

        found = await v2_workspace_member_repo.find_by_id("wm-upd")
        assert found is not None
        assert found.role == WorkspaceRole.EDITOR

    @pytest.mark.asyncio
    async def test_delete_member(self, v2_workspace_member_repo: SqlWorkspaceMemberRepository) -> None:
        await v2_workspace_member_repo.save(make_member("wm-del"))

        deleted = await v2_workspace_member_repo.delete("wm-del")
        assert deleted is True
        assert await v2_workspace_member_repo.find_by_id("wm-del") is None
