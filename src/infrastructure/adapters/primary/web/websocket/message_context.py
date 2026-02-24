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
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi import WebSocket
from sqlalchemy.ext.asyncio import AsyncSession

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
