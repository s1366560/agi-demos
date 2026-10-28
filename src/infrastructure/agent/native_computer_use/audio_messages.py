"""Hydrate owned native audio only at the selected Provider request boundary."""

from __future__ import annotations

import asyncio
import base64
import hashlib
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager, suppress
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TypeVar, cast

from src.domain.model.artifact.artifact import ArtifactStatus
from src.infrastructure.agent.native_computer_use.audio_authority import (
    require_audio_authority,
    require_current_audio_provider,
)
from src.infrastructure.agent.native_computer_use.store import DeviceBridgeError
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

if TYPE_CHECKING:
    from src.application.services.artifact_service import ArtifactService
    from src.domain.llm_providers.models import ProviderConfig
    from src.domain.model.artifact.artifact import Artifact

MAX_AUDIO_INPUT_BYTES = 32 * 1024 * 1024
MAX_AUDIO_INPUT_FILES = 4
_FORMATS = {"audio/wav": "wav", "audio/mpeg": "mp3"}
_T = TypeVar("_T")


@dataclass(frozen=True)
class AudioContext:
    service: ArtifactService | None
    scope: dict[str, Any]


_CONTEXT: ContextVar[AudioContext | None] = ContextVar("native_audio_context", default=None)


def bind_audio_context(
    service: ArtifactService | None,
    scope: dict[str, Any],
    session_id: str,
) -> Token[AudioContext | None]:
    return _CONTEXT.set(AudioContext(service, {**scope, "session_id": session_id}))


def reset_audio_context(token: Token[AudioContext | None]) -> None:
    _CONTEXT.reset(token)


def current_audio_scope() -> dict[str, Any]:
    context = _CONTEXT.get()
    return dict(context.scope) if context is not None else {}


def _invalid() -> RuntimeV2Error:
    return RuntimeV2Error(
        "computer_use_audio_invalid", "Audio input is not an owned current recording"
    )


async def _owned_artifact(context: AudioContext, reference: dict[str, Any]) -> Artifact:
    if context.service is None:
        raise _invalid()
    artifact_id = reference.get("artifact_id")
    if not isinstance(artifact_id, str) or not artifact_id:
        raise _invalid()
    artifact = await context.service.get_artifact(artifact_id)
    if (
        artifact is None
        or artifact.status != ArtifactStatus.READY
        or (artifact.tenant_id, artifact.project_id, artifact.conversation_id)
        != tuple(context.scope.get(key) for key in ("tenant_id", "project_id", "conversation_id"))
        or artifact.mime_type != reference.get("mime_type")
        or artifact.mime_type not in _FORMATS
        or artifact.size_bytes != reference.get("size_bytes")
        or not 0 < artifact.size_bytes <= MAX_AUDIO_INPUT_BYTES
    ):
        raise _invalid()
    raw_origin = artifact.metadata.get("native_audio_origin")
    if not isinstance(raw_origin, dict):
        raise _invalid()
    origin = cast(dict[str, Any], raw_origin)
    if origin.get("sha256") != reference.get("sha256"):
        raise _invalid()
    _, request = await require_audio_authority(context.scope, origin)
    if request.get("audio_artifacts", {}).get(artifact.id) != {
        "native_attachment_id": origin.get("native_attachment_id"),
        "sha256": reference.get("sha256"),
        "mime_type": artifact.mime_type,
        "size_bytes": artifact.size_bytes,
    }:
        raise _invalid()
    return artifact


@dataclass
class PreparedAudioInput:
    messages: list[dict[str, Any]]
    context: AudioContext | None = None
    provider: ProviderConfig | None = None
    references: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])

    async def validate(self) -> None:
        if not self.references:
            return
        if self.context is None or self.provider is None:
            raise _invalid()
        await require_current_audio_provider(self.provider)
        for reference in self.references:
            _ = await _owned_artifact(self.context, reference)

    async def wait(self, operation: Callable[[], Awaitable[_T]]) -> _T:
        """Cancel a pending provider operation when native or run authority is revoked."""
        if not self.references:
            return await operation()
        await self.validate()
        pending = asyncio.ensure_future(operation())
        try:
            while not pending.done():
                _ = await asyncio.wait({pending}, timeout=0.25)
                await self.validate()
            result = pending.result()
            await self.validate()
            return result
        finally:
            if not pending.done():
                _ = pending.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await pending

    async def stream(self, source: AsyncIterator[_T]) -> AsyncIterator[_T]:
        while True:
            try:
                item = await self.wait(lambda: anext(source))
            except StopAsyncIteration:
                return
            yield item

    @asynccontextmanager
    async def admission(
        self,
        acquire: Callable[[], Awaitable[AbstractAsyncContextManager[Any]]],
    ) -> AsyncIterator[None]:
        """Fence rate-limit queueing and release even a concurrently acquired permit."""
        permit: AbstractAsyncContextManager[Any] | None = None

        async def claim() -> None:
            nonlocal permit
            permit = await acquire()
            await permit.__aenter__()

        try:
            await self.wait(claim)
            yield
        finally:
            if permit is not None:
                await permit.__aexit__(None, None, None)

    async def complete(
        self,
        completion: Callable[..., Awaitable[_T]],
        kwargs: dict[str, Any],
    ) -> _T:
        if not self.references:
            return await completion(**kwargs)
        from src.infrastructure.plugins.v2.model_request_transport import recording_client_v2

        async with recording_client_v2(kwargs, None) as (owned_kwargs, capture):
            try:
                return await self.wait(lambda: completion(**owned_kwargs))
            finally:
                await capture.settle("completed", None)


def _omission(reason: str) -> dict[str, str]:
    return {
        "type": "text",
        "text": (
            "[Host: recording audio was omitted from this model request ("
            f"{reason}). The recording remains available as a user attachment.]"
        ),
    }


def _valid_audio(content: bytes, mime: str) -> bool:
    if mime == "audio/wav":
        return (
            len(content) >= 44
            and content[:4] == b"RIFF"
            and content[8:12] == b"WAVE"
            and int.from_bytes(content[4:8], "little") + 8 == len(content)
        )
    return mime == "audio/mpeg" and (
        content[:3] == b"ID3"
        or (len(content) >= 2 and content[0] == 0xFF and content[1] & 0xE0 == 0xE0)
    )


async def prepare_audio_input(
    messages: list[dict[str, Any]],
    *,
    supported: bool,
    provider: ProviderConfig | None,
) -> PreparedAudioInput:
    """Provider selection precedes capability, ownership and byte hydration checks."""
    context = _CONTEXT.get()
    prepared = PreparedAudioInput([], context, provider)
    total = 0
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            prepared.messages.append(dict(message))
            continue
        parts: list[Any] = []
        for raw_part in cast(list[object], content):
            if not isinstance(raw_part, dict):
                parts.append(raw_part)
                continue
            part = cast(dict[str, Any], raw_part)
            if part.get("type") in {"input_audio", "audio_url", "audio"}:
                # Callers cannot supply inline audio outside the verified artifact path.
                raise _invalid()
            if part.get("type") != "artifact_audio":
                parts.append(part)
                continue
            if not supported or provider is None:
                parts.append(_omission("model audio input is not explicitly enabled"))
                continue
            if context is None or context.service is None:
                parts.append(_omission("trusted recording context is unavailable"))
                continue
            try:
                await require_current_audio_provider(provider)
                artifact = await _owned_artifact(context, part)
                if len(prepared.references) >= MAX_AUDIO_INPUT_FILES or (
                    total + artifact.size_bytes > MAX_AUDIO_INPUT_BYTES
                ):
                    raise _invalid()
                content_bytes = await context.service.get_artifact_bytes(artifact.id)
                if (
                    content_bytes is None
                    or len(content_bytes) != artifact.size_bytes
                    or hashlib.sha256(content_bytes).hexdigest() != part.get("sha256")
                    or not _valid_audio(content_bytes, artifact.mime_type)
                ):
                    raise _invalid()
                _ = await _owned_artifact(context, part)
                await require_current_audio_provider(provider)
            except (RuntimeV2Error, DeviceBridgeError):
                parts.append(
                    _omission("recording ownership, format or current authority is invalid")
                )
                continue
            encoded = base64.b64encode(content_bytes).decode("ascii")
            from src.infrastructure.agent.native_computer_use.media_redaction import (
                register_model_media_reference,
            )

            register_model_media_reference(encoded, part)
            parts.append(
                {
                    "type": "input_audio",
                    "input_audio": {"data": encoded, "format": _FORMATS[artifact.mime_type]},
                }
            )
            prepared.references.append(dict(part))
            total += artifact.size_bytes
        prepared.messages.append({**message, "content": parts})
    return prepared
