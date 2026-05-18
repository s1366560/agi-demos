"""
WebSocket Message Context

Provides a context object for message handlers with access to:
- WebSocket connection
- User/tenant/session information
- Database session
- DI container
- Connection manager
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi import WebSocket
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.configuration.di_container import DIContainer

if TYPE_CHECKING:
    from src.infrastructure.adapters.primary.web.websocket.connection_manager import (
        ConnectionManager,
    )

logger = logging.getLogger(__name__)


@dataclass
class MessageContext:
    """
    Context for WebSocket message handling.

    Provides all necessary dependencies for message handlers.
    """

    websocket: WebSocket
    user_id: str
    tenant_id: str
    session_id: str
    db: AsyncSession
    container: DIContainer
    session_factory: async_sessionmaker[AsyncSession] | None = None
    api_key: str | None = field(default=None, repr=False)

    # Lazy-loaded connection manager (to avoid circular imports)
    _connection_manager: ConnectionManager | None = None

    @property
    def connection_manager(self) -> ConnectionManager:
        """Get the connection manager instance."""
        if self._connection_manager is None:
            from src.infrastructure.adapters.primary.web.websocket.connection_manager import (
                get_connection_manager,
            )

            self._connection_manager = get_connection_manager()
        return self._connection_manager

    async def send_json(self, message: dict[str, Any]) -> None:
        """Send a JSON message to the client."""
        await self.websocket.send_json(message)

    async def send_ack(
        self, action: str, extra: dict[str, Any] | None = None, **kwargs: Any
    ) -> None:
        """Send an acknowledgment message."""
        message = {
            "type": "ack",
            "action": action,
            "timestamp": datetime.now(UTC).isoformat(),
            **kwargs,
        }
        if extra:
            message.update(extra)
        await self.send_json(message)

    async def send_error(
        self,
        message: str,
        code: str | None = None,
        conversation_id: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Send an error message."""
        data: dict[str, Any] = {"message": message}
        if code:
            data["code"] = code

        error_msg: dict[str, Any] = {
            "type": "error",
            "data": data,
        }
        if conversation_id:
            error_msg["conversation_id"] = conversation_id
        if extra:
            error_msg["data"].update(extra)

        await self.send_json(error_msg)

    def get_scoped_container(self) -> DIContainer:
        """Get a container scoped to the current database session."""
        return self.container.with_db(self.db)

    def with_db(self, db: AsyncSession) -> MessageContext:
        """Return an equivalent context bound to a different database session."""
        return MessageContext(
            websocket=self.websocket,
            user_id=self.user_id,
            tenant_id=self.tenant_id,
            session_id=self.session_id,
            db=db,
            container=self.container,
            session_factory=self.session_factory,
            api_key=self.api_key,
            _connection_manager=self._connection_manager,
        )

    @asynccontextmanager
    async def fresh_db_context(self) -> AsyncIterator[MessageContext]:
        """Yield a context with an independent database session when possible."""
        if self.session_factory is None:
            yield self
            return

        async with self.session_factory() as db:
            yield self.with_db(db)
