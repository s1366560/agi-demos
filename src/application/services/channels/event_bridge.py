"""Channel Event Bridge - forwards agent events to bound channel adapters.

This module implements the Event Bridge pattern: a post-processing layer that
subscribes to agent events for channel-bound conversations and routes relevant
events to the appropriate channel adapter (Feishu, Slack, etc.).

The agent core remains unchanged; the bridge is purely additive.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any, cast

from src.configuration.config import get_settings
from src.domain.model.channels.message import ChannelAdapter

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from src.infrastructure.adapters.secondary.channels.feishu.cardkit_streaming import (
        CardStreamState,
    )
    from src.infrastructure.channels.connection_manager import ChannelConnectionManager

# Type alias for event handler coroutines
EventHandler = Callable[
    [ChannelAdapter, str, dict[str, Any]],
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
    _FORWARDED_EVENTS = frozenset(
        {
            "clarification_asked",
            "decision_asked",
            "env_var_requested",
            "permission_asked",
            "task_list_updated",
            "task_start",
            "task_complete",
            "artifact_ready",
            "error",
            "subagent_session_spawned",
            "subagent_run_completed",
            "subagent_run_failed",
            "subagent_announce_retry",
            "subagent_announce_giveup",
            "subagent_killed",
        }
    )

    _DEFAULT_SUBAGENT_FOCUS_TTL_SECONDS = 300.0

    def __init__(
        self,
        channel_manager: ChannelConnectionManager | None = None,
        *,
        subagent_focus_ttl_seconds: float | None = None,
    ) -> None:
        self._channel_manager = channel_manager
        self._handlers: dict[str, EventHandler] = {
            "clarification_asked": self._handle_hitl_event,
            "decision_asked": self._handle_hitl_event,
            "env_var_requested": self._handle_hitl_event,
            "permission_asked": self._handle_hitl_event,
            "task_list_updated": self._handle_task_update,
            "task_start": self._handle_task_timeline_event,
            "task_complete": self._handle_task_timeline_event,
            "artifact_ready": self._handle_artifact_ready,
            "error": self._handle_error,
            "subagent_session_spawned": self._handle_subagent_focus_event,
            "subagent_run_completed": self._handle_subagent_focus_event,
            "subagent_run_failed": self._handle_subagent_focus_event,
            "subagent_announce_retry": self._handle_subagent_focus_event,
            "subagent_announce_giveup": self._handle_subagent_focus_event,
            "subagent_killed": self._handle_subagent_focus_event,
        }
        # card_id → CardStreamState for unified HITL (set by streaming flow)
        self._card_states: dict[str, Any] = {}  # conversation_id → CardStreamState
        # conversation_id → task progress card message_id (for patch updates)
        self._task_card_states: dict[str, str] = {}
        # conversation_id -> detached subagent thread focus state
        self._subagent_focus: dict[str, dict[str, Any]] = {}
        self._subagent_focus_timeout_tasks: dict[str, asyncio.Task[None]] = {}
        configured_focus_ttl_seconds = (
            self._DEFAULT_SUBAGENT_FOCUS_TTL_SECONDS
            if subagent_focus_ttl_seconds is None
            else subagent_focus_ttl_seconds
        )
        self._subagent_focus_ttl_seconds = max(float(configured_focus_ttl_seconds), 0.0)

    async def on_agent_event(
        self,
        conversation_id: str,
        event: dict[str, Any],
        *,
        tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> None:
        """Route an agent event to the bound channel (if any).

        Args:
            conversation_id: The conversation that produced this event.
            event: Raw event dict with ``type`` and ``data`` keys.
            tenant_id: Tenant ID (passed through to HITL card buttons).
            project_id: Project ID (passed through to HITL card buttons).
        """
        event_type = event.get("type")
        if not event_type or event_type not in self._FORWARDED_EVENTS:
            return

        logger.info(
            f"[EventBridge] Received forwarded event: type={event_type}, "
            f"conversation_id={conversation_id}"
        )

        handler = self._handlers.get(event_type)
        if not handler:
            return

        try:
            binding = await self._lookup_binding(conversation_id)
            if not binding:
                logger.info(
                    f"[EventBridge] No binding for conversation {conversation_id}, "
                    f"skipping {event_type}"
                )
                return

            adapter = self._get_adapter(binding.channel_config_id)
            if not adapter:
                logger.info(
                    f"[EventBridge] No adapter for config {binding.channel_config_id}, "
                    f"skipping {event_type}"
                )
                return

            chat_id = binding.chat_id
            event_data = event.get("data") or {}
            if isinstance(event_data, dict):
                event_data = {
                    **event_data,
                    "_event_type": event_type,
                    "_conversation_id": conversation_id,
                    "_tenant_id": tenant_id,
                    "_project_id": project_id,
                    "_thread_id": getattr(binding, "thread_id", None),
                }
            await handler(adapter, chat_id, event_data)
        except Exception as e:
            logger.warning(
                f"[EventBridge] Failed to forward {event_type} "
                f"for conversation {conversation_id}: {e}"
            )

    async def _lookup_binding(self, conversation_id: str) -> Any:
        """Reverse-lookup channel binding from conversation_id."""
        try:
            from src.infrastructure.adapters.secondary.persistence.channel_repository import (
                ChannelSessionBindingRepository,
            )
            from src.infrastructure.adapters.secondary.persistence.database import (
                async_session_factory,
            )

            async with async_session_factory() as session:
                repo = ChannelSessionBindingRepository(session)
                return await repo.get_by_conversation_id(conversation_id)
        except Exception as e:
            logger.info(f"[EventBridge] Binding lookup failed: {e}")
            return None

    def _get_adapter(self, channel_config_id: str) -> ChannelAdapter | None:
        """Get the channel adapter for a config ID."""
        if not self._channel_manager:
            try:
                from src.infrastructure.adapters.primary.web.startup.channels import (
                    get_channel_manager,
                )

                self._channel_manager = get_channel_manager()
            except Exception:
                return None

        if not self._channel_manager:
            return None

        conn = self._channel_manager.connections.get(channel_config_id)
        if conn and getattr(conn, "adapter", None):
            return cast("ChannelAdapter", conn.adapter)
        return None

    # ------------------------------------------------------------------
    # Card state management (for unified CardKit HITL)
    # ------------------------------------------------------------------

    def register_card_state(self, conversation_id: str, card_state: CardStreamState) -> None:
        """Register a CardStreamState for unified HITL on a streaming card.

        Called by ``_invoke_agent()`` when CardKit streaming starts so HITL
        buttons can be appended to the same card entity.
        """
        self._card_states[conversation_id] = card_state

    def unregister_card_state(self, conversation_id: str) -> None:
        """Remove card state tracking for a conversation."""
        self._card_states.pop(conversation_id, None)

    def get_card_state(self, conversation_id: str) -> CardStreamState | None:
        """Get the active CardStreamState for a conversation (or None)."""
        return self._card_states.get(conversation_id)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    async def _handle_hitl_event(
        self,
        adapter: ChannelAdapter,
        chat_id: str,
        event_data: dict[str, Any],
    ) -> None:
        """Forward HITL request to channel as an interactive card.

        Priority order:
        1. Unified CardKit flow: add buttons to the active streaming card
        2. Standalone CardKit flow: create new card entity + buttons
        3. Static card JSON fallback
        4. Plain text fallback
        """
        try:
            event_type = event_data.get("_event_type", "clarification")
            request_id = event_data.get("request_id", "")
            conversation_id = event_data.get("_conversation_id", "")
            tenant_id = event_data.get("_tenant_id", "")
            project_id = event_data.get("_project_id", "")
            logger.info(
                f"[EventBridge] Building HITL card: type={event_type}, "
                f"request_id={request_id}, chat_id={chat_id}"
            )

            # 1. Try unified flow: add buttons to the active streaming card
            if conversation_id and hasattr(adapter, "add_card_elements"):
                card_state = self.get_card_state(conversation_id)
                if card_state and card_state.card_id:
                    ok = await self._add_hitl_to_streaming_card(
                        adapter,
                        card_state,
                        event_type,
                        request_id,
                        event_data,
                        tenant_id=tenant_id,
                        project_id=project_id,
                    )
                    if ok:
                        logger.info(
                            f"[EventBridge] Added HITL buttons to streaming card "
                            f"{card_state.card_id}"
                        )
                        return

            # 2. Try standalone CardKit flow
            if hasattr(adapter, "send_hitl_card_via_cardkit"):
                message_id = await adapter.send_hitl_card_via_cardkit(
                    chat_id,
                    event_type,
                    request_id,
                    event_data,
                    tenant_id=tenant_id,
                    project_id=project_id,
                )
                if message_id:
                    logger.info(f"[EventBridge] Sent HITL card via CardKit to {chat_id}")
                    return
                logger.info("[EventBridge] CardKit HITL failed, falling back to static card")

            # 3. Fallback: build static card and send as regular interactive message
            from src.infrastructure.adapters.secondary.channels.feishu.hitl_cards import (
                HITLCardBuilder,
            )

            builder = HITLCardBuilder()
            card = builder.build_card(
                event_type,
                request_id,
                event_data,
                tenant_id=tenant_id,
                project_id=project_id,
            )
            if not card:
                logger.warning(
                    f"[EventBridge] HITLCardBuilder returned None for "
                    f"type={event_type}, falling back"
                )
                card = self._build_hitl_card(event_data)

            if card:
                await adapter.send_card(chat_id, card)
                logger.info(f"[EventBridge] Sent HITL card to {chat_id}")
            else:
                question = event_data.get("question", "")
                options = event_data.get("options", [])
                text = self._format_hitl_text(question, options)
                if text:
                    logger.info(f"[EventBridge] Falling back to text for HITL: {chat_id}")
                    await adapter.send_text(chat_id, text)
        except Exception as e:
            logger.warning(f"[EventBridge] HITL card send failed: {e}", exc_info=True)

    async def _add_hitl_to_streaming_card(
        self,
        adapter: ChannelAdapter,
        card_state: CardStreamState,
        event_type: str,
        request_id: str,
        event_data: dict[str, Any],
        *,
        tenant_id: str = "",
        project_id: str = "",
    ) -> bool:
        """Add HITL action elements to an existing streaming card.

        Closes streaming mode first (required for card callbacks), then
        appends button/select elements to the card via CardKit API.
        """
        try:
            from src.infrastructure.adapters.secondary.channels.feishu.cardkit_streaming import (
                CardKitStreamingManager,
            )
            from src.infrastructure.adapters.secondary.channels.feishu.hitl_cards import (
                HITLCardBuilder,
            )

            builder = HITLCardBuilder()
            elements = builder.build_hitl_action_elements(
                event_type,
                request_id,
                event_data,
                tenant_id=tenant_id,
                project_id=project_id,
            )
            if not elements:
                return False

            mgr = CardKitStreamingManager(adapter)
            return await mgr.add_hitl_buttons(card_state, elements)
        except Exception as e:
            logger.warning(f"[EventBridge] Unified HITL failed: {e}")
            return False

    async def _handle_task_update(
        self,
        adapter: ChannelAdapter,
        chat_id: str,
        event_data: dict[str, Any],
    ) -> None:
        """Forward task list update to channel as a rich card.

        Uses patch_card to update existing task card if available,
        otherwise sends a new card and tracks it for future updates.
        """
        tasks = event_data.get("tasks") or event_data.get("todos") or []
        if not tasks:
            return

        conversation_id = event_data.get("_conversation_id", "")

        try:
            from src.infrastructure.adapters.secondary.channels.feishu.rich_cards import (
                RichCardBuilder,
            )

            card = RichCardBuilder().build_task_progress_card(tasks)
            if not card:
                # Fallback to plain text
                self._send_task_text_fallback(adapter, chat_id, tasks)
                return

            # Check if we have an existing task card to update
            existing_msg_id = (
                self._task_card_states.get(conversation_id) if conversation_id else None
            )

            if existing_msg_id and hasattr(adapter, "patch_card"):
                # Try to update existing card via patch
                card_json = json.dumps(card)
                try:
                    ok = await adapter.patch_card(existing_msg_id, card_json)
                    if ok:
                        logger.info(
                            f"[EventBridge] Updated task card {existing_msg_id} "
                            f"for conversation {conversation_id}"
                        )
                        return
                    logger.warning(
                        f"[EventBridge] Patch card failed for {existing_msg_id}, sending new card"
                    )
                except Exception as e:
                    logger.warning(f"[EventBridge] Patch card error: {e}, sending new card")

            # Send new card
            try:
                msg_id = await adapter.send_card(chat_id, card)
                if msg_id and conversation_id:
                    self._task_card_states[conversation_id] = msg_id
                    logger.info(
                        f"[EventBridge] Sent new task card {msg_id} "
                        f"for conversation {conversation_id}"
                    )
            except Exception as e:
                logger.warning(f"[EventBridge] Send card failed: {e}")
                # Fallback to plain text
                self._send_task_text_fallback(adapter, chat_id, tasks)

        except Exception as e:
            logger.warning(f"[EventBridge] Task update handling failed: {e}")
            # Fallback to plain text
            self._send_task_text_fallback(adapter, chat_id, tasks)

    async def _send_task_text_fallback(
        self,
        adapter: ChannelAdapter,
        chat_id: str,
        tasks: list[dict[str, Any]],
    ) -> None:
        """Send task update as plain text fallback."""
        lines: list[str] = []
        for task in tasks[:10]:
            status = task.get("status", "pending")
            title = task.get("content") or task.get("title", "Untitled")
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

    def clear_task_card_state(self, conversation_id: str) -> None:
        """Clear task card state for a conversation (call when conversation ends)."""
        self._task_card_states.pop(conversation_id, None)

    async def _handle_task_timeline_event(
        self,
        adapter: ChannelAdapter,
        chat_id: str,
        event_data: dict[str, Any],
    ) -> None:
        """Forward task_start/task_complete timeline events as status messages."""
        event_type = event_data.get("_event_type", "")
        _task_id = event_data.get("task_id", "")
        content = event_data.get("content", "")
        status = event_data.get("status", "")

        if not content:
            return

        icon = {
            "task_start": "🔄",
            "task_complete": "✅" if status == "completed" else "❌",
        }.get(event_type, "•")

        order_index = event_data.get("order_index", 0)
        total_tasks = event_data.get("total_tasks", 1)

        progress = f"({order_index + 1}/{total_tasks})"

        if event_type == "task_start":
            text = f"{icon} {progress} **Starting:** {content}"
        elif event_type == "task_complete":
            if status == "completed":
                text = f"{icon} {progress} **Completed:** {content}"
            elif status == "failed":
                text = f"{icon} {progress} **Failed:** {content}"
            else:
                text = f"{icon} {progress} **{status.capitalize()}:** {content}"
        else:
            text = f"{icon} {content}"

        try:
            await adapter.send_markdown_card(chat_id, text)
        except Exception:
            try:
                await adapter.send_text(chat_id, text)
            except Exception as e:
                logger.warning(f"[EventBridge] Task timeline send failed: {e}")

    async def _handle_artifact_ready(
        self,
        adapter: ChannelAdapter,
        chat_id: str,
        event_data: dict[str, Any],
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
        event_data: dict[str, Any],
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

    async def _handle_subagent_focus_event(
        self,
        adapter: ChannelAdapter,
        chat_id: str,
        event_data: dict[str, Any],
    ) -> None:
        """Forward detached subagent lifecycle updates with thread focus + TTL unfocus."""
        event_type_raw = event_data.get("_event_type")
        event_type = event_type_raw if isinstance(event_type_raw, str) else ""
        conversation_id_raw = event_data.get("_conversation_id")
        conversation_id = conversation_id_raw if isinstance(conversation_id_raw, str) else ""
        run_id_raw = event_data.get("run_id")
        run_id = run_id_raw if isinstance(run_id_raw, str) else ""
        subagent_name_raw = event_data.get("subagent_name")
        subagent_name = (
            subagent_name_raw.strip()
            if isinstance(subagent_name_raw, str) and subagent_name_raw.strip()
            else "subagent"
        )
        thread_id = event_data.get("_thread_id")
        thread_reply_to = thread_id if isinstance(thread_id, str) and thread_id else None
        summary = event_data.get("summary")
        error = event_data.get("error")

        if not conversation_id or not run_id:
            return

        if event_type == "subagent_session_spawned":
            self._set_subagent_focus(
                conversation_id=conversation_id,
                run_id=run_id,
                subagent_name=subagent_name,
            )
            self._arm_subagent_focus_timeout(
                conversation_id=conversation_id,
                run_id=run_id,
                subagent_name=subagent_name,
                adapter=adapter,
                chat_id=chat_id,
                reply_to=thread_reply_to,
            )
            await self._send_thread_markdown(
                adapter=adapter,
                chat_id=chat_id,
                text=f"SubAgent `{subagent_name}` started (run `{run_id}`).",
                reply_to=thread_reply_to,
            )
            return

        if event_type == "subagent_announce_retry":
            focus = self._subagent_focus.get(conversation_id)
            if focus and focus.get("run_id") == run_id:
                self._arm_subagent_focus_timeout(
                    conversation_id=conversation_id,
                    run_id=run_id,
                    subagent_name=subagent_name,
                    adapter=adapter,
                    chat_id=chat_id,
                    reply_to=thread_reply_to,
                )
            return

        if event_type == "subagent_run_completed":
            self._clear_subagent_focus(conversation_id=conversation_id, run_id=run_id)
            completion_text = f"SubAgent `{subagent_name}` completed."
            if isinstance(summary, str) and summary.strip():
                completion_text = f"{completion_text}\n\n{summary.strip()}"
            await self._send_thread_markdown(
                adapter=adapter,
                chat_id=chat_id,
                text=completion_text,
                reply_to=thread_reply_to,
            )
            return

        if event_type in {"subagent_run_failed", "subagent_announce_giveup", "subagent_killed"}:
            self._clear_subagent_focus(conversation_id=conversation_id, run_id=run_id)
            failure_reason = (
                error.strip()
                if isinstance(error, str) and error.strip()
                else str(event_data.get("status", "failed"))
            )
            await self._send_thread_markdown(
                adapter=adapter,
                chat_id=chat_id,
                text=f"SubAgent `{subagent_name}` failed: {failure_reason}",
                reply_to=thread_reply_to,
            )

    async def _send_thread_markdown(
        self,
        *,
        adapter: ChannelAdapter,
        chat_id: str,
        text: str,
        reply_to: str | None,
    ) -> None:
        """Send markdown card in thread when possible, with text fallback."""
        if hasattr(adapter, "send_markdown_card"):
            try:
                await adapter.send_markdown_card(chat_id, text, reply_to=reply_to)
                return
            except Exception:
                logger.debug("[EventBridge] send_markdown_card failed, fallback to send_text")

        await adapter.send_text(chat_id, text, reply_to=reply_to)

    def _set_subagent_focus(
        self,
        *,
        conversation_id: str,
        run_id: str,
        subagent_name: str,
    ) -> None:
        """Track active detached subagent focus per conversation."""
        self._subagent_focus[conversation_id] = {
            "run_id": run_id,
            "subagent_name": subagent_name,
        }

    def _clear_subagent_focus(self, *, conversation_id: str, run_id: str) -> bool:
        """Clear detached subagent focus and cancel timeout task."""
        focus = self._subagent_focus.get(conversation_id)
        if not focus or focus.get("run_id") != run_id:
            return False
        self._subagent_focus.pop(conversation_id, None)
        self._cancel_subagent_focus_timeout(conversation_id)
        return True

    def _cancel_subagent_focus_timeout(self, conversation_id: str) -> None:
        """Cancel pending subagent focus timeout task for a conversation."""
        timeout_task = self._subagent_focus_timeout_tasks.pop(conversation_id, None)
        if timeout_task and not timeout_task.done():
            timeout_task.cancel()

    def _arm_subagent_focus_timeout(
        self,
        *,
        conversation_id: str,
        run_id: str,
        subagent_name: str,
        adapter: ChannelAdapter,
        chat_id: str,
        reply_to: str | None,
    ) -> None:
        """Arm (or refresh) auto-unfocus timeout for an active detached subagent."""
        self._cancel_subagent_focus_timeout(conversation_id)
        ttl_seconds = max(float(self._subagent_focus_ttl_seconds), 0.0)

        async def _expire_focus() -> None:
            try:
                await asyncio.sleep(ttl_seconds)
                focus = self._subagent_focus.get(conversation_id)
                if not focus or focus.get("run_id") != run_id:
                    return
                self._subagent_focus.pop(conversation_id, None)
                await self._send_thread_markdown(
                    adapter=adapter,
                    chat_id=chat_id,
                    text=(
                        f"SubAgent `{subagent_name}` is still running; "
                        "focus auto-cleared after TTL."
                    ),
                    reply_to=reply_to,
                )
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.debug(f"[EventBridge] Subagent focus timeout handling failed: {e}")
            finally:
                current = self._subagent_focus_timeout_tasks.get(conversation_id)
                if current is asyncio.current_task():
                    self._subagent_focus_timeout_tasks.pop(conversation_id, None)

        self._subagent_focus_timeout_tasks[conversation_id] = asyncio.create_task(
            _expire_focus(),
            name=f"subagent-focus-timeout-{conversation_id}",
        )

    # ------------------------------------------------------------------
    # Card builders
    # ------------------------------------------------------------------

    def _build_hitl_card(self, event_data: dict[str, Any]) -> dict[str, Any] | None:
        """Build an interactive card for HITL requests.

        Returns a Feishu-compatible card dict or None if not possible.
        """
        question = event_data.get("question", "")
        options = event_data.get("options", [])
        request_id = event_data.get("request_id", "")

        if not question:
            return None

        elements: list[dict[str, Any]] = [
            {
                "tag": "markdown",
                "content": f"**Agent Question**\n\n{question}",
            },
        ]

        if options:
            actions: list[dict[str, Any]] = []
            for opt in options[:5]:  # Limit to 5 buttons
                opt_text = opt if isinstance(opt, str) else str(opt.get("label", opt))
                opt_value = opt if isinstance(opt, str) else str(opt.get("value", opt))
                actions.append(
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": opt_text},
                        "type": "primary" if len(actions) == 0 else "default",
                        "value": {
                            "hitl_request_id": request_id,
                            "response_data": json.dumps({"answer": opt_value}),
                        },
                    }
                )
            elements.append({"tag": "action", "actions": actions})

        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "Agent needs your input"},
                "template": "blue",
            },
            "elements": elements,
        }

    def _format_hitl_text(self, question: str, options: list[Any]) -> str:
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

_bridge: ChannelEventBridge | None = None


def get_channel_event_bridge() -> ChannelEventBridge:
    """Get or create the singleton ChannelEventBridge."""
    global _bridge
    if _bridge is None:
        settings = get_settings()
        _bridge = ChannelEventBridge(
            subagent_focus_ttl_seconds=settings.agent_subagent_focus_ttl_seconds
        )
    return _bridge
