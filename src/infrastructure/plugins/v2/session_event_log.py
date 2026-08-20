"""Generation-scoped session event-log Provider for the v2 runtime spine."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .runtime import ContextV2, PluginDefinitionV2

SESSION_EVENT_LOG_MODULE_V2 = "builtin://memstack/session/event-log"
SESSION_EVENT_LOG_WRITER_SERVICE_V2 = "service:session-event-log-writer"

type SessionEventBatchWriterV2 = Callable[..., Awaitable[None]]


@dataclass(frozen=True, kw_only=True)
class SessionEventLogWriterV2:
    """Persist an ordered event batch through the active native transaction writer."""

    strategy: str

    async def persist(
        self,
        *,
        writer: SessionEventBatchWriterV2,
        conversation_id: str,
        message_id: str,
        events: list[dict[str, Any]],
        correlation_id: str | None,
    ) -> None:
        if not conversation_id.strip():
            raise ValueError("conversation_id must be non-empty")
        if not message_id.strip():
            raise ValueError("message_id must be non-empty")
        await writer(
            conversation_id=conversation_id,
            message_id=message_id,
            events=events,
            correlation_id=correlation_id,
        )


def _apply_session_event_log_writer_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    strategy = config.get("strategy")
    if strategy != "ordered-sql-event-log":
        raise ValueError("session event-log provider requires strategy ordered-sql-event-log")
    context.provide(
        SESSION_EVENT_LOG_WRITER_SERVICE_V2,
        SessionEventLogWriterV2(strategy=strategy),
        label="session-event-log-writer",
    )


def builtin_session_event_log_definition_v2() -> PluginDefinitionV2:
    return PluginDefinitionV2(
        module_ref=SESSION_EVENT_LOG_MODULE_V2,
        apply=_apply_session_event_log_writer_v2,
        provides=(SESSION_EVENT_LOG_WRITER_SERVICE_V2,),
    )


__all__ = [
    "SESSION_EVENT_LOG_MODULE_V2",
    "SESSION_EVENT_LOG_WRITER_SERVICE_V2",
    "SessionEventLogWriterV2",
    "builtin_session_event_log_definition_v2",
]
