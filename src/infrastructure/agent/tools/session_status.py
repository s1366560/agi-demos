"""Session status tool -- shows a status card for the current conversation.

Displays conversation metadata (title, mode, message count, timestamps)
and agent identity. Worker contributions bind a scoped repository to each
invocation.

Inspired by OpenClaw's session-status-tool.ts, adapted for MemStack's
DDD + Hexagonal Architecture.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from src.domain.model.agent.conversation.conversation import Conversation
from src.domain.ports.repositories.agent_repository import (
    ConversationRepository,
)
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import ToolInfo, tool_define
from src.infrastructure.agent.tools.result import ToolResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Generation-bound runtime
# ---------------------------------------------------------------------------

type SessionStatusSessionFactory = Callable[[], AbstractAsyncContextManager[Any]]

_session_status_runtime: ContextVar[ConversationRepository | None] = ContextVar(
    f"{__name__}.session_status_runtime",
    default=None,
)


def _repo() -> ConversationRepository:
    """Return the invocation-bound repository or raise."""
    repository = _session_status_runtime.get()
    if repository is None:
        raise RuntimeError("session_status requires a generation-bound runtime")
    return repository


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _format_duration(start: datetime, end: datetime) -> str:
    """Format the elapsed duration between two datetimes as human-readable text."""
    delta = end - start
    total_seconds = int(delta.total_seconds())

    if total_seconds < 60:
        return f"{total_seconds}s"

    minutes, seconds = divmod(total_seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds}s"

    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes}m"

    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h"


def _build_status_card(
    conversation: Conversation,
    ctx: ToolContext,
) -> str:
    """Build a formatted status card string from conversation data."""
    now = datetime.now(UTC)
    duration = _format_duration(conversation.created_at, now)

    lines: list[str] = [
        "--- Session Status ---",
        "",
        f"  Session ID   : {conversation.id}",
        f"  Title        : {conversation.title}",
        f"  Status       : {conversation.status.value}",
        f"  Mode         : {conversation.current_mode.value}",
        f"  Messages     : {conversation.message_count}",
        "",
        f"  Agent        : {ctx.agent_name}",
        f"  Project      : {conversation.project_id}",
        "",
        f"  Created      : {conversation.created_at.isoformat()}",
        f"  Duration     : {duration}",
    ]

    if conversation.updated_at:
        lines.append(f"  Last Updated : {conversation.updated_at.isoformat()}")

    if conversation.summary:
        lines.append(f"  Summary      : {conversation.summary}")

    if conversation.is_subagent_session:
        lines.append(f"  Parent Conv  : {conversation.parent_conversation_id}")

    if conversation.current_plan_id:
        lines.append(f"  Active Plan  : {conversation.current_plan_id}")

    lines.append("")
    lines.append("--- End Status ---")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# session_status tool
# ---------------------------------------------------------------------------


@tool_define(
    name="session_status",
    description=(
        "Show a status card for the current session (conversation). "
        "Displays session ID, title, status, mode, message count, "
        "agent identity, project, timestamps, and duration. "
        "Optionally accepts a conversation_id to inspect a different "
        "session in the same project."
    ),
    parameters={
        "type": "object",
        "properties": {
            "conversation_id": {
                "type": "string",
                "description": (
                    "Optional conversation ID to inspect. Defaults to the current session."
                ),
            },
        },
        "required": [],
    },
    permission="read",
    category="session",
)
async def session_status_tool(
    ctx: ToolContext,
    *,
    conversation_id: str | None = None,
) -> ToolResult:
    """Show session status card for the current or specified conversation."""
    target_id = conversation_id or ctx.conversation_id
    if not target_id:
        return ToolResult(
            output=_json({"error": "No conversation_id available in context"}),
            is_error=True,
        )

    try:
        conversation = await _repo().find_by_id(target_id)
    except Exception as exc:
        logger.warning("session_status: failed to fetch conversation: %s", exc)
        return ToolResult(
            output=_json({"error": f"Failed to fetch conversation: {exc}"}),
            is_error=True,
        )

    if conversation is None:
        return ToolResult(
            output=_json({"error": f"Conversation {target_id} not found"}),
            is_error=True,
        )

    # Enforce project scoping: cannot inspect conversations from other projects
    if ctx.project_id and conversation.project_id != ctx.project_id:
        return ToolResult(
            output=_json({"error": "Cannot access conversation from a different project"}),
            is_error=True,
        )

    status_card = _build_status_card(conversation, ctx)

    return ToolResult(
        output=status_card,
        metadata={
            "conversation_id": conversation.id,
            "status": conversation.status.value,
            "mode": conversation.current_mode.value,
            "message_count": conversation.message_count,
        },
    )


def _build_conversation_repo(session: Any) -> ConversationRepository:
    """Build the conversation repository for one invocation."""
    from src.infrastructure.adapters.secondary.persistence.sql_conversation_repository import (
        SqlConversationRepository,
    )

    return SqlConversationRepository(session)


@dataclass(frozen=True, kw_only=True, slots=True)
class _BoundSessionStatusExecutor:
    template: ToolInfo
    session_factory: SessionStatusSessionFactory

    async def __call__(self, ctx: ToolContext, **kwargs: Any) -> Any:
        async with self.session_factory() as session:
            token = _session_status_runtime.set(_build_conversation_repo(session))
            try:
                return await self.template.execute(ctx, **kwargs)
            finally:
                _session_status_runtime.reset(token)


def make_session_status_tool(
    *,
    session_factory: SessionStatusSessionFactory,
) -> ToolInfo:
    """Return a session-status ToolInfo bound to one generation's session factory."""
    return replace(
        session_status_tool,
        execute=_BoundSessionStatusExecutor(
            template=session_status_tool,
            session_factory=session_factory,
        ),
    )
