"""CardKit streaming orchestration for Feishu.

Manages card entity lifecycle for streaming AI responses:
  1. Create card entity (JSON 2.0)
  2. Enable streaming mode
  3. Send card as message
  4. Stream text updates (typewriter effect)
  5. Disable streaming mode
  6. (Optional) Add HITL buttons to the same card
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, Optional

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from src.infrastructure.adapters.secondary.channels.feishu.adapter import FeishuAdapter

CONTENT_ELEMENT_ID = "content"
"""Fixed element_id for the main markdown content element."""


class CardKitSequence:
    """Thread-safe strictly-increasing sequence number manager per card_id.

    Every CardKit API call on a card entity requires a ``sequence`` parameter
    that must be strictly increasing across all operations on that card.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sequences: Dict[str, int] = {}

    def next(self, card_id: str) -> int:
        """Return the next sequence number for *card_id*."""
        with self._lock:
            current = self._sequences.get(card_id, 0)
            next_val = current + 1
            self._sequences[card_id] = next_val
            return next_val

    def current(self, card_id: str) -> int:
        """Return the current sequence number (0 if never used)."""
        with self._lock:
            return self._sequences.get(card_id, 0)

    def remove(self, card_id: str) -> None:
        """Clean up sequence tracking for a card."""
        with self._lock:
            self._sequences.pop(card_id, None)


@dataclass
class CardStreamState:
    """Tracks the state of a CardKit streaming card for one conversation turn."""

    card_id: str
    message_id: Optional[str] = None
    streaming_active: bool = False
    last_content: str = ""
    sequence: CardKitSequence = field(default_factory=CardKitSequence)

    def next_seq(self) -> int:
        return self.sequence.next(self.card_id)


def build_initial_card_data(title: str = "MemStack Agent") -> Dict[str, Any]:
    """Build a JSON 2.0 card entity with a single markdown element for streaming.

    The card has:
    - A header with the given title
    - A single markdown element with element_id="content" (initial: thinking)
    - ``update_multi: true`` (required for CardKit operations)

    Returns:
        Card JSON 2.0 dict ready for ``create_card_entity()``.
    """
    return {
        "schema": "2.0",
        "config": {
            "update_multi": True,
        },
        "header": {
            "title": {
                "tag": "plain_text",
                "content": title,
            },
            "template": "blue",
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 12px 12px",
            "elements": [
                {
                    "tag": "markdown",
                    "element_id": CONTENT_ELEMENT_ID,
                    "content": "_Thinking..._",
                },
            ],
        },
    }


def build_streaming_settings(enabled: bool) -> Dict[str, Any]:
    """Build settings dict for enabling/disabling streaming mode.

    Args:
        enabled: True to enable streaming (typewriter), False to disable.

    Returns:
        Settings dict for ``update_card_settings()``.
    """
    settings: Dict[str, Any] = {
        "config": {
            "streaming_mode": enabled,
        },
    }
    if enabled:
        settings["config"]["streaming_config"] = {
            "print_frequency_ms": {"default": 50},
            "print_step": {"default": 2},
            "print_strategy": "fast",
        }
    return settings


class CardKitStreamingManager:
    """Manages CardKit streaming lifecycle for a single conversation turn.

    Usage in ``_invoke_agent()``::

        mgr = CardKitStreamingManager(adapter)
        card_state = await mgr.start_streaming(chat_id, reply_to=msg_id)
        # ... on text_delta events:
        await mgr.update_text(card_state, accumulated_text)
        # ... on stream end:
        await mgr.finish_streaming(card_state, final_text)
        # ... on HITL:
        await mgr.add_hitl_buttons(card_state, elements)
    """

    # Minimum interval between streaming text updates (seconds)
    _MIN_UPDATE_INTERVAL = 0.3

    def __init__(self, adapter: FeishuAdapter) -> None:
        self._adapter = adapter
        self._last_update_time: float = 0

    async def start_streaming(
        self,
        chat_id: str,
        *,
        reply_to: Optional[str] = None,
        title: str = "MemStack Agent",
    ) -> Optional[CardStreamState]:
        """Create card entity, enable streaming, and send the card.

        Returns a ``CardStreamState`` on success, ``None`` on failure.
        """
        card_data = build_initial_card_data(title)
        card_id = await self._adapter.create_card_entity(card_data)
        if not card_id:
            return None

        state = CardStreamState(card_id=card_id)

        # Enable streaming mode
        settings = build_streaming_settings(enabled=True)
        ok = await self._adapter.update_card_settings(card_id, settings, state.next_seq())
        if not ok:
            logger.warning(f"[CardKitStreaming] Failed to enable streaming for {card_id}")

        # Send the card as a message
        try:
            message_id = await self._adapter.send_card_entity_message(chat_id, card_id, reply_to)
            state.message_id = message_id
            state.streaming_active = True
            logger.info(
                f"[CardKitStreaming] Started streaming: card_id={card_id}, message_id={message_id}"
            )
            return state
        except Exception as e:
            logger.error(f"[CardKitStreaming] Failed to send card: {e}")
            return None

    async def update_text(
        self,
        state: CardStreamState,
        content: str,
        *,
        force: bool = False,
    ) -> bool:
        """Push accumulated text to the streaming card (typewriter effect).

        Throttles calls to respect the 10 ops/s CardKit limit.

        Args:
            state: The card stream state.
            content: Full accumulated text (not a delta).
            force: If True, skip throttle check.

        Returns:
            True if the update was sent.
        """
        if not state.streaming_active:
            return False

        if content == state.last_content:
            return False

        now = asyncio.get_event_loop().time()
        if not force and (now - self._last_update_time) < self._MIN_UPDATE_INTERVAL:
            return False

        ok = await self._adapter.stream_text_content(
            state.card_id, CONTENT_ELEMENT_ID, content, state.next_seq()
        )
        if ok:
            state.last_content = content
            self._last_update_time = now
        return ok

    async def finish_streaming(
        self,
        state: CardStreamState,
        final_content: str,
    ) -> bool:
        """Finalize the streaming card: send final text and disable streaming mode.

        Args:
            state: The card stream state.
            final_content: The complete final text.

        Returns:
            True if finalization succeeded.
        """
        if not state.card_id:
            return False

        # Always send final content if non-empty (force, skip throttle)
        # This ensures the final text is displayed correctly after streaming mode is disabled
        if final_content.strip():
            ok = await self.update_text(state, final_content, force=True)
            if not ok:
                # Retry once if update failed (e.g., due to throttle or same content)
                state.last_content = ""  # Reset to force update
                await self.update_text(state, final_content, force=True)

        # Disable streaming mode
        settings = build_streaming_settings(enabled=False)
        ok = await self._adapter.update_card_settings(state.card_id, settings, state.next_seq())
        state.streaming_active = False

        if ok:
            logger.info(f"[CardKitStreaming] Finished streaming: card_id={state.card_id}")
        return ok

    async def add_hitl_buttons(
        self,
        state: CardStreamState,
        elements: list,
    ) -> bool:
        """Add HITL interactive buttons to the streaming card.

        Streaming mode must be disabled first (call ``finish_streaming()``).

        Args:
            state: The card stream state.
            elements: Button element dicts (JSON 2.0).

        Returns:
            True on success.
        """
        if state.streaming_active:
            await self.finish_streaming(state, state.last_content)

        return await self._adapter.add_card_elements(
            state.card_id,
            elements,
            position="append",
            sequence=state.next_seq(),
        )
