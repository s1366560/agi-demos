"""
WebSocket Notifier for Agent Lifecycle State Changes.

This module provides a notification service for broadcasting ProjectReActAgent
lifecycle state changes to connected WebSocket clients.

Architecture:
- Decouples agent lifecycle from WebSocket implementation
- Uses ConnectionManager for broadcasting
- Supports project-scoped notifications
- Standardized message format for frontend consumption

Usage:
    notifier = WebSocketNotifier(connection_manager)
    await notifier.notify_ready(tenant_id, project_id, tool_count=10)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, Optional

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from src.infrastructure.adapters.primary.web.websocket.connection_manager import (
        ConnectionManager,
    )


class LifecycleState(str, Enum):
    """Lifecycle states for ProjectReActAgent."""

    INITIALIZING = "initializing"
    READY = "ready"
    EXECUTING = "executing"
    PAUSED = "paused"
    SHUTTING_DOWN = "shutting_down"
    ERROR = "error"


@dataclass
class LifecycleStateChangeMessage:
    """
    Message for agent lifecycle state change.

    Attributes:
        project_id: Project identifier
        tenant_id: Tenant identifier
        lifecycle_state: Current lifecycle state
        is_initialized: Whether agent is initialized
        is_active: Whether agent is active (not paused/stopped)
        tool_count: Total number of available tools (builtin + mcp)
        builtin_tool_count: Number of built-in tools
        mcp_tool_count: Number of MCP tools
        skill_count: Number of loaded skills (deprecated, use loaded_skill_count)
        total_skill_count: Total number of skills available
        loaded_skill_count: Number of skills loaded into current context
        subagent_count: Number of available subagents
        conversation_id: Current conversation ID (for executing state)
        error_message: Error message (for error state)
        timestamp: ISO format timestamp
    """

    project_id: str
    tenant_id: str
    lifecycle_state: LifecycleState
    is_initialized: bool
    is_active: bool
    tool_count: int = 0
    builtin_tool_count: int = 0
    mcp_tool_count: int = 0
    skill_count: int = 0  # Deprecated, kept for backward compatibility
    total_skill_count: int = 0
    loaded_skill_count: int = 0
    subagent_count: int = 0
    conversation_id: Optional[str] = None
    error_message: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_ws_message(self) -> Dict[str, Any]:
        """Convert to WebSocket message format."""
        data: Dict[str, Any] = {
            "lifecycle_state": self.lifecycle_state.value,
            "is_initialized": self.is_initialized,
            "is_active": self.is_active,
            "tool_count": self.tool_count,
            "builtin_tool_count": self.builtin_tool_count,
            "mcp_tool_count": self.mcp_tool_count,
            "skill_count": self.skill_count,
            "total_skill_count": self.total_skill_count,
            "loaded_skill_count": self.loaded_skill_count,
            "subagent_count": self.subagent_count,
        }

        if self.conversation_id:
            data["conversation_id"] = self.conversation_id

        if self.error_message:
            data["error_message"] = self.error_message

        return {
            "type": "lifecycle_state_change",
            "project_id": self.project_id,
            "tenant_id": self.tenant_id,
            "data": data,
            "timestamp": self.timestamp,
        }


class WebSocketNotifier:
    """
    Notifier for broadcasting agent lifecycle state changes via WebSocket.

    This class provides a clean interface for broadcasting lifecycle state
    changes to all connected clients subscribed to a specific project.

    Usage:
        notifier = WebSocketNotifier(connection_manager)
        await notifier.notify_ready(tenant_id, project_id, tool_count=10)
    """

    def __init__(self, connection_manager: ConnectionManager):
        """
        Initialize the notifier.

        Args:
            connection_manager: ConnectionManager instance for broadcasting
        """
        self._manager = connection_manager

    async def notify_lifecycle_state_change(self, message: LifecycleStateChangeMessage) -> int:
        """
        Notify subscribers of a lifecycle state change.

        Args:
            message: Lifecycle state change message

        Returns:
            Number of clients notified
        """
        try:
            ws_message = message.to_ws_message()

            # Broadcast to all subscribers of this project
            count = await self._manager.broadcast_to_project(
                tenant_id=message.tenant_id,
                project_id=message.project_id,
                message=ws_message,
            )

            if count > 0:
                logger.debug(
                    f"[WSNotifier] Notified {count} clients of lifecycle state "
                    f"{message.lifecycle_state.value} for project {message.project_id}"
                )

            return count

        except Exception as e:
            logger.error(f"[WSNotifier] Failed to notify lifecycle state: {e}")
            return 0

    async def notify_subagent_lifecycle_event(
        self,
        tenant_id: str,
        project_id: str,
        event: Dict[str, Any],
    ) -> int:
        """Notify subscribers of detached subagent lifecycle hook events."""
        try:
            ws_message = {
                "type": "subagent_lifecycle",
                "project_id": project_id,
                "tenant_id": tenant_id,
                "data": dict(event),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            count = await self._manager.broadcast_to_project(
                tenant_id=tenant_id,
                project_id=project_id,
                message=ws_message,
            )
            if count > 0:
                logger.debug(
                    "[WSNotifier] Notified %s clients of subagent lifecycle event %s for project %s",
                    count,
                    event.get("type"),
                    project_id,
                )
            return count
        except Exception as e:
            logger.error(f"[WSNotifier] Failed to notify subagent lifecycle event: {e}")
            return 0

    async def notify_initializing(self, tenant_id: str, project_id: str) -> int:
        """
        Notify that agent is initializing.

        Args:
            tenant_id: Tenant identifier
            project_id: Project identifier

        Returns:
            Number of clients notified
        """
        message = LifecycleStateChangeMessage(
            project_id=project_id,
            tenant_id=tenant_id,
            lifecycle_state=LifecycleState.INITIALIZING,
            is_initialized=False,
            is_active=False,
            tool_count=0,
            skill_count=0,
        )
        return await self.notify_lifecycle_state_change(message)

    async def notify_ready(
        self,
        tenant_id: str,
        project_id: str,
        tool_count: int = 0,
        builtin_tool_count: int = 0,
        mcp_tool_count: int = 0,
        skill_count: int = 0,
        total_skill_count: int = 0,
        loaded_skill_count: int = 0,
        subagent_count: int = 0,
    ) -> int:
        """
        Notify that agent is ready.

        Args:
            tenant_id: Tenant identifier
            project_id: Project identifier
            tool_count: Total number of available tools
            builtin_tool_count: Number of built-in tools
            mcp_tool_count: Number of MCP tools
            skill_count: Deprecated, use loaded_skill_count
            total_skill_count: Total number of skills available
            loaded_skill_count: Number of skills loaded into current context
            subagent_count: Number of available subagents

        Returns:
            Number of clients notified
        """
        message = LifecycleStateChangeMessage(
            project_id=project_id,
            tenant_id=tenant_id,
            lifecycle_state=LifecycleState.READY,
            is_initialized=True,
            is_active=True,
            tool_count=tool_count,
            builtin_tool_count=builtin_tool_count,
            mcp_tool_count=mcp_tool_count,
            skill_count=skill_count,
            total_skill_count=total_skill_count,
            loaded_skill_count=loaded_skill_count,
            subagent_count=subagent_count,
        )
        return await self.notify_lifecycle_state_change(message)

    async def notify_executing(
        self,
        tenant_id: str,
        project_id: str,
        conversation_id: str,
    ) -> int:
        """
        Notify that agent is executing a chat request.

        Args:
            tenant_id: Tenant identifier
            project_id: Project identifier
            conversation_id: Active conversation ID

        Returns:
            Number of clients notified
        """
        message = LifecycleStateChangeMessage(
            project_id=project_id,
            tenant_id=tenant_id,
            lifecycle_state=LifecycleState.EXECUTING,
            is_initialized=True,
            is_active=True,
            conversation_id=conversation_id,
        )
        return await self.notify_lifecycle_state_change(message)

    async def notify_paused(self, tenant_id: str, project_id: str) -> int:
        """
        Notify that agent is paused.

        Args:
            tenant_id: Tenant identifier
            project_id: Project identifier

        Returns:
            Number of clients notified
        """
        message = LifecycleStateChangeMessage(
            project_id=project_id,
            tenant_id=tenant_id,
            lifecycle_state=LifecycleState.PAUSED,
            is_initialized=True,
            is_active=False,
        )
        return await self.notify_lifecycle_state_change(message)

    async def notify_shutting_down(self, tenant_id: str, project_id: str) -> int:
        """
        Notify that agent is shutting down.

        Args:
            tenant_id: Tenant identifier
            project_id: Project identifier

        Returns:
            Number of clients notified
        """
        message = LifecycleStateChangeMessage(
            project_id=project_id,
            tenant_id=tenant_id,
            lifecycle_state=LifecycleState.SHUTTING_DOWN,
            is_initialized=False,
            is_active=False,
        )
        return await self.notify_lifecycle_state_change(message)

    async def notify_error(
        self,
        tenant_id: str,
        project_id: str,
        error_message: str,
    ) -> int:
        """
        Notify that agent encountered an error.

        Args:
            tenant_id: Tenant identifier
            project_id: Project identifier
            error_message: Error description

        Returns:
            Number of clients notified
        """
        message = LifecycleStateChangeMessage(
            project_id=project_id,
            tenant_id=tenant_id,
            lifecycle_state=LifecycleState.ERROR,
            is_initialized=False,
            is_active=False,
            error_message=error_message,
        )
        return await self.notify_lifecycle_state_change(message)


def get_websocket_notifier(connection_manager: ConnectionManager) -> WebSocketNotifier:
    """
    Get or create a WebSocketNotifier instance.

    Args:
        connection_manager: ConnectionManager instance

    Returns:
        WebSocketNotifier instance
    """
    return WebSocketNotifier(connection_manager)
