"""Channel Event Bridge - forwards agent events to bound channel adapters.

This module implements the Event Bridge pattern: a post-processing layer that
subscribes to agent events for channel-bound conversations and routes relevant
events to the appropriate channel adapter (Feishu, Slack, etc.).

The agent core remains unchanged; the bridge is purely additive.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Dict, List, Optional

from src.domain.model.channels.message import ChannelAdapter

logger = logging.getLogger(__name__)

# Type alias for event handler coroutines
EventHandler = Callable[
    [ChannelAdapter, str, Dict[str, Any]],
    Coroutine[Any, Any, None],
]


class ChannelEventBridge:
    """Bridges agent events to channel adapters for channel-bound conversations.

    Usage::

        bridge = ChannelEventBridge(channel_manager)
        await bridge.on_agent_event(conversation_id, event_dict)

    The bridge performs a reverse-lookup from ``conversation_id`` to the bound
    channel (via ``ChannelSessionBindingRepository``), then dispatches the event
    to the appropriate handler.
    """

    # Event types that should be forwarded to channels
    _FORWARDED_EVENTS = frozenset({
        "clarification_asked",
        "decision_asked",
        "env_var_requested",
        "permission_asked",
        "task_list_updated",
        "artifact_ready",
        "error",
    })

    def __init__(self, channel_manager: Any = None) -> None:
        self._channel_manager = channel_manager
        self._handlers: Dict[str, EventHandler] = {
            "clarification_asked": self._handle_hitl_event,
            "decision_asked": self._handle_hitl_event,
            "env_var_requested": self._handle_hitl_event,
            "permission_asked": self._handle_hitl_event,
            "task_list_updated": self._handle_task_update,
            "artifact_ready": self._handle_artifact_ready,
            "error": self._handle_error,
        }

    async def on_agent_event(
        self,
        conversation_id: str,
        event: Dict[str, Any],
    ) -> None:
        """Route an agent event to the bound channel (if any).

        Args:
            conversation_id: The conversation that produced this event.
            event: Raw event dict with ``type`` and ``data`` keys.
        """
        event_type = event.get("type")
        if not event_type or event_type not in self._FORWARDED_EVENTS:
            return

        handler = self._handlers.get(event_type)
        if not handler:
            return

        try:
            binding = await self._lookup_binding(conversation_id)
            if not binding:
                return

            adapter = self._get_adapter(binding.channel_config_id)
            if not adapter:
                logger.debug(
                    f"[EventBridge] No adapter for config {binding.channel_config_id}"
                )
                return

            chat_id = binding.chat_id
            event_data = event.get("data") or {}
            await handler(adapter, chat_id, event_data)
        except Exception as e:
            logger.warning(
                f"[EventBridge] Failed to forward {event_type} "
                f"for conversation {conversation_id}: {e}"
            )

    async def _lookup_binding(self, conversation_id: str) -> Any:
        """Reverse-lookup channel binding from conversation_id."""
        try:
            from src.infrastructure.adapters.secondary.persistence.database import (
                async_session_factory,
            )
            from src.infrastructure.adapters.secondary.persistence.channel_repository import (
                ChannelSessionBindingRepository,
            )

            async with async_session_factory() as session:
                repo = ChannelSessionBindingRepository(session)
                return await repo.get_by_conversation_id(conversation_id)
        except Exception as e:
            logger.debug(f"[EventBridge] Binding lookup failed: {e}")
            return None

    def _get_adapter(self, channel_config_id: str) -> Optional[ChannelAdapter]:
        """Get the channel adapter for a config ID."""
        if not self._channel_manager:
            try:
                from src.infrastructure.channels.connection_manager import (
                    get_channel_manager,
                )
                self._channel_manager = get_channel_manager()
            except Exception:
                return None

        if not self._channel_manager:
            return None

        conn = self._channel_manager.connections.get(channel_config_id)
        if conn and getattr(conn, "adapter", None):
            return conn.adapter
        return None

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    async def _handle_hitl_event(
        self,
        adapter: ChannelAdapter,
        chat_id: str,
        event_data: Dict[str, Any],
    ) -> None:
        """Forward HITL request to channel as an interactive card."""
        try:
            from src.infrastructure.adapters.secondary.channels.feishu.hitl_cards import (
                HITLCardBuilder,
            )

            builder = HITLCardBuilder()
            event_type = event_data.get("_event_type", "clarification")
            request_id = event_data.get("request_id", "")
            card = builder.build_card(event_type, request_id, event_data)
            if not card:
                card = self._build_hitl_card(event_data)

            if card:
                await adapter.send_card(chat_id, card)
                logger.info(f"[EventBridge] Sent HITL card to {chat_id}")
            else:
                question = event_data.get("question", "")
                options = event_data.get("options", [])
                text = self._format_hitl_text(question, options)
                if text:
                    await adapter.send_text(chat_id, text)
        except Exception as e:
            logger.warning(f"[EventBridge] HITL card send failed: {e}")

    async def _handle_task_update(
        self,
        adapter: ChannelAdapter,
        chat_id: str,
        event_data: Dict[str, Any],
    ) -> None:
        """Forward task list update to channel as a rich card."""
        tasks = event_data.get("tasks") or event_data.get("todos") or []
        if not tasks:
            return

        try:
            from src.infrastructure.adapters.secondary.channels.feishu.rich_cards import (
                RichCardBuilder,
            )

            card = RichCardBuilder().build_task_progress_card(tasks)
            if card:
                await adapter.send_card(chat_id, card)
                return
        except Exception:
            pass

        # Fallback to plain text
        lines: List[str] = []
        for task in tasks[:10]:
            status = task.get("status", "pending")
            title = task.get("title", "Untitled")
            icon = {"completed": "[done]", "in_progress": "[...]", "failed": "[X]"}.get(
                status, "[ ]"
            )
            lines.append(f"{icon} {title}")

        if lines:
            text = "**Task Update**\n" + "\n".join(lines)
            try:
                await adapter.send_markdown_card(chat_id, text)
            except Exception:
                await adapter.send_text(chat_id, text)

    async def _handle_artifact_ready(
        self,
        adapter: ChannelAdapter,
        chat_id: str,
        event_data: Dict[str, Any],
    ) -> None:
        """Forward artifact availability notification as a rich card."""
        name = event_data.get("name") or event_data.get("filename") or "Artifact"
        url = event_data.get("url") or event_data.get("download_url") or ""

        try:
            from src.infrastructure.adapters.secondary.channels.feishu.rich_cards import (
                RichCardBuilder,
            )

            card = RichCardBuilder().build_artifact_card(
                name,
                url=url,
                file_type=event_data.get("file_type", ""),
                size=event_data.get("size", ""),
                description=event_data.get("description", ""),
            )
            await adapter.send_card(chat_id, card)
        except Exception:
            text = f"**Artifact Ready**: {name}"
            if url:
                text += f"\n[Download]({url})"
            try:
                await adapter.send_markdown_card(chat_id, text)
            except Exception:
                await adapter.send_text(chat_id, text)

    async def _handle_error(
        self,
        adapter: ChannelAdapter,
        chat_id: str,
        event_data: Dict[str, Any],
    ) -> None:
        """Forward error notification as a rich card."""
        message = event_data.get("message") or "An error occurred"
        code = event_data.get("code") or ""
        conversation_id = event_data.get("conversation_id", "")

        try:
            from src.infrastructure.adapters.secondary.channels.feishu.rich_cards import (
                RichCardBuilder,
            )

            card = RichCardBuilder().build_error_card(
                message,
                error_code=code,
                conversation_id=conversation_id,
                retryable=event_data.get("retryable", False),
            )
            await adapter.send_card(chat_id, card)
        except Exception:
            text = f"Error: {message}"
            if code:
                text += f" ({code})"
            try:
                await adapter.send_text(chat_id, text)
            except Exception as e:
                logger.debug(f"[EventBridge] Error send failed: {e}")

    # ------------------------------------------------------------------
    # Card builders
    # ------------------------------------------------------------------

    def _build_hitl_card(self, event_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Build an interactive card for HITL requests.

        Returns a Feishu-compatible card dict or None if not possible.
        """
        question = event_data.get("question", "")
        options = event_data.get("options", [])
        request_id = event_data.get("request_id", "")

        if not question:
            return None

        elements: List[Dict[str, Any]] = [
            {
                "tag": "markdown",
                "content": f"**Agent Question**\n\n{question}",
            },
        ]

        if options:
            actions: List[Dict[str, Any]] = []
            for opt in options[:5]:  # Limit to 5 buttons
                opt_text = opt if isinstance(opt, str) else str(opt.get("label", opt))
                opt_value = opt if isinstance(opt, str) else str(opt.get("value", opt))
                actions.append({
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": opt_text},
                    "type": "primary" if len(actions) == 0 else "default",
                    "value": {
                        "hitl_request_id": request_id,
                        "response_data": {"answer": opt_value},
                    },
                })
            elements.append({"tag": "action", "actions": actions})

        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "Agent needs your input"},
                "template": "blue",
            },
            "elements": elements,
        }

    def _format_hitl_text(
        self, question: str, options: List[Any]
    ) -> str:
        """Format HITL request as plain text (fallback)."""
        if not question:
            return ""
        parts = [f"[Agent Question] {question}"]
        if options:
            for i, opt in enumerate(options, 1):
                opt_text = opt if isinstance(opt, str) else str(opt)
                parts.append(f"  {i}. {opt_text}")
            parts.append("Please reply with your choice number or answer.")
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_bridge: Optional[ChannelEventBridge] = None


def get_channel_event_bridge() -> ChannelEventBridge:
    """Get or create the singleton ChannelEventBridge."""
    global _bridge
    if _bridge is None:
        _bridge = ChannelEventBridge()
    return _bridge
