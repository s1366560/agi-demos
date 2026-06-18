"""Tests for SqlWorkspaceMessageRepository."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.workspace.workspace_message import MessageSenderType, WorkspaceMessage
from src.infrastructure.adapters.secondary.persistence.sql_workspace_message_repository import (
    SqlWorkspaceMessageRepository,
)


@pytest.fixture
async def v2_workspace_message_repo(
    v2_db_session: AsyncSession,
    workspace_test_seed: dict[str, str],
) -> SqlWorkspaceMessageRepository:
    """Create a SqlWorkspaceMessageRepository for testing."""
    return SqlWorkspaceMessageRepository(v2_db_session)


def make_message(
    message_id: str,
    workspace_id: str = "workspace-1",
    parent_message_id: str | None = None,
    created_at: datetime | None = None,
    mentions: list[str] | None = None,
) -> WorkspaceMessage:
    return WorkspaceMessage(
        id=message_id,
        workspace_id=workspace_id,
        sender_id="user-1",
        sender_type=MessageSenderType.HUMAN,
        content=f"Message {message_id}",
        mentions=mentions or [],
        parent_message_id=parent_message_id,
        created_at=created_at or datetime.now(UTC),
    )


class TestSqlWorkspaceMessageRepository:
    """Tests for workspace message repository behavior."""

    @pytest.mark.asyncio
    async def test_find_by_workspace_uses_id_tie_breaker_and_cursor_boundary(
        self, v2_workspace_message_repo: SqlWorkspaceMessageRepository
    ) -> None:
        created_at = datetime(2026, 1, 1, tzinfo=UTC)
        await v2_workspace_message_repo.save(make_message("msg-c", created_at=created_at))
        await v2_workspace_message_repo.save(make_message("msg-a", created_at=created_at))
        await v2_workspace_message_repo.save(make_message("msg-b", created_at=created_at))

        messages = await v2_workspace_message_repo.find_by_workspace("workspace-1")
        before_cursor = await v2_workspace_message_repo.find_by_workspace(
            "workspace-1",
            before="msg-c",
        )

        assert [message.id for message in messages] == ["msg-a", "msg-b", "msg-c"]
        assert [message.id for message in before_cursor] == ["msg-a", "msg-b"]

    @pytest.mark.asyncio
    async def test_find_by_workspace_ignores_cross_workspace_cursor(
        self, v2_workspace_message_repo: SqlWorkspaceMessageRepository
    ) -> None:
        created_at = datetime(2026, 1, 1, tzinfo=UTC)
        await v2_workspace_message_repo.save(
            make_message("msg-other", workspace_id="workspace-other", created_at=created_at)
        )
        await v2_workspace_message_repo.save(
            make_message("msg-local", workspace_id="workspace-1", created_at=created_at)
        )

        messages = await v2_workspace_message_repo.find_by_workspace(
            "workspace-1",
            before="msg-other",
        )

        assert [message.id for message in messages] == ["msg-local"]

    @pytest.mark.asyncio
    async def test_find_thread_uses_id_tie_breaker(
        self, v2_workspace_message_repo: SqlWorkspaceMessageRepository
    ) -> None:
        created_at = datetime(2026, 1, 1, tzinfo=UTC)
        await v2_workspace_message_repo.save(
            make_message("msg-child-b", parent_message_id="msg-parent", created_at=created_at)
        )
        await v2_workspace_message_repo.save(
            make_message("msg-child-a", parent_message_id="msg-parent", created_at=created_at)
        )

        messages = await v2_workspace_message_repo.find_thread("msg-parent")

        assert [message.id for message in messages] == ["msg-child-a", "msg-child-b"]

    @pytest.mark.asyncio
    async def test_find_mentions_filters_exact_target_with_limit(
        self, v2_workspace_message_repo: SqlWorkspaceMessageRepository
    ) -> None:
        created_at = datetime(2026, 1, 1, tzinfo=UTC)
        await v2_workspace_message_repo.save(
            make_message("msg-b", created_at=created_at, mentions=["agent-1"])
        )
        await v2_workspace_message_repo.save(
            make_message("msg-a", created_at=created_at, mentions=["agent-1", "user-1"])
        )
        await v2_workspace_message_repo.save(
            make_message("msg-prefix", created_at=created_at, mentions=["agent-10"])
        )
        await v2_workspace_message_repo.save(
            make_message(
                "msg-other-workspace",
                workspace_id="workspace-other",
                created_at=created_at,
                mentions=["agent-1"],
            )
        )

        messages = await v2_workspace_message_repo.find_mentions(
            "workspace-1",
            "agent-1",
            limit=1,
        )

        assert [message.id for message in messages] == ["msg-a"]
