"""Durable prepared model requests, recorded at the provider invocation boundary."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping
from contextlib import aclosing
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from .runtime import RuntimeV2Error
from .session_event_log import SESSION_EVENT_LOG_SERVICE_V2, SessionEventLogServiceV2
from .session_event_log_types import SessionEventRecordV2

if TYPE_CHECKING:
    from .model_request_transport import RequestCaptureV2

MODEL_REQUEST_PREPARED_EVENT_V2 = "model_request_prepared"
MODEL_REQUEST_SETTLED_EVENT_V2 = "model_request_settled"
_APPEND_CONFIRMATION_ATTEMPTS = 4


def prepared_model_request_v2(body: Mapping[str, Any]) -> dict[str, Any]:
    """Detach final provider fields, replacing inline media with hashes and artifact references."""
    try:
        result = json.loads(json.dumps(body, allow_nan=False))
    except (TypeError, ValueError) as error:
        raise RuntimeV2Error(
            "invalid_prepared_model_request", "Model request must be JSON serializable"
        ) from error
    if not isinstance(result, dict):
        raise RuntimeV2Error(
            "invalid_prepared_model_request", "Model request must be a JSON object"
        )
    from src.infrastructure.agent.native_computer_use.image_messages import redact_model_media

    return cast(dict[str, Any], redact_model_media(result))


@dataclass(frozen=True, kw_only=True)
class ModelRequestRecorderV2:
    """Append attempts using the session log owned by the pinned generation."""

    log: SessionEventLogServiceV2
    conversation_id: str
    message_id: str
    operation_id: str
    contributors: tuple[dict[str, Any], ...] = ()

    async def append(self, event: str, data: dict[str, Any]) -> None:
        attempt_id = data.get("attempt_id")
        if not isinstance(attempt_id, str) or not attempt_id:
            raise RuntimeV2Error("invalid_model_request_attempt", "Request attempt requires an ID")
        expected = prepared_model_request_v2(
            {
                **data,
                "operation_id": self.operation_id,
                "contributors": list(self.contributors),
                "plugin_generation": self.log.generation_resolver().to_payload(),
            }
        )
        for _ in range(_APPEND_CONFIRMATION_ATTEMPTS):
            cursor = await self.log.last_cursor(conversation_id=self.conversation_id)
            await self.log.append(
                conversation_id=self.conversation_id,
                message_id=self.message_id,
                correlation_id=self.operation_id,
                events=[
                    {
                        "type": event,
                        "data": expected,
                        "event_time_us": max(time.time_ns() // 1000, cursor.event_time_us + 1),
                        "event_counter": 0,
                    }
                ],
            )
            records = await self.log.store.read_message_events(
                conversation_id=self.conversation_id, message_id=self.message_id
            )
            matches = [
                record
                for record in records
                if record.conversation_id == self.conversation_id
                and record.message_id == self.message_id
                and record.event_type == event
                and record.event_data.get("attempt_id") == attempt_id
            ]
            if len(matches) == 1 and matches[0].event_data == expected:
                return
            if matches:
                raise RuntimeV2Error(
                    "model_request_record_mismatch", "Stored request differs from prepared input"
                )
            # The existing store ignores cursor conflicts. Re-read its committed
            # cursor before retrying, and never send an unconfirmed request.
        raise RuntimeV2Error(
            "model_request_record_unconfirmed", "Request event could not be durably confirmed"
        )


def current_model_request_recorder_v2(*, message_id: str) -> ModelRequestRecorderV2:
    from .boundary import current_operation_context_v2

    operation = current_operation_context_v2()
    log = operation.require(SESSION_EVENT_LOG_SERVICE_V2)
    if not isinstance(log, SessionEventLogServiceV2) or not operation.context.scope.session_id:
        raise RuntimeV2Error(
            "model_request_log_unavailable", "Prepared request requires session log"
        )
    return ModelRequestRecorderV2(
        log=log,
        conversation_id=operation.context.scope.session_id,
        message_id=message_id,
        operation_id=operation.operation_id,
        contributors=_request_contributors_v2(operation),
    )


def _request_contributors_v2(operation: object) -> tuple[dict[str, Any], ...]:
    """Persist only declaration identities; plugin configuration remains private."""
    from .runtime import FiberPhaseV2, OperationContextV2

    if not isinstance(operation, OperationContextV2):
        return ()
    scope = operation.context.scope
    events = frozenset(
        {
            "agent.session.start",
            "agent.before_request",
            "agent.before_prompt_build",
            "tools.before_execute",
            "tools.result_transform",
        }
    )
    result = []
    for fiber in operation.generation.fibers:
        if fiber.phase is not FiberPhaseV2.ACTIVE or any(
            getattr(fiber.entry.scope, field) is not None
            and getattr(fiber.entry.scope, field) != getattr(scope, field)
            for field in ("tenant_id", "project_id", "session_id")
        ):
            continue
        handled = [item.event for item in fiber.contract.events.handles if item.event in events]
        services = [
            item.service
            for item in fiber.contract.services.provides
            if item.service == "service:agent-runtime-dispatcher"
        ]
        if handled or services:
            result.append(
                {
                    "entry_id": fiber.entry.entry_id,
                    "module_ref": fiber.entry.module_ref,
                    "events": handled,
                    "services": services,
                }
            )
    return tuple(result)


async def recorded_completion_stream_v2(
    completion: Callable[..., Awaitable[Any]],
    kwargs: dict[str, Any],
    recorder: ModelRequestRecorderV2 | None,
    *,
    owned_transport: bool = False,
) -> AsyncGenerator[Any, None]:
    """Record actual serialized HTTP bodies after all provider transformations."""
    if recorder is None and not owned_transport:
        async with aclosing(_consume_completion_v2(completion, kwargs, None)) as source:
            async for chunk in source:
                yield chunk
        return
    from .model_request_transport import recording_client_v2

    async with (
        recording_client_v2(kwargs, recorder) as (recorded_kwargs, capture),
        aclosing(_consume_completion_v2(completion, recorded_kwargs, capture)) as source,
    ):
        async for chunk in source:
            yield chunk


async def _consume_completion_v2(
    completion: Callable[..., Awaitable[Any]],
    kwargs: dict[str, Any],
    capture: RequestCaptureV2 | None,
) -> AsyncGenerator[Any, None]:
    status = "cancelled"
    error_type: str | None = None
    response = None
    try:
        response = await completion(**kwargs)
        if capture is not None:
            capture.bind_response(response)
        async for chunk in response:
            yield chunk
        status = "completed"
    except (asyncio.CancelledError, GeneratorExit):
        raise
    except BaseException as error:
        status = "failed"
        error_type = type(error).__name__
        raise
    finally:
        try:
            close = getattr(response, "aclose", None)
            if close is not None:
                await close()
        finally:
            if capture is not None:
                await capture.settle(status, error_type)


async def replay_prepared_model_request_v2(
    log: SessionEventLogServiceV2,
    *,
    conversation_id: str,
    message_id: str,
    attempt_id: str,
) -> dict[str, Any]:
    """Read an immutable attempt without rebuilding prompts or loading plugins."""
    records = await log.store.read_message_events(
        conversation_id=conversation_id,
        message_id=message_id,
    )
    prepared: list[SessionEventRecordV2] = []
    for record in records:
        if record.conversation_id != conversation_id or record.message_id != message_id:
            raise RuntimeV2Error(
                "model_request_scope_mismatch", "Request log returned another scope"
            )
        if (
            record.event_type == MODEL_REQUEST_PREPARED_EVENT_V2
            and record.event_data.get("attempt_id") == attempt_id
        ):
            prepared.append(record)
    if len(prepared) != 1:
        raise RuntimeV2Error(
            "model_request_snapshot_missing", "No exact prepared request snapshot is available"
        )
    data = prepared[0].event_data
    if data.get("schema_version") != 1 or data.get("format") != "provider.http.json/v1":
        raise RuntimeV2Error(
            "model_request_snapshot_missing", "Legacy request log has no exact HTTP input snapshot"
        )
    return prepared_model_request_v2(data["request"])
