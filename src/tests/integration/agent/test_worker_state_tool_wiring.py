"""Integration tests for _add_session_comm_tools and _add_canvas_tools wiring.

Verifies that agent_worker_state helper functions correctly register
session comm and canvas tools into the tool dictionary, and degrade
gracefully on import/setup failures.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import DateTime, Integer, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from src.domain.model.agent import Message, MessageRole, MessageType


class _LocalBase(DeclarativeBase):
    pass


class _LocalConversation(_LocalBase):
    __tablename__ = "test_conversations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class _LocalMessage(_LocalBase):
    __tablename__ = "test_messages"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    message_type: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class _LocalConversationRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_id(self, conversation_id: str):  # type: ignore[no-untyped-def]
        from src.domain.model.agent import Conversation, ConversationStatus

        result = await self._session.execute(
            select(_LocalConversation).where(_LocalConversation.id == conversation_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return Conversation(
            id=row.id,
            project_id=row.project_id,
            tenant_id=row.tenant_id,
            user_id=row.user_id,
            title=row.title,
            status=ConversationStatus(row.status),
            message_count=row.message_count,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            updated_at=row.updated_at,
        )

    async def save(self, conversation):  # type: ignore[no-untyped-def]
        result = await self._session.execute(
            select(_LocalConversation).where(_LocalConversation.id == conversation.id)
        )
        row = result.scalar_one()
        row.message_count = conversation.message_count
        row.updated_at = conversation.updated_at
        await self._session.flush()
        return conversation


class _LocalMessageRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, message: Message) -> Message:
        self._session.add(
            _LocalMessage(
                id=message.id,
                conversation_id=message.conversation_id,
                role=message.role.value,
                content=message.content,
                message_type=message.message_type.value,
                created_at=message.created_at,
            )
        )
        await self._session.flush()
        return message

    async def list_by_conversation(
        self,
        conversation_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Message]:
        result = await self._session.execute(
            select(_LocalMessage)
            .where(_LocalMessage.conversation_id == conversation_id)
            .order_by(_LocalMessage.created_at.asc())
            .offset(offset)
            .limit(limit)
        )
        rows = result.scalars().all()
        return [
            Message(
                id=row.id,
                conversation_id=row.conversation_id,
                role=MessageRole(row.role),
                content=row.content,
                message_type=MessageType(row.message_type),
                created_at=row.created_at,
            )
            for row in rows
        ]


@pytest.fixture
async def session_comm_sqlite_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(_LocalBase.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.mark.integration
class TestSessionCommToolsWiring:
    """Tests for _add_session_comm_tools adding tools to the dict."""

    async def test_session_comm_tools_added(self) -> None:
        """Tools are added to the dict after configure_session_comm.

        Arrange: Patch imports to provide mock objects.
        Act: Call _add_session_comm_tools.
        Assert: Three tool keys present in tools dict.
        """
        # Arrange
        mock_session = MagicMock()
        mock_session_factory = MagicMock(return_value=mock_session)

        mock_list_tool = MagicMock()
        mock_list_tool.name = "sessions_list"
        mock_history_tool = MagicMock()
        mock_history_tool.name = "sessions_history"
        mock_send_tool = MagicMock()
        mock_send_tool.name = "sessions_send"
        mock_configure = MagicMock()
        mock_service_cls = MagicMock()

        tools: dict[str, Any] = {}

        with (
            patch(
                "src.application.services.session_comm_service.SessionCommService",
                mock_service_cls,
            ),
            patch(
                "src.infrastructure.adapters.secondary.persistence.database.async_session_factory",
                mock_session_factory,
            ),
            patch(
                "src.infrastructure.adapters.secondary.persistence.sql_conversation_repository.SqlConversationRepository",
                create=True,
            ),
            patch(
                "src.infrastructure.adapters.secondary.persistence.sql_agent_execution_event_repository.SqlAgentExecutionEventRepository",
                create=True,
            ),
            patch(
                "src.infrastructure.adapters.secondary.persistence.sql_message_repository.SqlMessageRepository",
                create=True,
            ),
            patch(
                "src.infrastructure.agent.tools.session_comm_tools.configure_session_comm",
                mock_configure,
            ),
            patch(
                "src.infrastructure.agent.tools.session_comm_tools.sessions_list_tool",
                mock_list_tool,
            ),
            patch(
                "src.infrastructure.agent.tools.session_comm_tools.sessions_history_tool",
                mock_history_tool,
            ),
            patch(
                "src.infrastructure.agent.tools.session_comm_tools.sessions_send_tool",
                mock_send_tool,
            ),
        ):
            # The function uses lazy imports, so we import here
            from src.infrastructure.agent.state.agent_worker_state import (
                _add_session_comm_tools,
            )

            # Act
            _add_session_comm_tools(tools, project_id="proj-001", redis_client=MagicMock())

        # Assert
        assert "sessions_list" in tools
        assert "sessions_history" in tools
        assert "sessions_send" in tools
        assert len(tools) == 3
        assert mock_service_cls.call_args is not None
        assert "agent_execution_event_repo" in mock_service_cls.call_args.kwargs

    async def test_session_comm_tools_graceful_failure(self) -> None:
        """Import failure is caught silently; tools dict unchanged.

        Arrange: Patch lazy import to raise ImportError.
        Act: Call _add_session_comm_tools.
        Assert: tools dict is empty, no exception raised.
        """
        # Arrange
        tools: dict[str, Any] = {}

        # Patch sys.modules so the lazy import inside
        # _add_session_comm_tools raises ImportError.
        with patch.dict(
            "sys.modules",
            {
                "src.application.services.session_comm_service": None,
            },
        ):
            import src.infrastructure.agent.state.agent_worker_state as mod

            mod._add_session_comm_tools(tools, project_id="proj-001", redis_client=MagicMock())

        # Assert -- no error raised, tools still empty
        assert len(tools) == 0


@pytest.mark.integration
class TestSessionCommPersistenceBoundary:
    """PR2 persistence-boundary tests using a minimal local SQLite schema."""

    async def test_send_to_session_increments_conversation_message_count(
        self,
        session_comm_sqlite_session: AsyncSession,
    ) -> None:
        from src.application.services.session_comm_service import SessionCommService

        session_comm_sqlite_session.add(
            _LocalConversation(
                id="pr2-conv",
                project_id="pr2-proj",
                tenant_id="pr2-tenant",
                user_id="pr2-user",
                title="PR2 Test Conversation",
                status="active",
                message_count=3,
            )
        )
        await session_comm_sqlite_session.flush()

        conv_repo = _LocalConversationRepo(session_comm_sqlite_session)
        msg_repo = _LocalMessageRepo(session_comm_sqlite_session)
        svc = SessionCommService(conversation_repo=conv_repo, message_repo=msg_repo)
        await svc.send_to_session("pr2-proj", "pr2-conv", "hello from peer agent")
        await session_comm_sqlite_session.commit()

        result = await session_comm_sqlite_session.execute(
            select(_LocalConversation).where(_LocalConversation.id == "pr2-conv")
        )
        updated_conv = result.scalar_one()
        assert updated_conv.message_count == 4

    async def test_send_to_session_updates_conversation_updated_at(
        self,
        session_comm_sqlite_session: AsyncSession,
    ) -> None:
        from src.application.services.session_comm_service import SessionCommService

        session_comm_sqlite_session.add(
            _LocalConversation(
                id="pr2-conv-2",
                project_id="pr2-proj-2",
                tenant_id="pr2-tenant-2",
                user_id="pr2-user-2",
                title="PR2 Test Conversation 2",
                status="active",
                message_count=0,
                updated_at=None,
            )
        )
        await session_comm_sqlite_session.flush()

        conv_repo = _LocalConversationRepo(session_comm_sqlite_session)
        msg_repo = _LocalMessageRepo(session_comm_sqlite_session)
        svc = SessionCommService(conversation_repo=conv_repo, message_repo=msg_repo)
        await svc.send_to_session("pr2-proj-2", "pr2-conv-2", "ping")
        await session_comm_sqlite_session.commit()

        result = await session_comm_sqlite_session.execute(
            select(_LocalConversation).where(_LocalConversation.id == "pr2-conv-2")
        )
        updated_conv = result.scalar_one()
        assert updated_conv.updated_at is not None

    async def test_sessions_history_reflects_incremented_message_count_after_send(
        self,
        session_comm_sqlite_session: AsyncSession,
    ) -> None:
        from src.application.services.session_comm_service import SessionCommService

        session_comm_sqlite_session.add(
            _LocalConversation(
                id="pr2-conv-3",
                project_id="pr2-proj-3",
                tenant_id="pr2-tenant-3",
                user_id="pr2-user-3",
                title="PR2 Test Conversation 3",
                status="active",
                message_count=1,
            )
        )
        session_comm_sqlite_session.add(
            _LocalMessage(
                id="pr2-msg-existing",
                conversation_id="pr2-conv-3",
                role="user",
                content="original message",
                message_type="text",
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        await session_comm_sqlite_session.flush()

        conv_repo = _LocalConversationRepo(session_comm_sqlite_session)
        msg_repo = _LocalMessageRepo(session_comm_sqlite_session)
        svc = SessionCommService(conversation_repo=conv_repo, message_repo=msg_repo)

        await svc.send_to_session("pr2-proj-3", "pr2-conv-3", "peer message")
        await session_comm_sqlite_session.commit()

        history = await svc.get_session_history("pr2-proj-3", "pr2-conv-3")
        assert history["conversation"]["message_count"] == 2
        assert history["conversation"]["updated_at"] is not None


@pytest.mark.integration
class TestCanvasToolsWiring:
    """Tests for _add_canvas_tools adding tools to the dict."""

    async def test_canvas_tools_added(self) -> None:
        """Canvas tools are added to the dict after configure_canvas.

        Arrange: Patch canvas imports to provide mock objects.
        Act: Call _add_canvas_tools.
        Assert: Three canvas tool keys present in tools dict.
        """
        # Arrange
        mock_manager_cls = MagicMock()
        mock_manager = MagicMock()
        mock_manager_cls.return_value = mock_manager

        mock_create = MagicMock()
        mock_create.name = "canvas_create"
        mock_update = MagicMock()
        mock_update.name = "canvas_update"
        mock_delete = MagicMock()
        mock_delete.name = "canvas_delete"
        mock_create_interactive = MagicMock()
        mock_create_interactive.name = "canvas_create_interactive"
        mock_configure = MagicMock()

        tools: dict[str, Any] = {}

        with (
            patch(
                "src.infrastructure.agent.canvas.manager.CanvasManager",
                mock_manager_cls,
            ),
            patch(
                "src.infrastructure.agent.canvas.tools.canvas_create",
                mock_create,
            ),
            patch(
                "src.infrastructure.agent.canvas.tools.canvas_update",
                mock_update,
            ),
            patch(
                "src.infrastructure.agent.canvas.tools.canvas_delete",
                mock_delete,
            ),
            patch(
                "src.infrastructure.agent.canvas.tools.canvas_create_interactive",
                mock_create_interactive,
            ),
            patch(
                "src.infrastructure.agent.canvas.tools.configure_canvas",
                mock_configure,
            ),
        ):
            from src.infrastructure.agent.state.agent_worker_state import (
                _add_canvas_tools,
            )

            # Act
            _add_canvas_tools(tools)

        # Assert
        assert "canvas_create" in tools
        assert "canvas_create_interactive" in tools
        assert "canvas_update" in tools
        assert "canvas_delete" in tools
        assert len(tools) == 4
        mock_configure.assert_called_once_with(mock_manager)

    async def test_canvas_tools_graceful_failure(self) -> None:
        """Import failure is caught silently; tools dict unchanged.

        Arrange: Patch sys.modules to make canvas import fail.
        Act: Call _add_canvas_tools.
        Assert: tools dict is empty, no exception raised.
        """
        # Arrange
        tools: dict[str, Any] = {}

        with patch.dict(
            "sys.modules",
            {
                "src.infrastructure.agent.canvas.manager": None,
            },
        ):
            import src.infrastructure.agent.state.agent_worker_state as mod

            # Act
            mod._add_canvas_tools(tools)

        # Assert -- no error raised, tools still empty
        assert len(tools) == 0
