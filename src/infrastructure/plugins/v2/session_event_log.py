"""Generation-scoped authoritative session event log for protocol v2."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.agent.events.converter import normalize_event_dict

from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)
from .session_event_log_types import (
    SessionEventCursorV2,
    SessionEventLogStoreV2,
    SessionEventRecordV2,
)

SESSION_EVENT_LOG_MODULE_V2 = "builtin://memstack/session/event-log"
SESSION_EVENT_LOG_SERVICE_V2 = "service:session-event-log"

TURN_ADMITTED_EVENT_V2 = "turn_admitted"
MODEL_MESSAGE_COMMITTED_EVENT_V2 = "model_message_committed"
HITL_TOOL_RESULT_APPLIED_EVENT_V2 = "hitl_tool_result_applied"

_TYPED_MODEL_EVENT_TYPES = frozenset(
    {
        TURN_ADMITTED_EVENT_V2,
        MODEL_MESSAGE_COMMITTED_EVENT_V2,
        HITL_TOOL_RESULT_APPLIED_EVENT_V2,
    }
)
_LEGACY_MODEL_EVENT_ROLES = {
    "user_message": "user",
    "assistant_message": "assistant",
}
_MODEL_ROLES = frozenset({"assistant", "system", "tool", "user"})


type GenerationResolverV2 = Callable[[], PluginGenerationDescriptorV2]


def _current_operation_generation_v2() -> PluginGenerationDescriptorV2:
    """Resolve generation identity from the active operation, never a caller payload."""
    from .boundary import current_operation_context_v2

    return current_operation_context_v2().descriptor


def _require_identifier(value: str, *, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")


def _normalize_for_append(
    event: Mapping[str, Any],
    *,
    descriptor: PluginGenerationDescriptorV2,
) -> dict[str, Any]:
    normalized = normalize_event_dict(event)
    if normalized is None:
        raise RuntimeV2Error(
            "invalid_session_event",
            "session event must have a non-empty type",
        )

    event_data = dict(normalized["data"])
    descriptor_payload = descriptor.to_payload()
    existing_descriptor = event_data.get("plugin_generation")
    if existing_descriptor is not None:
        if not isinstance(existing_descriptor, Mapping):
            raise RuntimeV2Error(
                "invalid_generation_descriptor",
                "session event generation descriptor must be an object",
            )
        try:
            parsed = PluginGenerationDescriptorV2.from_payload(
                dict(cast(Mapping[str, Any], existing_descriptor))
            )
        except (TypeError, ValueError) as exc:
            raise RuntimeV2Error(
                "invalid_generation_descriptor",
                "session event generation descriptor is invalid",
            ) from exc
        if parsed != descriptor:
            raise RuntimeV2Error(
                "generation_descriptor_mismatch",
                "session event generation does not match the pinned operation",
            )
    event_data["plugin_generation"] = descriptor_payload

    prepared = dict(normalized)
    prepared["data"] = event_data
    if "timestamp" not in event:
        _ = prepared.pop("timestamp", None)
    return prepared


def _typed_model_message(record: SessionEventRecordV2) -> dict[str, Any]:
    raw_message = record.event_data.get("model_message")
    if not isinstance(raw_message, Mapping):
        raise RuntimeV2Error(
            "invalid_model_message_event",
            f"session event {record.event_id} has no model_message object",
        )
    message: dict[str, Any] = dict(cast(Mapping[str, Any], raw_message))
    role = message.get("role")
    if not isinstance(role, str) or role not in _MODEL_ROLES:
        raise RuntimeV2Error(
            "invalid_model_message_event",
            f"session event {record.event_id} has an invalid model-message role",
        )
    if "content" not in message and not (
        role == "assistant" and isinstance(message.get("tool_calls"), list)
    ):
        raise RuntimeV2Error(
            "invalid_model_message_event",
            f"session event {record.event_id} has no model-visible content",
        )
    if role == "tool" and not (
        isinstance(message.get("tool_call_id"), str) and message["tool_call_id"].strip()
    ):
        raise RuntimeV2Error(
            "invalid_model_message_event",
            f"session event {record.event_id} has no tool_call_id",
        )
    return message


def _legacy_model_message(record: SessionEventRecordV2) -> dict[str, Any]:
    role = record.event_data.get("role", _LEGACY_MODEL_EVENT_ROLES[record.event_type])
    if not isinstance(role, str) or role not in _MODEL_ROLES:
        raise RuntimeV2Error(
            "invalid_model_message_event",
            f"legacy session event {record.event_id} has an invalid role",
        )
    message: dict[str, Any] = {
        "role": role,
        "content": record.event_data.get("content", ""),
    }
    for field_name in ("name", "tool_call_id", "tool_calls"):
        if field_name in record.event_data:
            message[field_name] = record.event_data[field_name]
    return message


@dataclass(frozen=True, kw_only=True)
class SessionEventLogServiceV2:
    """The sole v2 authority for append, model materialization, and cursors."""

    strategy: str
    store: SessionEventLogStoreV2 = field(repr=False, compare=False)
    generation_resolver: GenerationResolverV2 = field(
        default=_current_operation_generation_v2,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if self.strategy != "ordered-sql-event-log":
            raise ValueError("session event-log service requires strategy ordered-sql-event-log")

    async def append(
        self,
        *,
        conversation_id: str,
        message_id: str,
        events: Sequence[Mapping[str, Any]],
        correlation_id: str | None = None,
    ) -> None:
        """Append through the owned store and propagate every persistence failure."""
        _require_identifier(conversation_id, field_name="conversation_id")
        _require_identifier(message_id, field_name="message_id")
        if not events:
            return
        descriptor = self.generation_resolver()
        prepared = [_normalize_for_append(event, descriptor=descriptor) for event in events]
        await self.store.append_stream_events(
            conversation_id=conversation_id,
            message_id=message_id,
            events=prepared,
            correlation_id=correlation_id,
        )

    async def materialize_model_messages(
        self,
        *,
        conversation_id: str,
        after: SessionEventCursorV2 | None = None,
        exclude_event_id: str | None = None,
        page_size: int = 1000,
    ) -> list[dict[str, Any]]:
        """Materialize only declared model-visible events in exact cursor order."""
        _require_identifier(conversation_id, field_name="conversation_id")
        if page_size <= 0:
            raise ValueError("page_size must be positive")
        messages: list[dict[str, Any]] = []
        cursor = after
        while True:
            records = sorted(
                await self.store.read_events(
                    conversation_id=conversation_id,
                    after=cursor,
                    limit=page_size,
                ),
                key=lambda item: item.cursor,
            )
            if not records:
                break
            previous_cursor = cursor
            for record in records:
                if previous_cursor is not None and record.cursor <= previous_cursor:
                    raise RuntimeV2Error(
                        "invalid_session_event_order",
                        "session event store returned a non-increasing cursor",
                    )
                previous_cursor = record.cursor
                if exclude_event_id is not None and record.event_id == exclude_event_id:
                    continue
                if record.event_type in _TYPED_MODEL_EVENT_TYPES:
                    messages.append(_typed_model_message(record))
                elif record.event_type in _LEGACY_MODEL_EVENT_ROLES:
                    messages.append(_legacy_model_message(record))
            cursor = records[-1].cursor
            if len(records) < page_size:
                break
        return messages

    async def last_cursor(self, *, conversation_id: str) -> SessionEventCursorV2:
        """Return the exact durable tail cursor for one conversation."""
        _require_identifier(conversation_id, field_name="conversation_id")
        return await self.store.last_cursor(conversation_id=conversation_id)


def _apply_session_event_log_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    strategy = config.get("strategy")
    if strategy != "ordered-sql-event-log":
        raise ValueError("session event-log provider requires strategy ordered-sql-event-log")

    from .session_event_log_store import SqlSessionEventLogStoreV2

    _ = context.provide(
        SESSION_EVENT_LOG_SERVICE_V2,
        SessionEventLogServiceV2(
            strategy=strategy,
            store=SqlSessionEventLogStoreV2(),
        ),
        label="session-event-log-service",
    )


def builtin_session_event_log_definition_v2() -> PluginDefinitionV2:
    return PluginDefinitionV2(
        module_ref=SESSION_EVENT_LOG_MODULE_V2,
        contract_digest=generated_contract_digest_v2(SESSION_EVENT_LOG_MODULE_V2),
        apply=_apply_session_event_log_v2,
    )


__all__ = [
    "HITL_TOOL_RESULT_APPLIED_EVENT_V2",
    "MODEL_MESSAGE_COMMITTED_EVENT_V2",
    "SESSION_EVENT_LOG_MODULE_V2",
    "SESSION_EVENT_LOG_SERVICE_V2",
    "TURN_ADMITTED_EVENT_V2",
    "SessionEventCursorV2",
    "SessionEventLogServiceV2",
    "SessionEventLogStoreV2",
    "SessionEventRecordV2",
    "builtin_session_event_log_definition_v2",
]
