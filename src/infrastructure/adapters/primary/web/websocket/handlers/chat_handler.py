"""
Chat Handlers for WebSocket

Handles send_message and stop_session message types.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast, override

from sqlalchemy import exists, select

from src.domain.model.agent.execution_backend import execution_backend_from_metadata
from src.infrastructure.adapters.primary.web.websocket.handlers.base_handler import (
    WebSocketMessageHandler,
)
from src.infrastructure.adapters.primary.web.websocket.message_context import MessageContext
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    Project,
    UserProject,
    UserTenant,
)

if TYPE_CHECKING:
    from src.application.services.agent_service import AgentService
    from src.domain.model.agent import Agent, AgentExecutionEvent, Conversation
    from src.domain.model.agent.execution.event_time import EventTimeGenerator
    from src.infrastructure.adapters.secondary.persistence.sql_agent_execution_event_repository import (
        SqlAgentExecutionEventRepository,
    )

logger = logging.getLogger(__name__)


class _RayCancelMethod(Protocol):
    def remote(self, conversation_id: str) -> object: ...


class _RayActorLike(Protocol):
    cancel: _RayCancelMethod


class _ExternalACPSessionResult(Protocol):
    session_id: str


class _ExternalACPPromptResult(Protocol):
    updates: list[dict[str, Any]]
    result: dict[str, Any] | None


class _ExternalACPService(Protocol):
    async def new_session(
        self,
        *,
        agent_id: str,
        owner_user_id: str,
        cwd: str,
        additional_directories: list[str] | None,
        mcp_servers: list[dict[str, Any]],
        tenant_id: str | None,
        field_meta: dict[str, Any] | None,
    ) -> _ExternalACPSessionResult: ...

    async def prompt(
        self,
        *,
        agent_id: str,
        session_id: str,
        owner_user_id: str,
        prompt: list[dict[str, str]],
        message_id: str | None,
        tenant_id: str | None,
    ) -> _ExternalACPPromptResult: ...

    async def close(
        self,
        *,
        agent_id: str,
        session_id: str,
        owner_user_id: str,
        tenant_id: str | None,
    ) -> object: ...


@dataclass(slots=True)
class _ExternalACPExecutionState:
    event_repo: SqlAgentExecutionEventRepository
    time_gen: EventTimeGenerator
    user_msg_id: str
    assistant_msg_id: str


_CLIENT_APP_MODEL_CONTEXT_DENYLIST = frozenset(
    {
        "active_execution_root",
        "additional_instructions",
        "attempt_worktree",
        "code_context",
        "context_type",
        "iteration_review",
        "root_goal_task_id",
        "runtime_limits",
        "task_authority",
        "verification_judge",
        "workspace_binding",
        "workspace_id",
        "workspace_planner",
        "workspace_root_override",
        "workspace_session_role",
        "workspace_tool_mode",
        "workspace_turn_type",
        "workspace_verification_integrity",
        "worktree_setup",
    }
)


def _sanitize_client_app_model_context(value: object) -> dict[str, Any] | None:
    """Drop server-owned workspace runtime fields from browser-supplied context."""
    if not isinstance(value, dict):
        return None
    sanitized = {
        key: item
        for key, item in value.items()
        if isinstance(key, str) and key not in _CLIENT_APP_MODEL_CONTEXT_DENYLIST
    }
    return sanitized or None


async def _cancel_ray_actor_chat(
    actor: _RayActorLike, conversation_id: str
) -> tuple[bool, Exception | None]:
    from src.infrastructure.adapters.secondary.ray.client import await_ray

    try:
        cancelled = bool(await await_ray(actor.cancel.remote(conversation_id)))
    except Exception as exc:
        logger.error(
            "[WS] Failed to cancel Ray actor for conversation %s: %s",
            conversation_id,
            exc,
            exc_info=True,
        )
        return False, exc

    if cancelled:
        logger.info(
            "[WS] Cancelled Ray actor execution for conversation %s",
            conversation_id,
        )
    return cancelled, None


async def _cancel_local_chat(conversation_id: str) -> bool:
    from src.application.services.agent.runtime_bootstrapper import (
        AgentRuntimeBootstrapper,
    )

    cancelled = await AgentRuntimeBootstrapper.cancel_local_chat(conversation_id)
    if cancelled:
        logger.info(
            "[WS] Cancelled local execution for conversation %s",
            conversation_id,
        )
    return cancelled


class SendMessageHandler(WebSocketMessageHandler):
    """Handle send_message: Start agent execution."""

    @property
    @override
    def message_type(self) -> str:
        return "send_message"

    @override
    async def handle(self, context: MessageContext, message: dict[str, Any]) -> None:
        """Handle send_message: Start agent execution."""
        conversation_id = message.get("conversation_id")
        user_message = message.get("message")
        message_id = message.get("message_id")
        project_id = message.get("project_id")
        preferred_language = message.get("preferred_language")
        attachment_ids = message.get("attachment_ids")
        file_metadata = message.get("file_metadata")
        forced_skill_name = message.get("forced_skill_name")
        app_model_context = _sanitize_client_app_model_context(message.get("app_model_context"))
        image_attachments = message.get("image_attachments")
        agent_id = message.get("agent_id")
        raw_mentions = message.get("mentions")
        mentions = (
            [m for m in raw_mentions if isinstance(m, str)]
            if isinstance(raw_mentions, list)
            else None
        )

        if not all([conversation_id, user_message, project_id]):
            await context.send_error(
                "Missing required fields: conversation_id, message, project_id"
            )
            return

        # Type narrowing: after the guard above, these are guaranteed to be non-None strings
        assert isinstance(conversation_id, str)
        assert isinstance(user_message, str)
        assert isinstance(project_id, str)
        if preferred_language not in {"en-US", "zh-CN"}:
            preferred_language = None

        # Fallback: when the client did not specify a per-message language,
        # use the authenticated user's stored preference.
        if preferred_language is None:
            preferred_language = await _resolve_user_preferred_language(context)

        try:
            container = context.get_scoped_container()

            # Verify conversation ownership
            conversation_repo = container.conversation_repository()
            conversation = await conversation_repo.find_by_id(conversation_id)

            if not conversation:
                await context.send_error("Conversation not found", conversation_id=conversation_id)
                return

            if not await _conversation_scope_is_active(
                context,
                conversation=conversation,
                project_id=project_id,
            ):
                await context.send_error(
                    "You do not have permission to access this conversation",
                    conversation_id=conversation_id,
                )
                return

            # Check for pending HITL requests
            from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
                SqlHITLRequestRepository,
            )

            hitl_repo = SqlHITLRequestRepository(context.db)
            pending_hitl = await hitl_repo.get_pending_by_conversation(
                conversation_id=conversation_id,
                tenant_id=context.tenant_id,
                project_id=project_id,
                exclude_expired=True,
            )

            if pending_hitl:
                from src.infrastructure.agent.hitl.utils import resolve_trusted_hitl_type

                pending_types = [
                    resolve_trusted_hitl_type(r) or r.request_type.value for r in pending_hitl
                ]
                await context.send_error(
                    f"Agent is waiting for your response. Please complete the pending "
                    f"{', '.join(pending_types)} request(s) before sending new messages.",
                    code="HITL_PENDING",
                    conversation_id=conversation_id,
                    extra={
                        "pending_requests": [
                            {
                                "request_id": r.id,
                                "request_type": resolve_trusted_hitl_type(r)
                                or r.request_type.value,
                                "question": r.question,
                            }
                            for r in pending_hitl
                        ]
                    },
                )
                return

            # Auto-subscribe this session to this conversation
            await context.connection_manager.subscribe(context.session_id, conversation_id)

            # Send acknowledgment
            ack_fields = {"conversation_id": conversation_id}
            if message_id is not None:
                ack_fields["message_id"] = message_id
            await context.send_ack("send_message", **ack_fields)

            task = asyncio.create_task(
                stream_agent_to_websocket_with_fresh_session(
                    context=context,
                    conversation_id=conversation_id,
                    user_message=user_message,
                    project_id=project_id,
                    preferred_language=preferred_language,
                    attachment_ids=attachment_ids,
                    file_metadata=file_metadata,
                    forced_skill_name=forced_skill_name,
                    app_model_context=app_model_context,
                    image_attachments=image_attachments,
                    agent_id=agent_id,
                    mentions=mentions,
                )
            )
            context.connection_manager.add_bridge_task(context.session_id, conversation_id, task)

        except Exception as e:
            logger.error(f"[WS] Error handling send_message: {e}", exc_info=True)
            await context.send_error(str(e), conversation_id=conversation_id)


class StopSessionHandler(WebSocketMessageHandler):
    """Handle stop_session: Cancel ongoing agent execution."""

    @property
    @override
    def message_type(self) -> str:
        return "stop_session"

    @override
    async def handle(self, context: MessageContext, message: dict[str, Any]) -> None:
        """Handle stop_session: Cancel ongoing agent execution."""
        conversation_id = message.get("conversation_id")

        if not conversation_id:
            await context.send_error("Missing conversation_id")
            return

        try:
            manager = context.connection_manager
            cancelled = False

            # Cancel the bridge task if exists for this session
            if (
                context.session_id in manager.bridge_tasks
                and conversation_id in manager.bridge_tasks[context.session_id]
            ):
                task = manager.bridge_tasks[context.session_id][conversation_id]
                task.cancel()
                del manager.bridge_tasks[context.session_id][conversation_id]
                cancelled = True
                logger.info(f"[WS] Cancelled stream task for conversation {conversation_id}")

            from src.infrastructure.adapters.secondary.persistence.sql_conversation_repository import (
                SqlConversationRepository,
            )
            from src.infrastructure.agent.actor.actor_manager import get_actor_if_exists

            conv_repo = SqlConversationRepository(context.db)
            conversation = await conv_repo.find_by_id(conversation_id)
            if not conversation:
                await context.send_error("Conversation not found", conversation_id=conversation_id)
                return
            if conversation.tenant_id != context.tenant_id:
                await context.send_error("Access denied", conversation_id=conversation_id)
                return

            actor = await get_actor_if_exists(
                tenant_id=conversation.tenant_id,
                project_id=conversation.project_id,
                agent_mode="default",
            )

            actor_error: Exception | None = None
            if actor:
                actor_cancelled, actor_error = await _cancel_ray_actor_chat(actor, conversation_id)
                cancelled = cancelled or actor_cancelled

            local_cancelled = await _cancel_local_chat(conversation_id)
            cancelled = cancelled or local_cancelled

            if actor_error is not None and not cancelled:
                await context.send_error(
                    "Failed to stop session",
                    code="STOP_SESSION_FAILED",
                    conversation_id=conversation_id,
                )
                return

            if not cancelled:
                await context.send_error(
                    "No running session found to stop",
                    code="SESSION_NOT_RUNNING",
                    conversation_id=conversation_id,
                )
                return

            # Send acknowledgment
            await context.send_ack("stop_session", conversation_id=conversation_id)

        except Exception as e:
            logger.error(f"[WS] Error stopping session: {e}", exc_info=True)
            await context.send_error(str(e), conversation_id=conversation_id)


# =============================================================================
# Helper Functions
# =============================================================================


async def _conversation_scope_is_active(
    context: MessageContext,
    *,
    conversation: Conversation,
    project_id: str,
) -> bool:
    """Validate the complete persisted scope for one conversation turn."""
    if (
        conversation.user_id != context.user_id
        or conversation.tenant_id != context.tenant_id
        or conversation.project_id != project_id
    ):
        return False

    statement = select(Project.id).where(
        Project.id == project_id,
        Project.tenant_id == context.tenant_id,
        exists(
            select(UserProject.id).where(
                UserProject.user_id == context.user_id,
                UserProject.project_id == project_id,
            )
        ),
        exists(
            select(UserTenant.id).where(
                UserTenant.user_id == context.user_id,
                UserTenant.tenant_id == context.tenant_id,
            )
        ),
    )
    result = await context.db.execute(refresh_select_statement(statement))
    return result.scalar_one_or_none() is not None


async def _resolve_user_preferred_language(context: MessageContext) -> str | None:
    """Look up the authenticated user's stored preferred_language.

    Returns one of {"en-US", "zh-CN"} or None if unset/invalid.
    """
    try:
        from sqlalchemy import select

        from src.infrastructure.adapters.secondary.common.base_repository import (
            refresh_select_statement,
        )
        from src.infrastructure.adapters.secondary.persistence.models import User as DBUser

        result = await context.db.execute(
            refresh_select_statement(
                select(DBUser.preferred_language).where(DBUser.id == context.user_id)
            )
        )
        value = result.scalar_one_or_none()
        if isinstance(value, str) and value in {"en-US", "zh-CN"}:
            return value
    except Exception:
        logger.debug("[WS] Failed to load user preferred_language", exc_info=True)
    return None


async def _load_external_acp_backend(
    context: MessageContext,
    *,
    agent_id: str | None,
    project_id: str,
) -> tuple[Agent, dict[str, Any]] | None:
    if not agent_id:
        return None
    registry = context.get_scoped_container().agent_registry()
    agent = await registry.get_by_id(
        agent_id,
        tenant_id=context.tenant_id,
        project_id=project_id,
    )
    if agent is None:
        return None
    backend = execution_backend_from_metadata(agent.metadata)
    if backend["type"] != "acp_external":
        return None
    return agent, dict(backend)


async def _ensure_external_acp_chat_admin(context: MessageContext) -> None:
    result = await context.db.execute(
        refresh_select_statement(
            select(UserTenant.role).where(
                UserTenant.user_id == context.user_id,
                UserTenant.tenant_id == context.tenant_id,
            )
        )
    )
    role = result.scalar_one_or_none()
    if role not in {"admin", "owner"}:
        raise PermissionError("Admin access required for external ACP agents")


def _has_external_acp_unsupported_payload(
    *,
    attachment_ids: list[str] | None,
    file_metadata: list[dict[str, Any]] | None,
    forced_skill_name: str | None,
    image_attachments: list[str] | None,
    mentions: list[str] | None,
) -> bool:
    return bool(
        attachment_ids or file_metadata or forced_skill_name or image_attachments or mentions
    )


def _resolve_external_acp_cwd(agent: Agent) -> str:
    candidates = [
        getattr(agent, "workspace_dir", None),
        getattr(getattr(agent, "workspace_config", None), "base_path", None),
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            path = Path(candidate).expanduser()
            return str(path if path.is_absolute() else Path.cwd() / path)
    return str(Path.cwd())


def _get_external_acp_update(item: dict[str, Any]) -> dict[str, Any] | None:
    update = item.get("update")
    if isinstance(update, dict):
        return update
    params = item.get("params")
    if isinstance(params, dict) and isinstance(params.get("update"), dict):
        return cast(dict[str, Any], params["update"])
    return None


_EXTERNAL_ACP_TOOL_OUTPUT_MAX_CHARS = 2000
_EXTERNAL_ACP_META_KEYS = (
    "sessionUpdate",
    "session_update",
    "toolCallId",
    "tool_call_id",
    "kind",
    "status",
    "title",
)


def _text_from_external_acp_content(content: object) -> str:
    text = ""
    if isinstance(content, list):
        text = "".join(_text_from_external_acp_content(item) for item in content)
    elif isinstance(content, dict):
        if isinstance(content.get("text"), str):
            text = str(content["text"])
        elif isinstance(content.get("content"), str):
            text = str(content["content"])
        elif (nested := content.get("content")) is not None:
            text = _text_from_external_acp_content(nested)
    elif isinstance(content, str):
        text = content
    return text


def _compact_external_acp_text(
    text: str, max_chars: int = _EXTERNAL_ACP_TOOL_OUTPUT_MAX_CHARS
) -> str:
    value = text.strip()
    if len(value) <= max_chars:
        return value
    return value[:max_chars].rstrip() + "\n... [truncated]"


def _external_acp_update_meta(update: dict[str, Any]) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    for key in _EXTERNAL_ACP_META_KEYS:
        value = update.get(key)
        if isinstance(value, str | int | float | bool):
            meta[key] = value
    return meta


def _external_acp_update_kind(update: dict[str, Any]) -> str:
    value = update.get("sessionUpdate") or update.get("session_update")
    return str(value or "")


def _external_acp_update_text(update: dict[str, Any]) -> str:
    return _text_from_external_acp_content(update.get("content"))


def _extract_external_acp_result_text(result: dict[str, Any] | None) -> str:
    if not isinstance(result, dict):
        return ""
    for key in ("content", "text", "message", "output"):
        value = result.get(key)
        if isinstance(value, str) and value:
            return value
    content = result.get("content")
    if isinstance(content, list):
        chunks = [_text_from_external_acp_content(item) for item in content]
        return "".join(chunk for chunk in chunks if chunk)
    return ""


def _external_acp_event_content(event_data: dict[str, Any]) -> str:
    content = event_data.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "".join(_text_from_external_acp_content(item) for item in content).strip()
    return ""


def _format_external_acp_prompt_with_history(
    *,
    user_message: str,
    history: list[tuple[str, str]],
    max_chars: int = 6000,
) -> str:
    if not history:
        return user_message

    lines: list[str] = []
    remaining = max_chars
    for role, content in reversed(history):
        normalized = " ".join(content.split())
        if not normalized:
            continue
        prefix = "User" if role == "user" else "Assistant"
        line = f"{prefix}: {normalized}"
        if len(line) > remaining:
            line = line[: max(0, remaining - 1)] + "…"
        lines.append(line)
        remaining -= len(line)
        if remaining <= 0:
            break
    lines.reverse()

    if not lines:
        return user_message
    return (
        "Conversation context from previous MemStack turns:\n"
        + "\n".join(lines)
        + "\n\nCurrent user request:\n"
        + user_message
    )


async def _build_external_acp_prompt_text(
    context: MessageContext,
    *,
    conversation_id: str,
    user_message: str,
) -> str:
    from src.infrastructure.adapters.secondary.persistence.sql_agent_execution_event_repository import (
        SqlAgentExecutionEventRepository,
    )

    event_repo = SqlAgentExecutionEventRepository(context.db)
    events = await event_repo.get_events(
        conversation_id=conversation_id,
        limit=24,
        event_types={"user_message", "assistant_message"},
    )
    history: list[tuple[str, str]] = []
    for event in events:
        data = event.event_data if isinstance(event.event_data, dict) else {}
        role = data.get("role")
        if role not in {"user", "assistant"}:
            role = "assistant" if event.event_type == "assistant_message" else "user"
        content = _external_acp_event_content(data)
        if content:
            history.append((str(role), content))
    return _format_external_acp_prompt_with_history(user_message=user_message, history=history[-8:])


def _new_execution_event(
    *,
    conversation_id: str,
    message_id: str,
    event_type: str,
    data: dict[str, Any],
    event_time_us: int,
    event_counter: int,
) -> AgentExecutionEvent:
    from src.domain.model.agent import AgentExecutionEvent

    enriched = {
        **data,
        "message_id": data.get("message_id") or message_id,
        "event_time_us": event_time_us,
        "event_counter": event_counter,
    }
    return AgentExecutionEvent(
        id=str(uuid.uuid4()),
        conversation_id=conversation_id,
        message_id=message_id,
        event_type=event_type,
        event_data=enriched,
        event_time_us=event_time_us,
        event_counter=event_counter,
        created_at=datetime.now(UTC),
    )


async def _broadcast_external_acp_event(
    context: MessageContext,
    *,
    conversation_id: str,
    event_type: str,
    data: dict[str, Any],
    event_time_us: int | None = None,
    event_counter: int | None = None,
) -> None:
    await context.connection_manager.broadcast_to_conversation(
        conversation_id,
        {
            "type": event_type,
            "conversation_id": conversation_id,
            "data": data,
            "timestamp": datetime.now(UTC).isoformat(),
            "event_time_us": event_time_us,
            "event_counter": event_counter,
        },
    )


async def _load_external_acp_service(
    context: MessageContext,
    *,
    acp_agent_key: str,
) -> _ExternalACPService:
    from src.infrastructure.acp.client import get_external_agent_service
    from src.infrastructure.acp.tenant_config import runtime_config_from_row
    from src.infrastructure.adapters.secondary.persistence.sql_acp_external_agent_config_repository import (
        ACPExternalAgentConfigRepository,
    )

    config_repo = ACPExternalAgentConfigRepository(context.db)
    rows = await config_repo.list_by_tenant(context.tenant_id)
    target_row = next((row for row in rows if row.agent_key == acp_agent_key), None)
    if target_row is None:
        raise ValueError("ACP external agent is not configured")
    if not target_row.enabled:
        raise ValueError("ACP external agent is disabled")

    service = get_external_agent_service()
    service.set_tenant_configs(
        context.tenant_id,
        [runtime_config_from_row(row) for row in rows],
    )
    return cast(_ExternalACPService, service)


async def _create_external_acp_user_event(
    context: MessageContext,
    *,
    conversation_id: str,
    user_message: str,
    agent: Agent,
) -> _ExternalACPExecutionState:
    from src.domain.model.agent.execution.event_time import EventTimeGenerator
    from src.infrastructure.adapters.secondary.persistence.sql_agent_execution_event_repository import (
        SqlAgentExecutionEventRepository,
    )

    event_repo = SqlAgentExecutionEventRepository(context.db)
    last_time_us, last_counter = await event_repo.get_last_event_time(conversation_id)
    time_gen = EventTimeGenerator(last_time_us=last_time_us, last_counter=last_counter)
    user_msg_id = str(uuid.uuid4())
    assistant_msg_id = str(uuid.uuid4())

    next_time_us, next_counter = time_gen.next()
    user_event = _new_execution_event(
        conversation_id=conversation_id,
        message_id=user_msg_id,
        event_type="user_message",
        data={
            "id": user_msg_id,
            "role": "user",
            "content": user_message,
            "created_at": datetime.now(UTC).isoformat(),
            "agent_id": agent.id,
        },
        event_time_us=next_time_us,
        event_counter=next_counter,
    )
    await event_repo.save(user_event)
    await context.db.commit()

    await _broadcast_external_acp_event(
        context,
        conversation_id=conversation_id,
        event_type="message",
        data={
            "id": user_msg_id,
            "role": "user",
            "content": user_message,
            "created_at": user_event.created_at.isoformat(),
            "agent_id": agent.id,
        },
        event_time_us=next_time_us,
        event_counter=next_counter,
    )
    await _broadcast_external_acp_event(
        context,
        conversation_id=conversation_id,
        event_type="text_start",
        data={"message_id": user_msg_id, "agent_id": agent.id},
    )

    return _ExternalACPExecutionState(
        event_repo=event_repo,
        time_gen=time_gen,
        user_msg_id=user_msg_id,
        assistant_msg_id=assistant_msg_id,
    )


def _append_external_acp_update_event(
    *,
    live_events: list[tuple[str, dict[str, Any]]],
    assistant_text_chunks: list[str],
    update: dict[str, Any],
    agent_id: str,
    user_msg_id: str,
) -> None:
    kind = _external_acp_update_kind(update)
    text = _external_acp_update_text(update)
    if kind == "agent_message_chunk" and text:
        assistant_text_chunks.append(text)
        live_events.append(
            (
                "text_delta",
                {
                    "delta": text,
                    "message_id": user_msg_id,
                    "agent_id": agent_id,
                    "_meta": {"acp": update},
                },
            )
        )
    elif kind == "agent_thought_chunk" and text:
        live_events.append(
            (
                "thought_delta",
                {
                    "delta": text,
                    "message_id": user_msg_id,
                    "agent_id": agent_id,
                    "_meta": {"acp": update},
                },
            )
        )
    elif kind == "tool_call":
        call_id = str(update.get("toolCallId") or update.get("tool_call_id") or uuid.uuid4())
        tool_name = str(update.get("title") or update.get("kind") or "acp_tool")
        tool_input = {
            key: value
            for key in ("title", "kind", "status")
            if isinstance((value := update.get(key)), str) and value
        }
        live_events.append(
            (
                "act",
                {
                    "tool_name": tool_name,
                    "tool_input": tool_input or {"type": "acp_tool_call"},
                    "tool_execution_id": call_id,
                    "message_id": user_msg_id,
                    "_meta": {"acp": _external_acp_update_meta(update)},
                },
            )
        )
    elif kind == "tool_call_update":
        call_id = str(update.get("toolCallId") or update.get("tool_call_id") or uuid.uuid4())
        observation = _compact_external_acp_text(text or str(update.get("status") or "updated"))
        live_events.append(
            (
                "observe",
                {
                    "tool_name": str(update.get("title") or "acp_tool"),
                    "tool_execution_id": call_id,
                    "observation": observation,
                    "result": observation,
                    "message_id": user_msg_id,
                    "_meta": {"acp": _external_acp_update_meta(update)},
                },
            )
        )


def _collect_external_acp_live_events(
    prompt_result: _ExternalACPPromptResult,
    *,
    agent: Agent,
    user_msg_id: str,
) -> tuple[str, list[tuple[str, dict[str, Any]]]]:
    assistant_text_chunks: list[str] = []
    live_events: list[tuple[str, dict[str, Any]]] = []
    for item in prompt_result.updates:
        update = _get_external_acp_update(item)
        if update is not None:
            _append_external_acp_update_event(
                live_events=live_events,
                assistant_text_chunks=assistant_text_chunks,
                update=update,
                agent_id=agent.id,
                user_msg_id=user_msg_id,
            )

    fallback_text = _extract_external_acp_result_text(prompt_result.result)
    if not assistant_text_chunks and fallback_text:
        assistant_text_chunks.append(fallback_text)
        live_events.append(
            (
                "text_delta",
                {
                    "delta": fallback_text,
                    "message_id": user_msg_id,
                    "agent_id": agent.id,
                },
            )
        )
    return "".join(assistant_text_chunks), live_events


async def _run_external_acp_prompt(
    service: _ExternalACPService,
    context: MessageContext,
    *,
    acp_agent_key: str,
    agent: Agent,
    project_id: str,
    user_message: str,
    user_msg_id: str,
) -> tuple[str, list[tuple[str, dict[str, Any]]]]:
    session_result = None
    try:
        session_result = await service.new_session(
            agent_id=acp_agent_key,
            owner_user_id=context.user_id,
            cwd=_resolve_external_acp_cwd(agent),
            additional_directories=None,
            mcp_servers=[],
            tenant_id=context.tenant_id,
            field_meta={
                "memstack": {
                    "projectId": project_id,
                    "agentDefinitionId": agent.id,
                }
            },
        )
        prompt_result = await service.prompt(
            agent_id=acp_agent_key,
            session_id=session_result.session_id,
            owner_user_id=context.user_id,
            prompt=[{"type": "text", "text": user_message}],
            message_id=user_msg_id,
            tenant_id=context.tenant_id,
        )
        return _collect_external_acp_live_events(
            prompt_result,
            agent=agent,
            user_msg_id=user_msg_id,
        )
    finally:
        if session_result is not None:
            with contextlib.suppress(Exception):
                await service.close(
                    agent_id=acp_agent_key,
                    session_id=session_result.session_id,
                    owner_user_id=context.user_id,
                    tenant_id=context.tenant_id,
                )


async def _persist_external_acp_completion(
    context: MessageContext,
    *,
    conversation_id: str,
    state: _ExternalACPExecutionState,
    live_events: list[tuple[str, dict[str, Any]]],
    assistant_text: str,
    agent: Agent,
    acp_agent_key: str,
) -> None:
    persisted_events = []
    for event_type, data in live_events:
        next_time_us, next_counter = state.time_gen.next()
        await _broadcast_external_acp_event(
            context,
            conversation_id=conversation_id,
            event_type=event_type,
            data=data,
            event_time_us=next_time_us,
            event_counter=next_counter,
        )
        if event_type not in {"text_delta", "thought_delta"}:
            persisted_events.append(
                _new_execution_event(
                    conversation_id=conversation_id,
                    message_id=state.user_msg_id,
                    event_type=event_type,
                    data=data,
                    event_time_us=next_time_us,
                    event_counter=next_counter,
                )
            )

    final_event_specs: list[tuple[str, dict[str, Any]]] = [
        (
            "text_end",
            {
                "full_text": assistant_text,
                "message_id": state.user_msg_id,
                "agent_id": agent.id,
            },
        ),
        (
            "assistant_message",
            {
                "id": state.assistant_msg_id,
                "role": "assistant",
                "content": assistant_text,
                "created_at": datetime.now(UTC).isoformat(),
                "message_id": state.user_msg_id,
                "agent_id": agent.id,
                "metadata": {
                    "source": "acp_external",
                    "acp_agent_key": acp_agent_key,
                },
            },
        ),
        (
            "complete",
            {
                "content": assistant_text,
                "message_id": state.user_msg_id,
                "assistant_message_id": state.assistant_msg_id,
                "agent_id": agent.id,
            },
        ),
    ]
    for event_type, data in final_event_specs:
        next_time_us, next_counter = state.time_gen.next()
        if event_type != "assistant_message":
            await _broadcast_external_acp_event(
                context,
                conversation_id=conversation_id,
                event_type=event_type,
                data=data,
                event_time_us=next_time_us,
                event_counter=next_counter,
            )
        persisted_events.append(
            _new_execution_event(
                conversation_id=conversation_id,
                message_id=state.user_msg_id,
                event_type=event_type,
                data=data,
                event_time_us=next_time_us,
                event_counter=next_counter,
            )
        )

    await state.event_repo.save_batch(persisted_events)
    await context.db.commit()


async def _stream_external_acp_agent_definition(
    context: MessageContext,
    conversation_id: str,
    user_message: str,
    project_id: str,
    *,
    agent: Agent,
    backend: dict[str, Any],
) -> None:
    acp_agent_key = str(backend["acp_agent_key"])
    service = await _load_external_acp_service(context, acp_agent_key=acp_agent_key)
    prompt_text = await _build_external_acp_prompt_text(
        context,
        conversation_id=conversation_id,
        user_message=user_message,
    )
    state = await _create_external_acp_user_event(
        context,
        conversation_id=conversation_id,
        user_message=user_message,
        agent=agent,
    )
    assistant_text, live_events = await _run_external_acp_prompt(
        service,
        context,
        acp_agent_key=acp_agent_key,
        agent=agent,
        project_id=project_id,
        user_message=prompt_text,
        user_msg_id=state.user_msg_id,
    )
    await _persist_external_acp_completion(
        context,
        conversation_id=conversation_id,
        state=state,
        live_events=live_events,
        assistant_text=assistant_text,
        agent=agent,
        acp_agent_key=acp_agent_key,
    )


async def stream_agent_to_websocket_with_fresh_session(
    context: MessageContext,
    conversation_id: str,
    user_message: str,
    project_id: str,
    preferred_language: str | None = None,
    attachment_ids: list[str] | None = None,
    file_metadata: list[dict[str, Any]] | None = None,
    forced_skill_name: str | None = None,
    app_model_context: dict[str, Any] | None = None,
    image_attachments: list[str] | None = None,
    agent_id: str | None = None,
    mentions: list[str] | None = None,
) -> None:
    """Create a fresh DB-scoped agent service for the long-running stream."""
    async with context.fresh_db_context() as stream_context:
        from src.configuration.factories import create_llm_client

        llm = await create_llm_client(stream_context.tenant_id)
        agent_service = stream_context.get_scoped_container().agent_service(llm)
        await stream_agent_to_websocket(
            agent_service=agent_service,
            context=stream_context,
            conversation_id=conversation_id,
            user_message=user_message,
            project_id=project_id,
            preferred_language=preferred_language,
            attachment_ids=attachment_ids,
            file_metadata=file_metadata,
            forced_skill_name=forced_skill_name,
            app_model_context=_sanitize_client_app_model_context(app_model_context),
            image_attachments=image_attachments,
            agent_id=agent_id,
            mentions=mentions,
        )


async def stream_agent_to_websocket(  # noqa: PLR0913
    agent_service: AgentService,
    context: MessageContext,
    conversation_id: str,
    user_message: str,
    project_id: str,
    preferred_language: str | None = None,
    attachment_ids: list[str] | None = None,
    file_metadata: list[dict[str, Any]] | None = None,
    forced_skill_name: str | None = None,
    app_model_context: dict[str, Any] | None = None,
    image_attachments: list[str] | None = None,
    agent_id: str | None = None,
    mentions: list[str] | None = None,
) -> None:
    """
    Stream agent events to WebSocket.

    Events are broadcast to ALL sessions subscribed to this conversation,
    allowing multiple browser tabs to receive the same messages in real-time.
    """
    manager = context.connection_manager
    event_count = 0

    try:
        external_acp_backend = await _load_external_acp_backend(
            context,
            agent_id=agent_id,
            project_id=project_id,
        )
        if external_acp_backend is not None:
            agent, backend = external_acp_backend
            await _ensure_external_acp_chat_admin(context)
            if _has_external_acp_unsupported_payload(
                attachment_ids=attachment_ids,
                file_metadata=file_metadata,
                forced_skill_name=forced_skill_name,
                image_attachments=image_attachments,
                mentions=mentions,
            ):
                raise ValueError("External ACP agents support text prompts only")
            await _stream_external_acp_agent_definition(
                context=context,
                conversation_id=conversation_id,
                user_message=user_message,
                project_id=project_id,
                agent=agent,
                backend=backend,
            )
            return

        async for event in agent_service.stream_chat_v2(
            conversation_id=conversation_id,
            user_message=user_message,
            project_id=project_id,
            user_id=context.user_id,
            tenant_id=context.tenant_id,
            preferred_language=preferred_language,
            attachment_ids=attachment_ids,
            file_metadata=file_metadata,
            forced_skill_name=forced_skill_name,
            app_model_context=_sanitize_client_app_model_context(app_model_context),
            image_attachments=image_attachments,
            agent_id=agent_id,
            mentions=mentions,
            api_auth_token=context.api_key,
        ):
            event_count += 1
            event_type = event.get("type", "unknown")
            event_data = event.get("data", {})

            logger.debug(
                f"[WS Bridge] Event #{event_count}: type={event_type}, conv={conversation_id}"
            )

            # Check if session is still subscribed
            if not manager.is_subscribed(context.session_id, conversation_id):
                logger.info(
                    f"[WS] Session {context.session_id[:8]}... unsubscribed, stopping stream"
                )
                break

            # Add conversation_id to event for routing
            ws_event = {
                "type": event.get("type"),
                "conversation_id": conversation_id,
                "data": event_data,
                "seq": event.get("id"),
                "timestamp": event.get("timestamp", datetime.now(UTC).isoformat()),
                "event_time_us": event.get("event_time_us"),
                "event_counter": event.get("event_counter"),
            }

            # Broadcast to ALL sessions subscribed to this conversation
            await manager.broadcast_to_conversation(conversation_id, ws_event)

    except asyncio.CancelledError:
        logger.info(f"[WS] Stream cancelled for conversation {conversation_id}")
    except Exception as e:
        logger.error(f"[WS] Error streaming to websocket: {e}", exc_info=True)
        # Send error only to the initiating session
        await manager.send_to_session(
            context.session_id,
            {
                "type": "error",
                "conversation_id": conversation_id,
                "data": {"message": str(e)},
            },
        )


async def stream_hitl_response_to_websocket(
    agent_service: AgentService,
    session_id: str,
    conversation_id: str,
    message_id: str | None = None,
    *,
    replay_from_db: bool = True,
    from_time_us: int | None = None,
    from_counter: int | None = None,
) -> None:
    """
    Stream agent events after HITL response to WebSocket.

    Called after a HITL response (clarification, decision, env_var)
    to continue streaming agent events to the frontend.
    """
    from src.infrastructure.adapters.primary.web.websocket.connection_manager import (
        get_connection_manager,
    )

    manager = get_connection_manager()
    event_count = 0

    try:
        logger.info(
            f"[WS HITL Bridge] Starting stream for conversation {conversation_id}, "
            f"message_id={message_id or 'ALL'}, replay_from_db={replay_from_db}, "
            f"from_time_us={from_time_us}, from_counter={from_counter}"
        )

        async for event in agent_service.connect_chat_stream(
            conversation_id=conversation_id,
            message_id=message_id,
            replay_from_db=replay_from_db,
            from_time_us=from_time_us,
            from_counter=from_counter,
        ):
            event_count += 1
            event_type = event.get("type", "unknown")
            event_data = event.get("data", {})

            # DEBUG: Log events
            if event_count <= 20:
                logger.warning(
                    f"[WS HITL Bridge] Event #{event_count}: type={event_type}, "
                    f"conv={conversation_id}"
                )

            # Check if session is still subscribed
            if not manager.is_subscribed(session_id, conversation_id):
                logger.info(f"[WS HITL] Session {session_id[:8]}... unsubscribed, stopping stream")
                break

            # Add conversation_id to event for routing
            ws_event = {
                "type": event_type,
                "conversation_id": conversation_id,
                "data": event_data,
                "seq": event.get("id"),
                "timestamp": event.get("timestamp", datetime.now(UTC).isoformat()),
                "event_time_us": event.get("event_time_us"),
                "event_counter": event.get("event_counter"),
            }

            # Broadcast to ALL sessions subscribed to this conversation
            await manager.broadcast_to_conversation(conversation_id, ws_event)

            # Stop after completion or when agent pauses for another HITL request.
            # HITL-asked events mean the agent has paused again waiting for user input,
            # so the bridge should stop and let _start_hitl_stream_bridge create a new
            # one when the user responds to the next HITL request.
            HITL_ASKED_EVENTS = {
                "clarification_asked",
                "decision_asked",
                "env_var_requested",
                "permission_asked",
            }
            if event_type in ("complete", "error"):
                logger.info(f"[WS HITL Bridge] Stream completed: type={event_type}")
                break
            if event_type in HITL_ASKED_EVENTS:
                logger.info(
                    f"[WS HITL Bridge] Agent paused for another HITL: type={event_type}, "
                    f"stopping bridge for conversation {conversation_id}"
                )
                break

    except asyncio.CancelledError:
        logger.info(f"[WS HITL] Stream cancelled for conversation {conversation_id}")
    except Exception as e:
        logger.error(f"[WS HITL] Error streaming to websocket: {e}", exc_info=True)
        await manager.send_to_session(
            session_id,
            {
                "type": "error",
                "conversation_id": conversation_id,
                "data": {"message": str(e)},
            },
        )
