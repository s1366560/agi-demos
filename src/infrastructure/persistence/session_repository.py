"""PostgreSQL implementation of Session repository."""

from typing import Optional, List
from datetime import datetime, timedelta
import uuid

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, desc

from src.domain.model.session.entities import Session, SessionMessage, SessionStatus, SessionKind, MessageRole
from src.domain.model.session.value_objects import SessionKey
from src.domain.model.session.aggregates import SessionAggregate
from src.domain.ports.session_repository import (
    SessionRepository,
    SessionMessageRepository,
    SessionAggregateRepository,
)
from src.infrastructure.persistence.models import SessionModel, SessionMessageModel


class PostgresSessionRepository(SessionRepository):
    """PostgreSQL implementation of SessionRepository."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def save(self, session: Session) -> None:
        """Save a session."""
        existing = await self.get_by_id(session.id)
        if existing:
            # Update
            stmt = (
                SessionModel.__table__
                .update()
                .where(SessionModel.id == session.id)
                .values(
                    session_key=session.session_key.value,
                    agent_id=session.agent_id,
                    kind=session.kind.value,
                    model=session.model,
                    status=session.status.value,
                    metadata=session.metadata,
                    last_active_at=session.last_active_at,
                )
            )
            await self._session.execute(stmt)
        else:
            # Insert
            model = SessionModel(
                id=session.id,
                session_key=session.session_key.value,
                agent_id=session.agent_id,
                kind=session.kind.value,
                model=session.model,
                status=session.status.value,
                metadata=session.metadata,
                created_at=session.created_at,
                last_active_at=session.last_active_at,
            )
            self._session.add(model)

        await self._session.commit()

    async def get_by_id(self, session_id: str) -> Optional[Session]:
        """Get a session by ID."""
        stmt = select(SessionModel).where(SessionModel.id == session_id)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()

        if not model:
            return None

        return self._model_to_entity(model)

    async def get_by_session_key(self, session_key: str) -> Optional[Session]:
        """Get a session by session key."""
        stmt = select(SessionModel).where(SessionModel.session_key == session_key)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()

        if not model:
            return None

        return self._model_to_entity(model)

    async def list_sessions(
        self,
        *,
        agent_id: Optional[str] = None,
        kind: Optional[SessionKind] = None,
        status: Optional[SessionStatus] = None,
        limit: int = 50,
        offset: int = 0,
        active_minutes: Optional[int] = None,
    ) -> List[Session]:
        """List sessions with optional filters."""
        stmt = select(SessionModel)

        # Build filters
        conditions = []
        if agent_id:
            conditions.append(SessionModel.agent_id == agent_id)
        if kind:
            conditions.append(SessionModel.kind == kind.value)
        if status:
            conditions.append(SessionModel.status == status.value)
        if active_minutes:
            cutoff = datetime.utcnow() - timedelta(minutes=active_minutes)
            conditions.append(SessionModel.last_active_at >= cutoff)

        if conditions:
            stmt = stmt.where(and_(*conditions))

        # Ordering and pagination
        stmt = stmt.order_by(desc(SessionModel.last_active_at)).limit(limit).offset(offset)

        result = await self._session.execute(stmt)
        models = result.scalars().all()

        return [self._model_to_entity(model) for model in models]

    async def delete(self, session_id: str) -> bool:
        """Delete a session."""
        stmt = SessionModel.__table__.delete().where(SessionModel.id == session_id)
        result = await self._session.execute(stmt)
        await self._session.commit()
        return result.rowcount > 0

    async def count_sessions(
        self,
        *,
        agent_id: Optional[str] = None,
        kind: Optional[SessionKind] = None,
        status: Optional[SessionStatus] = None,
    ) -> int:
        """Count sessions with optional filters."""
        stmt = select(func.count()).select_from(SessionModel)

        conditions = []
        if agent_id:
            conditions.append(SessionModel.agent_id == agent_id)
        if kind:
            conditions.append(SessionModel.kind == kind.value)
        if status:
            conditions.append(SessionModel.status == status.value)

        if conditions:
            stmt = stmt.where(and_(*conditions))

        result = await self._session.execute(stmt)
        return result.scalar()

    def _model_to_entity(self, model: SessionModel) -> Session:
        """Convert model to entity."""
        return Session(
            id=model.id,
            session_key=SessionKey(model.session_key),
            agent_id=model.agent_id,
            kind=SessionKind(model.kind),
            model=model.model,
            status=SessionStatus(model.status),
            metadata=model.metadata or {},
            created_at=model.created_at,
            last_active_at=model.last_active_at,
        )


class PostgresSessionMessageRepository(SessionMessageRepository):
    """PostgreSQL implementation of SessionMessageRepository."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def save(self, message: SessionMessage) -> None:
        """Save a message."""
        existing = await self.get_by_id(message.id)
        if existing:
            # Update
            stmt = (
                SessionMessageModel.__table__
                .update()
                .where(SessionMessageModel.id == message.id)
                .values(
                    session_id=message.session_id,
                    role=message.role.value,
                    content=message.content,
                    metadata=message.metadata,
                )
            )
            await self._session.execute(stmt)
        else:
            # Insert
            model = SessionMessageModel(
                id=message.id,
                session_id=message.session_id,
                role=message.role.value,
                content=message.content,
                metadata=message.metadata,
                created_at=message.created_at,
            )
            self._session.add(model)

        await self._session.commit()

    async def get_by_id(self, message_id: str) -> Optional[SessionMessage]:
        """Get a message by ID."""
        stmt = select(SessionMessageModel).where(SessionMessageModel.id == message_id)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()

        if not model:
            return None

        return self._model_to_entity(model)

    async def get_session_messages(
        self,
        session_id: str,
        limit: int = 100,
        offset: int = 0,
        include_tools: bool = False,
    ) -> List[SessionMessage]:
        """Get messages for a session."""
        stmt = select(SessionMessageModel).where(SessionMessageModel.session_id == session_id)

        if not include_tools:
            stmt = stmt.where(SessionMessageModel.role != MessageRole.TOOL.value)

        stmt = stmt.order_by(SessionMessageModel.created_at).limit(limit).offset(offset)

        result = await self._session.execute(stmt)
        models = result.scalars().all()

        return [self._model_to_entity(model) for model in models]

    async def get_last_messages(
        self,
        session_id: str,
        limit: int = 5,
        include_tools: bool = False,
    ) -> List[SessionMessage]:
        """Get the last N messages for a session."""
        stmt = select(SessionMessageModel).where(SessionMessageModel.session_id == session_id)

        if not include_tools:
            stmt = stmt.where(SessionMessageModel.role != MessageRole.TOOL.value)

        stmt = stmt.order_by(desc(SessionMessageModel.created_at)).limit(limit)

        result = await self._session.execute(stmt)
        models = result.scalars().all()

        # Reverse to get chronological order
        messages = [self._model_to_entity(model) for model in reversed(models)]

        return messages

    async def delete_session_messages(self, session_id: str) -> int:
        """Delete all messages for a session."""
        stmt = SessionMessageModel.__table__.delete().where(SessionMessageModel.session_id == session_id)
        result = await self._session.execute(stmt)
        await self._session.commit()
        return result.rowcount

    async def count_session_messages(self, session_id: str) -> int:
        """Count messages in a session."""
        stmt = select(func.count()).select_from(SessionMessageModel).where(
            SessionMessageModel.session_id == session_id
        )
        result = await self._session.execute(stmt)
        return result.scalar()

    def _model_to_entity(self, model: SessionMessageModel) -> SessionMessage:
        """Convert model to entity."""
        return SessionMessage(
            id=model.id,
            session_id=model.session_id,
            role=MessageRole(model.role),
            content=model.content,
            metadata=model.metadata or {},
            created_at=model.created_at,
        )


class PostgresSessionAggregateRepository(SessionAggregateRepository):
    """PostgreSQL implementation of SessionAggregateRepository."""

    def __init__(self, session: AsyncSession):
        self._session = session
        self._session_repo = PostgresSessionRepository(session)
        self._message_repo = PostgresSessionMessageRepository(session)

    async def get_aggregate(self, session_id: str) -> Optional[SessionAggregate]:
        """Get a session aggregate with its messages."""
        session = await self._session_repo.get_by_id(session_id)
        if not session:
            return None

        messages = await self._message_repo.get_session_messages(session_id, limit=10000)

        return SessionAggregate(
            session=session,
            messages=messages,
        )

    async def get_aggregate_by_key(self, session_key: str) -> Optional[SessionAggregate]:
        """Get a session aggregate by session key."""
        session = await self._session_repo.get_by_session_key(session_key)
        if not session:
            return None

        return await self.get_aggregate(session.id)

    async def save_aggregate(self, aggregate: SessionAggregate) -> None:
        """Save a session aggregate (session + all messages)."""
        await self._session_repo.save(aggregate.session)

        for message in aggregate.messages:
            await self._message_repo.save(message)

        await self._session.commit()

    async def create_aggregate(
        self,
        session_key: SessionKey,
        agent_id: str,
        kind: SessionKind = SessionKind.MAIN,
        model: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> SessionAggregate:
        """Create a new session aggregate."""
        session = Session(
            id=str(uuid.uuid4()),
            session_key=session_key,
            agent_id=agent_id,
            kind=kind,
            model=model,
            status=SessionStatus.ACTIVE,
            metadata=metadata or {},
        )

        aggregate = SessionAggregate(session=session)

        await self.save_aggregate(aggregate)

        return aggregate
