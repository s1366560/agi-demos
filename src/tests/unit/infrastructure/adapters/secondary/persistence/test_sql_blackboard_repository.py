"""Tests for SqlBlackboardRepository."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.workspace.blackboard_post import BlackboardPost, BlackboardPostStatus
from src.domain.model.workspace.blackboard_reply import BlackboardReply
from src.infrastructure.adapters.secondary.persistence.sql_blackboard_repository import (
    SqlBlackboardRepository,
)


@pytest.fixture
async def v2_blackboard_repo(
    v2_db_session: AsyncSession,
    workspace_test_seed: dict[str, str],
) -> SqlBlackboardRepository:
    """Create a SqlBlackboardRepository for testing."""
    return SqlBlackboardRepository(v2_db_session)


def make_post(
    post_id: str,
    workspace_id: str = "workspace-1",
    title: str = "Post title",
    is_pinned: bool = False,
) -> BlackboardPost:
    return BlackboardPost(
        id=post_id,
        workspace_id=workspace_id,
        author_id="user-1",
        title=title,
        content="Post content",
        status=BlackboardPostStatus.OPEN,
        is_pinned=is_pinned,
        metadata={"type": "discussion"},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def make_reply(
    reply_id: str,
    post_id: str,
    workspace_id: str = "workspace-1",
    author_id: str = "user-1",
) -> BlackboardReply:
    return BlackboardReply(
        id=reply_id,
        post_id=post_id,
        workspace_id=workspace_id,
        author_id=author_id,
        content="Reply content",
        metadata={"kind": "reply"},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class TestSqlBlackboardRepository:
    """Tests for blackboard repository operations."""

    @pytest.mark.asyncio
    async def test_save_and_find_post_by_id(self, v2_blackboard_repo: SqlBlackboardRepository) -> None:
        post = make_post("post-1")
        await v2_blackboard_repo.save_post(post)

        found = await v2_blackboard_repo.find_post_by_id("post-1")
        assert found is not None
        assert found.id == "post-1"
        assert found.workspace_id == "workspace-1"
        assert found.title == "Post title"

    @pytest.mark.asyncio
    async def test_list_posts_by_workspace_orders_pinned_first(
        self, v2_blackboard_repo: SqlBlackboardRepository
    ) -> None:
        await v2_blackboard_repo.save_post(make_post("post-a", workspace_id="workspace-a", is_pinned=False))
        await v2_blackboard_repo.save_post(make_post("post-b", workspace_id="workspace-a", is_pinned=True))
        await v2_blackboard_repo.save_post(make_post("post-c", workspace_id="workspace-b", is_pinned=True))

        posts = await v2_blackboard_repo.list_posts_by_workspace("workspace-a")
        assert len(posts) == 2
        assert posts[0].is_pinned is True

    @pytest.mark.asyncio
    async def test_save_and_list_replies(self, v2_blackboard_repo: SqlBlackboardRepository) -> None:
        await v2_blackboard_repo.save_post(make_post("post-r"))
        await v2_blackboard_repo.save_reply(make_reply("reply-1", post_id="post-r"))
        await v2_blackboard_repo.save_reply(make_reply("reply-2", post_id="post-r", author_id="user-2"))

        replies = await v2_blackboard_repo.list_replies_by_post("post-r")
        assert len(replies) == 2
        assert replies[0].id == "reply-1"
        assert replies[1].id == "reply-2"

    @pytest.mark.asyncio
    async def test_delete_post_cascades_replies(self, v2_blackboard_repo: SqlBlackboardRepository) -> None:
        await v2_blackboard_repo.save_post(make_post("post-del"))
        await v2_blackboard_repo.save_reply(make_reply("reply-del", post_id="post-del"))

        deleted = await v2_blackboard_repo.delete_post("post-del")
        assert deleted is True
        assert await v2_blackboard_repo.find_post_by_id("post-del") is None
        assert await v2_blackboard_repo.list_replies_by_post("post-del") == []

    @pytest.mark.asyncio
    async def test_delete_reply(self, v2_blackboard_repo: SqlBlackboardRepository) -> None:
        await v2_blackboard_repo.save_post(make_post("post-del-reply"))
        await v2_blackboard_repo.save_reply(make_reply("reply-del-only", post_id="post-del-reply"))

        deleted = await v2_blackboard_repo.delete_reply("reply-del-only")
        assert deleted is True
        assert await v2_blackboard_repo.list_replies_by_post("post-del-reply") == []
