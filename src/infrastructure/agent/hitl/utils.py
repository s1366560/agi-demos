"""Shared HITL utilities for request identity, scoping, and text sanitization."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from html import escape, unescape
from typing import TYPE_CHECKING, Any, Protocol, cast

if TYPE_CHECKING:
    from src.infrastructure.security.encryption_service import EncryptionService

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ENV_VAR_NAME_MAX_LEN = 100
_ENV_VAR_NAME_RE = re.compile(rf"^[A-Z][A-Z0-9_]{{0,{_ENV_VAR_NAME_MAX_LEN - 1}}}$")
_HITL_STREAM_RESPONSE_ENCODING = "aes256gcm+json"
_PROCESSING_STARTED_AT_KEY = "processing_started_at"
_PROCESSING_HEARTBEAT_AT_KEY = "processing_heartbeat_at"
_PROCESSING_OWNER_KEY = "processing_owner"
_ENCRYPTED_STREAM_HITL_TYPES = frozenset({"env_var", "a2ui_action"})
_SAFE_ENV_CONTEXT_KEYS = frozenset(
    {
        "help_url",
        "hint",
        "project_id",
        "provider",
        "reason",
        "requested_variables",
        "required_for",
        "save_scope",
        "source",
        "step",
        "tool_name",
        "workflow",
    }
)
_SENSITIVE_CONTEXT_KEYWORDS = (
    "auth",
    "cookie",
    "credential",
    "jwt",
    "key",
    "password",
    "secret",
    "token",
)
_SECRET_LIKE_ENV_VAR_PATTERNS = (
    re.compile(r"^(?:AKIA|ASIA)[A-Z0-9]{16}$"),
    re.compile(r"^GHP_[A-Z0-9]{20,}$"),
    re.compile(r"^GH(?:S|U|O|P)_[A-Z0-9]{20,}$"),
    re.compile(r"^GITHUB_PAT_[A-Z0-9_]{20,}$"),
    re.compile(r"^SK-PROJ-[A-Z0-9_-]{16,}$"),
    re.compile(r"^SK(?:_LIVE|_TEST)?_[A-Z0-9_]{16,}$"),
    re.compile(r"^MS_SK_[A-F0-9]{16,}$"),
    re.compile(r"^XOX[COPRSAB]-[A-Z0-9-]{10,}$"),
    re.compile(r"^XOX[BAPRS]_[A-Z0-9_]{10,}$"),
)
_SECRET_LIKE_TEXT_PATTERNS = (
    re.compile(r"(?i)\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"(?i)\bGHP_[A-Z0-9]{20,}\b"),
    re.compile(r"(?i)\bGH(?:S|U|O|P)_[A-Z0-9]{20,}\b"),
    re.compile(r"(?i)\bGITHUB_PAT_[A-Z0-9_]{20,}\b"),
    re.compile(r"(?i)\bBEARER\s+[A-Z0-9._-]{16,}\b"),
    re.compile(r"(?i)\bSK-PROJ-[A-Z0-9_-]{16,}\b"),
    re.compile(r"(?i)\bSK-[A-Z0-9]{16,}\b"),
    re.compile(r"(?i)\bSK(?:_LIVE|_TEST)?_[A-Z0-9_]{16,}\b"),
    re.compile(r"(?i)\bMS_SK_[A-F0-9]{16,}\b"),
    re.compile(r"(?i)\bXOX[COPRSAB]-[A-Z0-9-]{10,}\b"),
    re.compile(r"(?i)\bXOX[BAPRS]_[A-Z0-9_]{10,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
)
_SECRET_TEXT_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{8,}")


class HITLRequestRecord(Protocol):
    """Attribute-based view of a persisted HITL request."""

    @property
    def id(self) -> str: ...

    @property
    def request_type(self) -> object: ...

    @property
    def question(self) -> str | None: ...

    @property
    def options(self) -> object: ...

    @property
    def context(self) -> object: ...

    @property
    def metadata(self) -> object: ...

    @property
    def response(self) -> object: ...

    @property
    def response_metadata(self) -> object: ...


_hitl_stream_encryption_service: EncryptionService | None = None


def resolve_trusted_hitl_type(hitl_request: HITLRequestRecord) -> str | None:
    """Return the trusted logical HITL type stored with a request."""
    request_metadata = _request_metadata_dict(hitl_request)
    metadata_type = request_metadata.get("hitl_type")
    if isinstance(metadata_type, str) and metadata_type:
        return metadata_type

    request_type = getattr(hitl_request, "request_type", None)
    request_type_value = getattr(request_type, "value", request_type)
    if isinstance(request_type_value, str) and request_type_value:
        return request_type_value
    return None


def merge_processing_lease_metadata(
    response_metadata: object,
    *,
    lease_time: datetime,
    lease_owner: str | None = None,
) -> dict[str, Any]:
    """Return response metadata with an updated processing lease heartbeat."""
    metadata: dict[str, Any] = (
        dict(response_metadata) if isinstance(response_metadata, Mapping) else {}
    )
    lease_time_iso = lease_time.astimezone(UTC).isoformat()
    metadata[_PROCESSING_HEARTBEAT_AT_KEY] = lease_time_iso
    metadata.setdefault(_PROCESSING_STARTED_AT_KEY, lease_time_iso)
    if lease_owner:
        metadata[_PROCESSING_OWNER_KEY] = lease_owner
    return metadata


def clear_processing_lease_metadata(response_metadata: object) -> dict[str, Any] | None:
    """Return response metadata without transient processing lease keys."""
    if not isinstance(response_metadata, Mapping):
        return None
    metadata = dict(response_metadata)
    metadata.pop(_PROCESSING_STARTED_AT_KEY, None)
    metadata.pop(_PROCESSING_HEARTBEAT_AT_KEY, None)
    metadata.pop(_PROCESSING_OWNER_KEY, None)
    return metadata or None


def _parse_processing_lease_time(value: object) -> datetime | None:
    """Parse an ISO-8601 processing lease timestamp."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def get_processing_lease_time(hitl_request: HITLRequestRecord) -> datetime | None:
    """Return the freshest persisted processing lease timestamp for a HITL request."""
    response_metadata_raw = getattr(hitl_request, "response_metadata", None)
    response_metadata = response_metadata_raw if isinstance(response_metadata_raw, Mapping) else {}
    heartbeat_at = _parse_processing_lease_time(response_metadata.get(_PROCESSING_HEARTBEAT_AT_KEY))
    if heartbeat_at is not None:
        return heartbeat_at
    return _parse_processing_lease_time(response_metadata.get(_PROCESSING_STARTED_AT_KEY))


def get_processing_owner(hitl_request: HITLRequestRecord) -> str | None:
    """Return the persisted processing lease owner for a HITL request, if present."""
    response_metadata_raw = getattr(hitl_request, "response_metadata", None)
    response_metadata = response_metadata_raw if isinstance(response_metadata_raw, Mapping) else {}
    owner = response_metadata.get(_PROCESSING_OWNER_KEY)
    return owner if isinstance(owner, str) and owner else None


def is_processing_lease_stale(
    hitl_request: HITLRequestRecord,
    *,
    before: datetime,
) -> bool:
    """Return True when the persisted processing lease is older than the cutoff."""
    lease_time = get_processing_lease_time(hitl_request)
    return lease_time is not None and lease_time < before


def _get_hitl_stream_encryption_service() -> EncryptionService:
    """Return the dedicated encryption service for HITL secret payloads."""
    global _hitl_stream_encryption_service
    if _hitl_stream_encryption_service is None:
        from src.configuration.config import get_settings
        from src.infrastructure.security.encryption_service import EncryptionService

        settings = get_settings()
        encryption_key = settings.llm_encryption_key
        if not encryption_key:
            raise RuntimeError(
                "LLM_ENCRYPTION_KEY is required for sensitive HITL payload encryption"
            )
        _hitl_stream_encryption_service = EncryptionService(encryption_key)
    return _hitl_stream_encryption_service


def serialize_hitl_stream_response(
    hitl_type: str,
    response_data: dict[str, Any],
) -> dict[str, Any]:
    """Return a stream-safe HITL response payload."""
    if hitl_type not in _ENCRYPTED_STREAM_HITL_TYPES:
        return {"response_data": response_data}

    encryption_service = _get_hitl_stream_encryption_service()
    encrypted_payload = encryption_service.encrypt(
        json.dumps(response_data, separators=(",", ":"), ensure_ascii=False)
    )
    return {
        "response_data_encrypted": encrypted_payload,
        "response_data_encoding": _HITL_STREAM_RESPONSE_ENCODING,
    }


def seal_hitl_response_data(hitl_type: str, response_data: dict[str, Any]) -> dict[str, Any]:
    """Return sealed response metadata for recoverable HITL payloads."""
    if hitl_type not in {"env_var", "a2ui_action"}:
        return {}

    encryption_service = _get_hitl_stream_encryption_service()
    encrypted_payload = encryption_service.encrypt(
        json.dumps(response_data, separators=(",", ":"), ensure_ascii=False)
    )
    return {
        "sealed_response": encrypted_payload,
        "sealed_response_encoding": _HITL_STREAM_RESPONSE_ENCODING,
    }


def unseal_hitl_response_data(response_metadata: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return the sealed HITL response payload from response metadata when present."""
    encrypted_payload = response_metadata.get("sealed_response")
    if not isinstance(encrypted_payload, str):
        return None

    encoding = response_metadata.get("sealed_response_encoding")
    if encoding != _HITL_STREAM_RESPONSE_ENCODING:
        raise ValueError("Unsupported sealed HITL response encoding")

    encryption_service = _get_hitl_stream_encryption_service()
    decrypted_payload = encryption_service.decrypt(encrypted_payload)
    decoded_response = json.loads(decrypted_payload)
    if not isinstance(decoded_response, dict):
        raise ValueError("Decoded sealed HITL response must be an object")
    return decoded_response


def _restore_choice_like_response(summary: str) -> str | list[str]:
    """Recover a stored clarification/decision response from its persisted summary."""
    try:
        decoded_summary = json.loads(summary)
    except json.JSONDecodeError:
        return summary
    if isinstance(decoded_summary, list) and all(isinstance(item, str) for item in decoded_summary):
        return decoded_summary
    if isinstance(decoded_summary, str):
        return decoded_summary
    return summary


def _restore_summary_hitl_response(
    hitl_type: str,
    response_summary: str,
    response_metadata: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Restore non-encrypted HITL response payloads from persisted summaries."""
    restored_response: dict[str, Any] | None = None
    if hitl_type == "clarification":
        restored_response = {"answer": _restore_choice_like_response(response_summary)}
    elif hitl_type == "decision":
        restored_response = {"decision": _restore_choice_like_response(response_summary)}
    elif hitl_type == "permission":
        normalized_response = response_summary.strip().lower()
        if normalized_response in {"true", "false"}:
            restored_response = {"granted": normalized_response == "true"}
        else:
            restored_response = {"action": response_summary}
    elif hitl_type == "a2ui_action":
        source_component_id = response_metadata.get("source_component_id")
        context = response_metadata.get("context")
        if isinstance(source_component_id, str) and isinstance(context, Mapping):
            restored_response = {
                "action_name": response_summary,
                "source_component_id": source_component_id,
                "context": dict(context),
            }
    return restored_response


def restore_persisted_hitl_response(
    hitl_request: HITLRequestRecord,
) -> dict[str, Any] | None:
    """Reconstruct a validated HITL response payload from persisted request fields."""
    hitl_type = resolve_trusted_hitl_type(hitl_request)
    if hitl_type is None:
        return None

    response_metadata_raw = getattr(hitl_request, "response_metadata", None)
    response_metadata = response_metadata_raw if isinstance(response_metadata_raw, Mapping) else {}

    restored_response: dict[str, Any] | None = None
    if "sealed_response" in response_metadata:
        restored_response = unseal_hitl_response_data(response_metadata)
        if restored_response is not None:
            return restored_response

    if hitl_type == "env_var":
        return unseal_hitl_response_data(response_metadata)

    response_summary = getattr(hitl_request, "response", None)
    if not isinstance(response_summary, str) or not response_summary:
        return None

    return _restore_summary_hitl_response(hitl_type, response_summary, response_metadata)


async def load_persisted_hitl_request(request_id: str) -> HITLRequestRecord | None:
    """Load the authoritative persisted HITL request for stream consumers."""
    from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
    from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
        SqlHITLRequestRepository,
    )

    async with async_session_factory() as session:
        repo = SqlHITLRequestRepository(session)
        return await repo.get_by_id(request_id)


async def refresh_processing_lease(
    request_id: str,
    *,
    lease_owner: str | None = None,
) -> bool:
    """Persist a fresh heartbeat for an in-flight PROCESSING request."""
    from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
    from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
        SqlHITLRequestRepository,
    )

    async with async_session_factory() as session:
        repo = SqlHITLRequestRepository(session)
        refreshed = await repo.refresh_processing_lease(request_id, lease_owner=lease_owner)
        if refreshed:
            await session.commit()
        return refreshed


@asynccontextmanager
async def processing_lease_heartbeat(
    request_id: str,
    *,
    lease_owner: str | None = None,
    interval_seconds: float = 15.0,
) -> AsyncIterator[None]:
    """Keep the persisted processing lease fresh while a continuation is running."""
    stop_event = asyncio.Event()

    async def _heartbeat_loop() -> None:
        while not stop_event.is_set():
            refreshed = await refresh_processing_lease(request_id, lease_owner=lease_owner)
            if not refreshed:
                return
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
            except TimeoutError:
                continue

    heartbeat_task = asyncio.create_task(_heartbeat_loop())
    try:
        yield
    finally:
        stop_event.set()
        heartbeat_task.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat_task


def is_permanent_hitl_resume_error(error_message: str | None) -> bool:
    """Return True when a continue_chat error is a terminal validation rejection."""
    if not isinstance(error_message, str):
        return False
    return (
        error_message == "HITL state not found or expired"
        or error_message.startswith("Rejected ")
        or error_message.startswith("Unsupported HITL type:")
    )


def deserialize_hitl_stream_response(
    payload: Mapping[str, Any],
    *,
    expected_hitl_type: str | None = None,
) -> dict[str, Any]:
    """Decode HITL response payloads from Redis streams."""
    encrypted_payload = payload.get("response_data_encrypted")
    if isinstance(encrypted_payload, str):
        encoding = payload.get("response_data_encoding")
        if encoding != _HITL_STREAM_RESPONSE_ENCODING:
            raise ValueError("Unsupported HITL stream response encoding")

        encryption_service = _get_hitl_stream_encryption_service()
        decrypted_payload = encryption_service.decrypt(encrypted_payload)
        decoded_response = json.loads(decrypted_payload)
        if not isinstance(decoded_response, dict):
            raise ValueError("Decoded HITL stream response must be an object")
        return decoded_response

    if expected_hitl_type in _ENCRYPTED_STREAM_HITL_TYPES:
        raise ValueError(f"{expected_hitl_type} HITL stream responses must use encrypted payloads")

    response_data_raw = payload.get("response_data", {})
    if isinstance(response_data_raw, str):
        try:
            decoded_response = json.loads(response_data_raw)
        except json.JSONDecodeError:
            return {"answer": response_data_raw}
        if not isinstance(decoded_response, dict):
            raise ValueError("Decoded HITL stream response must be an object")
        return decoded_response

    if isinstance(response_data_raw, dict):
        return response_data_raw

    raise ValueError("Unsupported HITL stream response payload")


def fully_unescape_hitl_text(value: str) -> str:
    """Collapse nested HTML entities and strip control characters."""
    candidate = _CONTROL_CHARS_RE.sub("", value)
    while True:
        unescaped = _CONTROL_CHARS_RE.sub("", unescape(candidate))
        if unescaped == candidate:
            return candidate
        candidate = unescaped


def sanitize_hitl_text(value: object) -> str | None:
    """Return a plain-text-safe HITL string or None when it becomes empty."""
    if not isinstance(value, str):
        return None
    candidate = unescape(_CONTROL_CHARS_RE.sub("", value)).strip()
    if not candidate:
        return None
    return escape(candidate)


def is_secret_like_env_var_value(candidate: str) -> bool:
    """Return True when a value fully matches a high-confidence secret shape."""
    normalized = candidate.upper()
    return any(pattern.fullmatch(normalized) for pattern in _SECRET_LIKE_ENV_VAR_PATTERNS)


def normalize_env_var_name(value: object) -> str:
    """Validate and normalize an env-var identifier for HITL requests."""
    if not isinstance(value, str):
        return ""
    candidate = value.strip()
    if not candidate or not _ENV_VAR_NAME_RE.fullmatch(candidate):
        return ""
    if is_secret_like_env_var_value(candidate):
        return ""
    return candidate


def contains_secret_like_text(value: str) -> bool:
    """Detect secret-like tokens in freeform text."""
    if any(pattern.search(value) for pattern in _SECRET_LIKE_TEXT_PATTERNS):
        return True
    return any(
        is_secret_like_env_var_value(token) for token in _SECRET_TEXT_TOKEN_RE.findall(value)
    )


def sanitize_env_var_plain_text(value: object) -> str | None:
    """Return secret-safe plain text for env-var metadata or None."""
    if not isinstance(value, str):
        return None
    candidate = fully_unescape_hitl_text(value).strip()
    if not candidate or contains_secret_like_text(candidate):
        return None
    return candidate


def sanitize_env_var_text(value: object) -> str | None:
    """Return HTML-safe env-var metadata or None when unsafe."""
    candidate = sanitize_env_var_plain_text(value)
    if candidate is None:
        return None
    return escape(candidate)


def sanitize_hitl_scalar(value: object) -> bool | int | float | str | None:
    """Return a safe scalar value for HITL payloads."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    return sanitize_hitl_text(value)


def sanitize_env_var_scalar(value: object) -> bool | int | float | str | None:
    """Return a safe scalar value for env-var HITL payloads."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    return sanitize_env_var_text(value)


def sanitize_hitl_sequence(value: object) -> list[bool | int | float | str] | None:
    """Return a safe list value for HITL payloads."""
    if not isinstance(value, (list, tuple)):
        return None
    sanitized_items: list[bool | int | float | str] = []
    for item in value:
        sanitized_item = sanitize_hitl_scalar(item)
        if sanitized_item is None:
            return None
        sanitized_items.append(sanitized_item)
    return sanitized_items or None


def sanitize_env_var_sequence(value: object) -> list[bool | int | float | str] | None:
    """Return a safe list value for env-var HITL payloads."""
    if not isinstance(value, (list, tuple)):
        return None
    sanitized_items: list[bool | int | float | str] = []
    for item in value:
        sanitized_item = sanitize_env_var_scalar(item)
        if sanitized_item is None:
            return None
        sanitized_items.append(sanitized_item)
    return sanitized_items or None


def sanitize_hitl_context(raw_context: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a context dict that contains only safe scalar or list values."""
    if raw_context is None:
        return {}

    sanitized_context: dict[str, Any] = {}
    for key, value in raw_context.items():
        sanitized_key = sanitize_hitl_text(key)
        if sanitized_key is None:
            continue
        sanitized_scalar = sanitize_hitl_scalar(value)
        if sanitized_scalar is not None:
            sanitized_context[sanitized_key] = sanitized_scalar
            continue
        sanitized_sequence = sanitize_hitl_sequence(value)
        if sanitized_sequence is not None:
            sanitized_context[sanitized_key] = sanitized_sequence
    return sanitized_context


def sanitize_env_var_context(raw_context: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a filtered env-var context dict with only safe keys and values."""
    if raw_context is None:
        return {}

    sanitized_context: dict[str, Any] = {}
    for raw_key, value in raw_context.items():
        normalized_key = fully_unescape_hitl_text(str(raw_key)).strip()
        if (
            not normalized_key
            or normalized_key == "message"
            or normalized_key not in _SAFE_ENV_CONTEXT_KEYS
            or any(keyword in normalized_key.lower() for keyword in _SENSITIVE_CONTEXT_KEYWORDS)
        ):
            continue

        sanitized_key = escape(normalized_key)
        sanitized_scalar = sanitize_env_var_scalar(value)
        if sanitized_scalar is not None:
            sanitized_context[sanitized_key] = sanitized_scalar
            continue
        sanitized_sequence = sanitize_env_var_sequence(value)
        if sanitized_sequence is not None:
            sanitized_context[sanitized_key] = sanitized_sequence
    return sanitized_context


def build_env_var_request_context(
    *,
    raw_context: Mapping[str, Any] | None,
    tool_name: str,
    requested_variables: list[str],
    project_id: str | None,
) -> tuple[dict[str, Any], str]:
    """Sanitize env-var context and overwrite reserved metadata with real request values."""
    request_context = sanitize_env_var_context(raw_context)
    scope_label = "project" if project_id else "tenant"
    sanitized_requested_variables = [
        sanitized_name
        for requested_variable in requested_variables
        if (sanitized_name := sanitize_env_var_text(requested_variable)) is not None
    ]
    request_context["tool_name"] = tool_name
    request_context["requested_variables"] = sanitized_requested_variables
    request_context["save_scope"] = scope_label
    sanitized_project_id = sanitize_env_var_text(project_id)
    if sanitized_project_id:
        request_context["project_id"] = sanitized_project_id
    else:
        request_context.pop("project_id", None)
    return request_context, scope_label


def build_stable_hitl_request_id(
    prefix: str,
    *,
    tenant_id: str | None,
    project_id: str | None,
    conversation_id: str | None,
    message_id: str | None,
    call_id: str | None,
    payload: Mapping[str, Any],
) -> str:
    """Build a deterministic HITL request id from scope plus full payload semantics."""
    seed_payload = {
        "tenant_id": tenant_id or "",
        "project_id": project_id or "",
        "conversation_id": conversation_id or "",
        "message_id": message_id or "",
        "call_id": call_id or "",
        "payload": payload,
    }
    seed = json.dumps(
        seed_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return f"{prefix}_{uuid.uuid5(uuid.NAMESPACE_URL, seed).hex[:16]}"


def scope_hitl_handler[T](
    base_handler: T,
    *,
    tenant_id: str | None,
    project_id: str | None,
    conversation_id: str | None,
    message_id: str | None,
) -> T:
    """Clone a Ray HITL handler into the current execution scope when possible."""
    if base_handler is None:
        return base_handler

    from src.infrastructure.agent.hitl.ray_hitl_handler import RayHITLHandler

    if not isinstance(base_handler, RayHITLHandler):
        return base_handler

    resolved_tenant_id = tenant_id or base_handler.tenant_id
    resolved_project_id = project_id if project_id is not None else base_handler.project_id
    resolved_conversation_id = conversation_id or base_handler.conversation_id
    resolved_message_id = base_handler.message_id if message_id is None else message_id

    return cast(
        T,
        base_handler.with_scope(
            tenant_id=resolved_tenant_id,
            project_id=resolved_project_id,
            conversation_id=resolved_conversation_id,
            message_id=resolved_message_id,
        ),
    )


def _request_metadata_dict(hitl_request: HITLRequestRecord) -> dict[str, Any]:
    """Return a mutable metadata copy for a persisted HITL request."""
    metadata = getattr(hitl_request, "metadata", None)
    if isinstance(metadata, Mapping):
        return dict(metadata)
    return {}


def _choice_request_data(hitl_request: HITLRequestRecord) -> dict[str, Any]:
    """Build shared question/options request data for choice-like HITL requests."""
    options = getattr(hitl_request, "options", None)
    return {
        "question": getattr(hitl_request, "question", ""),
        "options": list(options) if isinstance(options, list) else [],
    }


def build_hitl_request_data_from_record(hitl_request: HITLRequestRecord) -> dict[str, Any]:
    """Rebuild strategy request_data from a persisted HITL request record."""
    from src.domain.model.agent.hitl_request import HITLRequestType

    request_metadata = _request_metadata_dict(hitl_request)
    request_metadata.pop("hitl_type", None)

    request_data: dict[str, Any] = {"_request_id": getattr(hitl_request, "id", "")}
    context = getattr(hitl_request, "context", None)
    request_data["context"] = dict(context) if isinstance(context, Mapping) else {}

    request_type = resolve_trusted_hitl_type(hitl_request)
    if request_type in {
        HITLRequestType.CLARIFICATION.value,
        HITLRequestType.DECISION.value,
    }:
        request_data.update(_choice_request_data(hitl_request))
    elif request_type == HITLRequestType.ENV_VAR.value:
        request_data["message"] = getattr(hitl_request, "question", "")
    elif request_type == "permission":
        request_data["description"] = request_metadata.get("description") or getattr(
            hitl_request, "question", ""
        )
    elif request_type == HITLRequestType.A2UI_ACTION.value:
        request_data["title"] = request_metadata.get("title") or getattr(
            hitl_request, "question", ""
        )

    request_data.update(request_metadata)
    return {key: value for key, value in request_data.items() if value is not None}


def _summarize_env_var_response(response_data: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    """Return a redacted env-var response summary and safe metadata."""
    if response_data.get("cancelled") is True:
        metadata = {
            "cancelled": True,
            "value_count": 0,
            "variable_names": [],
        }
        metadata.update(seal_hitl_response_data("env_var", dict(response_data)))
        return "[cancelled env var response]", metadata

    if response_data.get("timeout") is True:
        metadata = {
            "timeout": True,
            "value_count": 0,
            "variable_names": [],
        }
        metadata.update(seal_hitl_response_data("env_var", dict(response_data)))
        return "[timed out env var response]", metadata

    raw_values = response_data.get("values")
    if not isinstance(raw_values, Mapping):
        raw_values = response_data
    variable_names: list[str] = []
    if isinstance(raw_values, Mapping):
        for raw_name in raw_values.keys():
            if not isinstance(raw_name, str):
                continue
            normalized_name = normalize_env_var_name(raw_name)
            if normalized_name:
                variable_names.append(normalized_name)
    sanitized_names = sorted(set(variable_names))
    metadata = {
        "value_count": len(sanitized_names),
        "variable_names": sanitized_names,
    }
    metadata.update(seal_hitl_response_data("env_var", dict(response_data)))
    return "[redacted env var response]", metadata


def _summarize_choice_like_response(value: object) -> str:
    """Summarize clarification/decision responses with safe text rendering."""
    if isinstance(value, list):
        sanitized_items = sanitize_hitl_sequence(value) or []
        return json.dumps(sanitized_items, ensure_ascii=False)
    return sanitize_hitl_text(value) or ""


def _summarize_permission_response(response_data: Mapping[str, Any]) -> str:
    """Summarize permission responses without exposing arbitrary payloads."""
    action = sanitize_hitl_text(response_data.get("action"))
    if action:
        return action
    granted = response_data.get("granted")
    if isinstance(granted, bool):
        return str(granted).lower()
    return ""


def summarize_hitl_response(
    hitl_type: str,
    response_data: Mapping[str, Any],
) -> tuple[str, dict[str, Any] | None]:
    """Return a safe response summary string and optional response metadata."""
    if hitl_type == "env_var":
        return _summarize_env_var_response(response_data)

    if hitl_type == "clarification":
        return _summarize_choice_like_response(response_data.get("answer")), None

    if hitl_type == "decision":
        return _summarize_choice_like_response(response_data.get("decision")), None

    if hitl_type == "permission":
        return _summarize_permission_response(response_data), None

    if hitl_type == "a2ui_action":
        source_component_id = sanitize_hitl_text(response_data.get("source_component_id")) or ""
        action_context = response_data.get("context")
        metadata = {
            "source_component_id": source_component_id,
            "context": (
                sanitize_hitl_context(action_context) if isinstance(action_context, Mapping) else {}
            ),
        }
        metadata.update(seal_hitl_response_data("a2ui_action", dict(response_data)))
        return sanitize_hitl_text(response_data.get("action_name")) or "", metadata

    return "", None
