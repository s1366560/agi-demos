"""Unit tests for BlackboardService."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.model.workspace.blackboard_post import BlackboardPost
from src.domain.model.workspace.blackboard_reply import BlackboardReply
from src.domain.model.workspace.workspace import Workspace
from src.domain.model.workspace.workspace_member import WorkspaceMember
from src.domain.model.workspace.workspace_role import WorkspaceRole


def _make_workspace(
    workspace_id: str = "ws-1",
    tenant_id: str = "tenant-1",
    project_id: str = "project-1",
) -> Workspace:
    return Workspace(
        id=workspace_id,
        tenant_id=tenant_id,
        project_id=project_id,
        name="Workspace One",
        created_by="owner-1",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_member(
    user_id: str,
    role: WorkspaceRole,
    workspace_id: str = "ws-1",
) -> WorkspaceMember:
    return WorkspaceMember(
        id=f"wm-{user_id}",
        workspace_id=workspace_id,
        user_id=user_id,
        role=role,
        invited_by="owner-1",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.fixture
def mock_blackboard_repo() -> MagicMock:
    repo = MagicMock()
    repo.save_post = AsyncMock()
    repo.find_post_by_id = AsyncMock(return_value=None)
    repo.list_posts_by_workspace = AsyncMock(return_value=[])
    repo.save_reply = AsyncMock()
    repo.list_replies_by_post = AsyncMock(return_value=[])
    repo.delete_post = AsyncMock(return_value=True)
    repo.delete_reply = AsyncMock(return_value=True)
    return repo


@pytest.fixture
def mock_workspace_repo() -> MagicMock:
    repo = MagicMock()
    repo.find_by_id = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def mock_member_repo() -> MagicMock:
    repo = MagicMock()
    repo.find_by_workspace_and_user = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def blackboard_service(
    mock_blackboard_repo: MagicMock,
    mock_workspace_repo: MagicMock,
    mock_member_repo: MagicMock,
):
    from src.application.services.blackboard_service import BlackboardService

    return BlackboardService(
        blackboard_repo=mock_blackboard_repo,
        workspace_repo=mock_workspace_repo,
        workspace_member_repo=mock_member_repo,
    )


class TestBlackboardPosts:
    @pytest.mark.unit
    async def test_create_post_forbidden_for_viewer(
        self,
        blackboard_service,
        mock_workspace_repo: MagicMock,
        mock_member_repo: MagicMock,
    ) -> None:
        mock_workspace_repo.find_by_id.return_value = _make_workspace()
        mock_member_repo.find_by_workspace_and_user.return_value = _make_member(
            user_id="viewer-1",
            role=WorkspaceRole.VIEWER,
        )

        with pytest.raises(PermissionError, match="permission"):
            await blackboard_service.create_post(
                tenant_id="tenant-1",
                project_id="project-1",
                workspace_id="ws-1",
                actor_user_id="viewer-1",
                title="Need help",
                content="Can someone help?",
            )

    @pytest.mark.unit
    async def test_pin_and_unpin_post_success(
        self,
        blackboard_service,
        mock_blackboard_repo: MagicMock,
        mock_workspace_repo: MagicMock,
        mock_member_repo: MagicMock,
    ) -> None:
        post = BlackboardPost(
            id="post-1",
            workspace_id="ws-1",
            author_id="editor-1",
            title="Important",
            content="Read this",
            is_pinned=False,
            created_at=datetime.now(UTC),
        )
        mock_workspace_repo.find_by_id.return_value = _make_workspace()
        mock_member_repo.find_by_workspace_and_user.return_value = _make_member(
            user_id="editor-1",
            role=WorkspaceRole.EDITOR,
        )
        mock_blackboard_repo.find_post_by_id.return_value = post
        mock_blackboard_repo.save_post.side_effect = lambda saved: saved

        pinned = await blackboard_service.pin_post(
            tenant_id="tenant-1",
            project_id="project-1",
            workspace_id="ws-1",
            post_id="post-1",
            actor_user_id="editor-1",
        )
        assert pinned.is_pinned is True

        unpinned = await blackboard_service.unpin_post(
            tenant_id="tenant-1",
            project_id="project-1",
            workspace_id="ws-1",
            post_id="post-1",
            actor_user_id="editor-1",
        )

        assert pinned.id == "post-1"
        assert unpinned.is_pinned is False
        assert mock_blackboard_repo.save_post.await_count == 2


class TestBlackboardReplies:
    @pytest.mark.unit
    async def test_update_reply_not_found(
        self,
        blackboard_service,
        mock_blackboard_repo: MagicMock,
        mock_workspace_repo: MagicMock,
        mock_member_repo: MagicMock,
    ) -> None:
        post = BlackboardPost(
            id="post-1",
            workspace_id="ws-1",
            author_id="editor-1",
            title="Thread",
            content="Body",
            created_at=datetime.now(UTC),
        )
        mock_workspace_repo.find_by_id.return_value = _make_workspace()
        mock_member_repo.find_by_workspace_and_user.return_value = _make_member(
            user_id="editor-1",
            role=WorkspaceRole.EDITOR,
        )
        mock_blackboard_repo.find_post_by_id.return_value = post
        mock_blackboard_repo.list_replies_by_post.return_value = []

        with pytest.raises(ValueError, match="not found"):
            await blackboard_service.update_reply(
                tenant_id="tenant-1",
                project_id="project-1",
                workspace_id="ws-1",
                post_id="post-1",
                reply_id="reply-missing",
                actor_user_id="editor-1",
                content="updated",
            )

    @pytest.mark.unit
    async def test_list_replies_requires_membership(
        self,
        blackboard_service,
        mock_blackboard_repo: MagicMock,
        mock_workspace_repo: MagicMock,
        mock_member_repo: MagicMock,
    ) -> None:
        post = BlackboardPost(
            id="post-1",
            workspace_id="ws-1",
            author_id="editor-1",
            title="Thread",
            content="Body",
            created_at=datetime.now(UTC),
        )
        mock_workspace_repo.find_by_id.return_value = _make_workspace()
        mock_member_repo.find_by_workspace_and_user.return_value = None
        mock_blackboard_repo.find_post_by_id.return_value = post
        mock_blackboard_repo.list_replies_by_post.return_value = [
            BlackboardReply(
                id="reply-1",
                post_id="post-1",
                workspace_id="ws-1",
                author_id="editor-1",
                content="hello",
                created_at=datetime.now(UTC),
            )
        ]

        with pytest.raises(PermissionError, match="member"):
            await blackboard_service.list_replies(
                tenant_id="tenant-1",
                project_id="project-1",
                workspace_id="ws-1",
                post_id="post-1",
                actor_user_id="viewer-1",
            )
