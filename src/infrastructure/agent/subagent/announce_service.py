"""Child-to-parent result announcement service with retry and error classification."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, cast

from src.domain.events.agent_events import SubAgentAnnounceRetryEvent
from src.domain.model.agent.announce_config import AnnounceConfig

if TYPE_CHECKING:
    from redis.asyncio import Redis as AsyncRedis

logger = logging.getLogger(__name__)


class ErrorCategory(str, Enum):
    """Classification of announce errors for retry decisions."""

    TRANSIENT = "transient"  # ConnectionError, TimeoutError, OSError -- retry
    PERMANENT = "permanent"  # ValueError, TypeError, KeyError -- do not retry
    UNKNOWN = "unknown"  # All other exceptions -- retry once


_TRANSIENT_ERRORS: tuple[type[Exception], ...] = (
    ConnectionError,
    TimeoutError,
    OSError,
)

_PERMANENT_ERRORS: tuple[type[Exception], ...] = (
    ValueError,
    TypeError,
    KeyError,
)


class AnnounceService:
    """Publishes child-to-parent announce messages via Redis Streams with retry.

    Replaces the bare _publish_agent_announce() function in execution.py
    with proper retry logic, exponential backoff, and error classification.
    """

    def __init__(
        self,
        redis_client: AsyncRedis,
        config: AnnounceConfig | None = None,
    ) -> None:
        super().__init__()
        self._redis = redis_client
        self._config = config or AnnounceConfig()
        self._pending_events: list[SubAgentAnnounceRetryEvent] = []

    def consume_pending_events(self) -> list[SubAgentAnnounceRetryEvent]:
        """Return and clear accumulated retry events."""
        events = list(self._pending_events)
        self._pending_events.clear()
        return events

    @staticmethod
    def classify_error(exc: Exception) -> ErrorCategory:
        """Classify an exception for retry decisions.

        Args:
            exc: The exception that occurred during announce.

        Returns:
            ErrorCategory indicating whether to retry.
        """
        if isinstance(exc, _TRANSIENT_ERRORS):
            return ErrorCategory.TRANSIENT
        if isinstance(exc, _PERMANENT_ERRORS):
            return ErrorCategory.PERMANENT
        return ErrorCategory.UNKNOWN

    async def publish_announce(
        self,
        agent_id: str,
        parent_session_id: str,
        child_session_id: str,
        result_content: str,
        success: bool,
        event_count: int = 0,
        execution_time_ms: float = 0.0,
    ) -> bool:
        """Publish announce message with retry.

        Returns True if published successfully, False if all retries exhausted.
        """
        announce_payload = self._build_payload(
            agent_id=agent_id,
            child_session_id=child_session_id,
            result_content=result_content,
            success=success,
            event_count=event_count,
            execution_time_ms=execution_time_ms,
        )
        message_data = self._build_message(
            agent_id=agent_id,
            parent_session_id=parent_session_id,
            announce_payload=announce_payload,
        )
        stream_key = f"agent:messages:{parent_session_id}"

        max_attempts = self._max_attempts_for_first_error()
        attempt = 0

        while True:
            try:
                await self._redis.xadd(
                    stream_key,
                    cast("dict[Any, Any]", {"data": json.dumps(message_data, default=str)}),
                )
                logger.info(
                    "Published announce: agent=%s child_session=%s parent_session=%s success=%s",
                    agent_id,
                    child_session_id,
                    parent_session_id,
                    success,
                )
                return True
            except Exception as exc:
                category = self.classify_error(exc)

                if category == ErrorCategory.PERMANENT:
                    logger.error(
                        "Permanent error publishing announce for agent=%s session=%s: %s",
                        agent_id,
                        child_session_id,
                        exc,
                    )
                    return False

                if attempt == 0:
                    max_attempts = self._resolve_max_attempts(category)

                if attempt >= max_attempts:
                    logger.error(
                        "All retries exhausted for announce agent=%s session=%s after %d attempts",
                        agent_id,
                        child_session_id,
                        attempt + 1,
                    )
                    return False

                delay_ms = self._config.delay_for_attempt(attempt)
                logger.warning(
                    (
                        "Retrying announce for agent=%s session=%s "
                        "attempt=%d/%d delay=%dms category=%s error=%s"
                    ),
                    agent_id,
                    child_session_id,
                    attempt + 1,
                    max_attempts,
                    delay_ms,
                    category.value,
                    exc,
                )

                self._pending_events.append(
                    SubAgentAnnounceRetryEvent(
                        agent_id=agent_id,
                        session_id=child_session_id,
                        attempt=attempt + 1,
                        max_retries=max_attempts,
                        delay_ms=delay_ms,
                        error=str(exc),
                        error_category=category.value,
                    )
                )

                await asyncio.sleep(delay_ms / 1000.0)
                attempt += 1

    def _max_attempts_for_first_error(self) -> int:
        return self._config.max_retries

    def _resolve_max_attempts(self, category: ErrorCategory) -> int:
        if category == ErrorCategory.TRANSIENT:
            return self._config.max_retries
        if category == ErrorCategory.UNKNOWN:
            return 1
        return 0

    @staticmethod
    def _build_payload(
        *,
        agent_id: str,
        child_session_id: str,
        result_content: str,
        success: bool,
        event_count: int,
        execution_time_ms: float,
    ) -> dict[str, Any]:
        return {
            "agent_id": agent_id,
            "session_id": child_session_id,
            "result": result_content[:500] if result_content else "",
            "artifacts": [],
            "success": success,
            "metadata": {
                "event_count": event_count,
                "execution_time_ms": round(execution_time_ms, 2),
            },
        }

    @staticmethod
    def _build_message(
        *,
        agent_id: str,
        parent_session_id: str,
        announce_payload: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "message_id": str(uuid.uuid4()),
            "from_agent_id": agent_id,
            "to_agent_id": "",
            "session_id": parent_session_id,
            "content": json.dumps(announce_payload),
            "message_type": "announce",
            "timestamp": datetime.now(UTC).isoformat(),
            "metadata": {"announce_payload": announce_payload},
            "parent_message_id": None,
        }
