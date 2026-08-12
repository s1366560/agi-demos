"""Avernet HTTP Provider protocol adapter for the existing Agent Runtime."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any, Literal, Protocol, cast

import httpx
from pydantic import BaseModel, ConfigDict, Field

from src.infrastructure.workspace_core.client import WorkspaceRuntimeCallbackAckRequest

logger = logging.getLogger(__name__)

ProviderMethod = Literal["chat.send", "chat.inject", "chat.abort", "chat.history"]
ProviderEventState = Literal["delta", "final", "aborted", "error"]
_DEFAULT_TERMINAL_CALLBACK_ATTEMPTS = 3
_DEFAULT_TERMINAL_CALLBACK_RETRY_DELAY_SECONDS = 0.25


def _empty_attachment_list() -> list[dict[str, Any]]:
    return []


class ProviderBotRef(BaseModel):
    model_config = ConfigDict(extra="allow")

    provider_id: str
    provider_bot_ref: str = ""
    tags: list[str] = Field(default_factory=list)


class ProviderWebhookRequest(BaseModel):
    """Provider request emitted by Avernet BCS."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    frame_type: Literal["req"] = Field(alias="type")
    id: str
    method: ProviderMethod
    run_id: str | None = None
    session_id: str
    bcn_group_id: str
    to_bot: ProviderBotRef
    message: Any | None = None
    attachments: list[dict[str, Any]] = Field(default_factory=_empty_attachment_list)
    before: int | None = None
    after: int | None = None
    limit: int | None = None
    timeout_ms: int = Field(gt=0)
    extensions: dict[str, Any] = Field(default_factory=dict)

    @property
    def correlation(self) -> dict[str, str]:
        """Return only the declared Workspace correlation fields."""
        names = (
            "workspace_id",
            "task_id",
            "plan_node_id",
            "conversation_id",
        )
        return {
            name: str(self.extensions[name])
            for name in names
            if self.extensions.get(name) is not None
        }


class ProviderRuntimeEvent(BaseModel):
    """One ordered Runtime event to return through Avernet `/bot/events`."""

    model_config = ConfigDict(extra="forbid")

    state: ProviderEventState
    sequence: int = Field(ge=0)
    message: dict[str, Any] | None = None
    error_message: str | None = None
    usage: dict[str, Any] | None = None
    stop_reason: str | None = None
    persisted: bool = False
    correlation_id: str | None = None


class ProviderAbortResult(BaseModel):
    """Proof that every execution substrate received cancellation."""

    model_config = ConfigDict(extra="forbid")

    ray_cancelled: bool
    local_worker_cancelled: bool
    terminal_event: ProviderRuntimeEvent | None = Field(default=None, exclude=True)

    @property
    def aborted(self) -> bool:
        return self.ray_cancelled or self.local_worker_cancelled


class ProviderHistoryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[dict[str, Any]]
    has_more: bool = False
    next_before: int | None = None
    next_after: int | None = None


class ProviderRuntimePort(Protocol):
    """Existing Agent Runtime capabilities consumed by the Provider adapter."""

    def stream_send(
        self,
        request: ProviderWebhookRequest,
    ) -> AsyncIterator[ProviderRuntimeEvent]: ...

    async def inject(self, request: ProviderWebhookRequest) -> None: ...

    async def abort(self, request: ProviderWebhookRequest) -> ProviderAbortResult: ...

    async def history(self, request: ProviderWebhookRequest) -> ProviderHistoryResult: ...


class ProviderEventSink(Protocol):
    """Authenticated `/bot/events` callback sink."""

    async def publish(
        self,
        request: ProviderWebhookRequest,
        event: ProviderRuntimeEvent,
    ) -> None: ...


class ProviderTerminalAcknowledger(Protocol):
    """Workspace Core callback acknowledgement authority."""

    async def acknowledge_runtime_terminal_callback(
        self,
        correlation_id: str,
        request: WorkspaceRuntimeCallbackAckRequest,
    ) -> object: ...


class AvernetProviderAdapter:
    """Translate Avernet Provider frames without owning Agent Runtime policy."""

    def __init__(
        self,
        runtime: ProviderRuntimePort,
        event_sink: ProviderEventSink,
        terminal_acknowledger: ProviderTerminalAcknowledger,
        *,
        terminal_callback_attempts: int = _DEFAULT_TERMINAL_CALLBACK_ATTEMPTS,
        terminal_callback_retry_delay_seconds: float = (
            _DEFAULT_TERMINAL_CALLBACK_RETRY_DELAY_SECONDS
        ),
    ) -> None:
        super().__init__()
        if terminal_callback_attempts <= 0:
            raise ValueError("terminal callback attempts must be positive")
        if terminal_callback_retry_delay_seconds < 0:
            raise ValueError("terminal callback retry delay must not be negative")
        self._runtime = runtime
        self._event_sink = event_sink
        self._terminal_acknowledger = terminal_acknowledger
        self._terminal_callback_attempts = terminal_callback_attempts
        self._terminal_callback_retry_delay_seconds = terminal_callback_retry_delay_seconds
        self._tasks: set[asyncio.Task[None]] = set()

    async def handle(self, request: ProviderWebhookRequest) -> dict[str, Any]:
        """Dispatch one structurally validated Provider method."""
        match request.method:
            case "chat.send":
                self._start_event_bridge(request)
                return {"ok": True}
            case "chat.inject":
                await self._runtime.inject(request)
                return {"ok": True}
            case "chat.abort":
                result = await self._runtime.abort(request)
                if result.terminal_event is not None:
                    if request.run_id is None:
                        raise RuntimeError("Avernet abort terminal is missing its target run id")
                    target_request = request.model_copy(update={"id": request.run_id})
                    await self._publish_terminal(target_request, result.terminal_event)
                return {
                    "ok": True,
                    "aborted": result.aborted,
                    "ray_cancelled": result.ray_cancelled,
                    "local_worker_cancelled": result.local_worker_cancelled,
                }
            case "chat.history":
                result = await self._runtime.history(request)
                return {
                    "ok": True,
                    "session_id": request.session_id,
                    "messages": result.messages,
                    "has_more": result.has_more,
                    "next_before": result.next_before,
                    "next_after": result.next_after,
                }

    def _start_event_bridge(self, request: ProviderWebhookRequest) -> None:
        task = asyncio.create_task(
            self._drive_send(request),
            name=f"avernet-provider:{request.id}",
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _drive_send(self, request: ProviderWebhookRequest) -> None:
        terminal_seen = False
        try:
            async for event in self._runtime.stream_send(request):
                if event.state in {"final", "aborted", "error"}:
                    await self._publish_terminal(request, event)
                    terminal_seen = True
                    break
                await self._event_sink.publish(request, event)
        except Exception:
            logger.exception(
                "Avernet Provider send bridge failed",
                extra={"run_id": request.id, **request.correlation},
            )
            return

        if not terminal_seen:
            logger.error(
                "Avernet Provider send ended without a persisted terminal event",
                extra={"run_id": request.id, **request.correlation},
            )

    async def _publish_terminal(
        self,
        request: ProviderWebhookRequest,
        event: ProviderRuntimeEvent,
    ) -> None:
        for attempt in range(1, self._terminal_callback_attempts + 1):
            try:
                await self._event_sink.publish(request, event)
                await self._acknowledge_terminal(request, event)
                return
            except Exception:
                if attempt == self._terminal_callback_attempts:
                    raise
                logger.warning(
                    "Retrying persisted Avernet terminal callback",
                    extra={
                        "run_id": request.id,
                        "sequence": event.sequence,
                        "callback_attempt": attempt,
                        **request.correlation,
                    },
                )
                delay = self._terminal_callback_retry_delay_seconds * (2 ** (attempt - 1))
                await asyncio.sleep(delay)

    async def _acknowledge_terminal(
        self,
        request: ProviderWebhookRequest,
        event: ProviderRuntimeEvent,
    ) -> None:
        if event.correlation_id is None:
            raise RuntimeError("Avernet terminal callback is missing its correlation id")
        _ = await self._terminal_acknowledger.acknowledge_runtime_terminal_callback(
            event.correlation_id,
            WorkspaceRuntimeCallbackAckRequest(
                tenant_id=_required_extension(request, "tenant_id"),
                project_id=_required_extension(request, "project_id"),
                workspace_id=_required_extension(request, "workspace_id"),
            ),
        )

    async def wait_until_idle(self) -> None:
        """Wait for tracked send bridges during tests or graceful shutdown."""
        while self._tasks:
            _ = await asyncio.gather(*tuple(self._tasks))


class AvernetBotEventHttpSink:
    """Authenticated callback-streaming sink for Avernet `/bot/events`."""

    def __init__(
        self,
        *,
        base_url: str,
        event_token: str,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        super().__init__()
        if not base_url.strip() or not event_token.strip():
            raise ValueError("Avernet bot event sink requires a base URL and token")
        self._base_url = base_url
        self._event_token = event_token
        self._transport = transport
        self._timeout_seconds = timeout_seconds

    async def publish(
        self,
        request: ProviderWebhookRequest,
        event: ProviderRuntimeEvent,
    ) -> None:
        if event.state in {"final", "aborted", "error"} and not event.persisted:
            raise RuntimeError("Avernet terminal callback requires persisted history")
        text = _runtime_event_text(event)
        message_content = {"content": [{"type": "text", "text": text}]} if text else None
        payload = {
            "run_id": request.id,
            "seq": event.sequence,
            "state": event.state,
            "event": "chat",
            "message": {"text": text},
            "payload": {
                "run_id": request.id,
                "bcs_group_id": request.bcn_group_id,
                "state": event.state,
                "message": message_content,
                "delta_text": text if event.state == "delta" else None,
                "usage": event.usage,
                "stop_reason": event.stop_reason,
                "errorMessage": event.error_message,
                "extensions": request.correlation,
            },
        }
        headers = {
            "Authorization": f"Bearer {self._event_token}",
            "Content-Type": "application/json",
            "X-BCN-Provider-Id": request.to_bot.provider_id,
        }
        if request.to_bot.provider_bot_ref:
            headers["X-BCN-Provider-Bot-Ref"] = request.to_bot.provider_bot_ref
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout_seconds,
                transport=self._transport,
            ) as client:
                response = await client.post("/bot/events", json=payload, headers=headers)
                _ = response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 410 and event.state in {"final", "aborted", "error"}:
                logger.info(
                    "Avernet terminal callback already completed upstream",
                    extra={"run_id": request.id, "sequence": event.sequence},
                )
                return
            raise RuntimeError("Avernet bot event callback failed") from exc
        except httpx.HTTPError as exc:
            raise RuntimeError("Avernet bot event callback failed") from exc


def _runtime_event_text(event: ProviderRuntimeEvent) -> str:
    if event.error_message:
        return event.error_message
    if event.message is None:
        return ""
    content = event.message.get("content")
    if isinstance(content, str):
        return content
    raw_data: object | None = event.message.get("data")
    if isinstance(raw_data, dict):
        data = cast("dict[str, object]", raw_data)
        for key in ("delta", "text", "content", "message"):
            value = data.get(key)
            if isinstance(value, str):
                return value
    return ""


def _required_extension(request: ProviderWebhookRequest, name: str) -> str:
    value = request.extensions.get(name)
    if value is None or not str(value).strip():
        raise ValueError(f"Avernet Provider request requires extensions.{name}")
    return str(value)
