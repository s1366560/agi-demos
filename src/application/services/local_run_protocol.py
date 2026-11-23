"""Cloud protocol for a desktop-local run and its uploaded execution record.

The cloud row is the source of truth. This module never starts a cloud agent
and never rewrites a local run into a cloud execution.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.chat_permission_admission_v2 import prepare_chat_permission_snapshot
from src.domain.model.agent.execution.run_execution_placement import ExecutionTarget
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentExecutionEvent,
    AgentLocalRunEventModel,
    AgentRunAuthorityModel,
    Conversation,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.security.secret_text import contains_secret_like_text

type JsonValue = dict[str, "JsonValue"] | list["JsonValue"] | str | int | float | bool | None

LOCAL_ROOT_TOKEN = "<local-root>"
REDACTED_TOKEN = "<redacted>"
MAX_BATCH_EVENTS = 32
MAX_BATCH_BYTES = 256 * 1024
MAX_ARTIFACT_BYTES = 256 * 1024
_EVENT_KINDS = frozenset(
    {
        "user_message",
        "assistant_message",
        "tool_call",
        "tool_result",
        "log",
        "artifact",
        "error",
        "status",
    }
)
_ACTIVE = frozenset({"queued", "running", "cancel_requested"})
_TERMINAL = frozenset({"completed", "failed", "cancelled"})
_HELD_TOKEN = re.compile(r"<local-root>(?:/[^\s\"'`<>]+)*")
_POSIX_PATH = re.compile(r"(?<![A-Za-z0-9])(/[^\s\"'`<>|*?]{2,})")
_WINDOWS_PATH = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]:\\[^\s\"'`<>|*?]{2,})")
_MACHINE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,127}$")
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,199}$")
_LABEL_FORBIDDEN = re.compile(r"[/\\:]")


class LocalRunProtocolError(Exception):
    """A protocol failure the desktop must surface. It is not a cloud fallback."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, kw_only=True)
class LocalRunRegistration:
    """Frozen local run returned to the machine that will execute it."""

    run_id: str
    revision: int
    status: str
    permission_profile: str
    execution_machine_id: str
    local_root_label: str
    upload_state: str


@dataclass(frozen=True, kw_only=True)
class LocalRunEventReceipt:
    """Result of one event batch. ``events_accepted`` is not a synced run."""

    accepted_through_seq: int
    revision: int
    status: str
    idempotent: bool
    upload_state: str


@dataclass(frozen=True, kw_only=True)
class LocalRunTerminalReceipt:
    """Optimistic terminal settlement, including a late arrival after stop."""

    status: str
    revision: int
    late_terminal: bool
    upload_state: str


class LocalArtifactWriter(Protocol):
    """Narrow port over ``ArtifactService.create_artifact``."""

    async def create_artifact(
        self,
        *,
        file_content: bytes,
        filename: str,
        project_id: str,
        tenant_id: str,
        conversation_id: str,
        source_tool: str | None,
        source_path: str | None,
        metadata: dict[str, Any],
    ) -> str: ...


def redact_uploaded_text(value: str) -> str:
    """Remove secret-like text and any absolute path the client still sent."""

    if contains_secret_like_text(value):
        return REDACTED_TOKEN
    return _rewrite_absolute_paths(value)


def redact_uploaded_json(value: JsonValue, *, depth: int = 0) -> JsonValue:
    """Walk a JSON value and redact every string."""

    if depth > 32:
        return REDACTED_TOKEN
    if isinstance(value, str):
        return redact_uploaded_text(value)
    if isinstance(value, bool) or value is None or isinstance(value, int | float):
        return value
    if isinstance(value, list):
        return [redact_uploaded_json(item, depth=depth + 1) for item in value]
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            safe_key = redact_uploaded_text(str(key))
            redacted[safe_key] = redact_uploaded_json(item, depth=depth + 1)
        return redacted


def canonical_payload(value: JsonValue) -> tuple[JsonValue, str]:
    """Return the redacted JSON value and its sha256."""

    redacted = redact_uploaded_json(value)
    encoded = json.dumps(redacted, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return redacted, digest


def validate_root_label(label: str) -> str:
    """Accept only a basename. The absolute directory stays on the computer."""

    text = label.strip()
    if not text or len(text) > 255 or text in {".", ".."} or _LABEL_FORBIDDEN.search(text):
        raise LocalRunProtocolError(
            422,
            "LOCAL_ROOT_LABEL_REJECTED",
            "Local root label must be a single directory name",
        )
    if contains_secret_like_text(text) or text.startswith("<"):
        raise LocalRunProtocolError(
            422,
            "LOCAL_ROOT_LABEL_REJECTED",
            "Local root label failed the sensitive-content check",
        )
    return text


def validate_machine_id(machine_id: str) -> str:
    """Require the desktop machine id that was frozen onto the run."""

    text = machine_id.strip()
    if not _MACHINE_ID.fullmatch(text) or contains_secret_like_text(text):
        raise LocalRunProtocolError(
            422,
            "LOCAL_RUN_MACHINE_REJECTED",
            "Execution machine id is missing or not usable",
        )
    return text


def require_desktop_surface(surface: str | None) -> None:
    """Web can read a local run. It cannot create or append one."""

    if surface != "desktop":
        raise LocalRunProtocolError(
            403,
            "WEB_LOCAL_RUN_READONLY",
            "Web cannot create or update a local run",
        )


async def register_local_run(
    db: AsyncSession,
    *,
    conversation: Conversation,
    user_id: str,
    surface: str | None,
    idempotency_key: str,
    message: str,
    execution_machine_id: str,
    local_root_label: str,
    permission_mode: str | None,
) -> LocalRunRegistration:
    """Create the cloud run and freeze permission, machine, and directory label."""

    require_desktop_surface(surface)
    _require_owner(conversation, user_id)
    key = _idempotency_key(idempotency_key)
    machine_id = validate_machine_id(execution_machine_id)
    label = validate_root_label(local_root_label)
    stored_message = redact_uploaded_text(message)
    if not stored_message.strip():
        raise LocalRunProtocolError(422, "LOCAL_RUN_MESSAGE_REJECTED", "Message is empty")
    try:
        permissions = await prepare_chat_permission_snapshot(conversation, permission_mode)
    except RuntimeV2Error as exc:
        raise LocalRunProtocolError(
            403,
            "LOCAL_RUN_PERMISSION_DENIED",
            "Requested permissions exceed the session or workspace ceiling",
        ) from exc
    existing = await _run_by_idempotency(db, conversation.id, key)
    if existing is not None:
        _assert_same_registration(
            existing,
            message=stored_message,
            machine_id=machine_id,
            label=label,
            permission_mode=permission_mode,
        )
        return _registration(existing)
    active = await db.scalar(
        select(func.count())
        .select_from(AgentRunAuthorityModel)
        .where(
            AgentRunAuthorityModel.conversation_id == conversation.id,
            AgentRunAuthorityModel.status.in_(_ACTIVE),
        )
    )
    if active:
        raise LocalRunProtocolError(
            409,
            "LOCAL_RUN_ACTIVE_CONFLICT",
            "This conversation already has an active run",
        )
    now = datetime.now(UTC)
    run_id = str(uuid.uuid4())
    profile = str(permissions["permission_profile"])
    row = AgentRunAuthorityModel(
        id=run_id,
        tenant_id=conversation.tenant_id,
        project_id=conversation.project_id,
        conversation_id=conversation.id,
        run_kind="chat",
        plan_run_id=None,
        plan_version_id=None,
        idempotency_key=key,
        message_id=run_id,
        request_message=stored_message,
        status="queued",
        revision=1,
        permission_profile=profile,
        execution_target=ExecutionTarget.LOCAL.value,
        execution_machine_id=machine_id,
        execution_environment_id=None,
        local_root_label=label,
        authorization_snapshot={
            "source": "local_run_registration",
            "conversation_id": conversation.id,
            "project_id": conversation.project_id,
            "workspace_id": conversation.workspace_id,
            "permission_profile": profile,
            **permissions,
            "execution_target": ExecutionTarget.LOCAL.value,
            "local_execution": {"stop_requested": False},
        },
        created_at=now,
        updated_at=now,
    )
    _reject_absolute_snapshot(row.authorization_snapshot, row.request_message, label)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _registration(row)


async def append_local_run_events(
    db: AsyncSession,
    *,
    run: AgentRunAuthorityModel,
    conversation: Conversation,
    user_id: str,
    surface: str | None,
    execution_machine_id: str,
    events: Sequence[Mapping[str, Any]],
    raw_size: int,
    artifacts: LocalArtifactWriter | None,
) -> LocalRunEventReceipt:
    """Append a contiguous seq range. Same bytes replay; different bytes conflict."""

    require_desktop_surface(surface)
    _require_owner(conversation, user_id)
    _require_local_machine(run, execution_machine_id)
    if raw_size > MAX_BATCH_BYTES or len(events) > MAX_BATCH_EVENTS:
        raise LocalRunProtocolError(
            413,
            "LOCAL_RUN_BATCH_TOO_LARGE",
            "Local run event batch exceeds the size limit",
        )
    prepared = [_prepare_event(event) for event in events]
    if not prepared:
        raise LocalRunProtocolError(422, "LOCAL_RUN_BATCH_EMPTY", "Event batch is empty")
    seqs = [item[0] for item in prepared]
    if seqs != list(range(seqs[0], seqs[0] + len(seqs))):
        raise LocalRunProtocolError(
            409,
            "LOCAL_RUN_SEQ_GAP",
            "Event seqs must be contiguous and strictly increasing",
        )
    await db.refresh(run)
    # The device sends its buffered WAL before the terminal receipt. A stop fences
    # execution immediately, while its already-produced events can still drain.
    if run.status in _TERMINAL:
        if not await _batch_is_idempotent(db, run.id, prepared):
            raise LocalRunProtocolError(
                409,
                "LOCAL_RUN_CLOSED",
                "The run is closed; new events were not stored",
            )
        last = await _last_seq(db, run.id)
        return LocalRunEventReceipt(
            accepted_through_seq=last,
            revision=run.revision,
            status=run.status,
            idempotent=True,
            upload_state="events_accepted",
        )
    last = await _last_seq(db, run.id)
    if seqs[0] == last + 1:
        await _insert_events(db, run, prepared, artifacts)
        if run.status == "queued":
            run.status = "running"
            run.started_at = datetime.now(UTC)
        run.updated_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(run)
        return LocalRunEventReceipt(
            accepted_through_seq=seqs[-1],
            revision=run.revision,
            status=run.status,
            idempotent=False,
            upload_state="events_accepted",
        )
    if seqs[-1] <= last and await _batch_is_idempotent(db, run.id, prepared):
        return LocalRunEventReceipt(
            accepted_through_seq=last,
            revision=run.revision,
            status=run.status,
            idempotent=True,
            upload_state="events_accepted",
        )
    if await _batch_has_conflict(db, run.id, prepared):
        raise LocalRunProtocolError(
            409,
            "LOCAL_RUN_EVENT_CONFLICT",
            "An event seq was already stored with different content",
        )
    raise LocalRunProtocolError(
        409,
        "LOCAL_RUN_SEQ_GAP",
        "Event seqs must continue from the last accepted seq",
    )


async def settle_local_run(
    db: AsyncSession,
    *,
    run: AgentRunAuthorityModel,
    conversation: Conversation,
    user_id: str,
    surface: str | None,
    expected_revision: int,
    status: str,
    execution_machine_id: str,
    error: str | None,
) -> LocalRunTerminalReceipt:
    """Settle the run. A completion that loses to stop stays cancelled."""

    require_desktop_surface(surface)
    _require_owner(conversation, user_id)
    _require_local_machine(run, execution_machine_id)
    if status not in _TERMINAL:
        raise LocalRunProtocolError(422, "LOCAL_RUN_STATUS_REJECTED", "Terminal status is invalid")
    await db.refresh(run)
    safe_error = redact_uploaded_text(error) if error else None
    if safe_error == REDACTED_TOKEN:
        safe_error = "terminal error redacted"
    receipt = _terminal_receipt(run)
    if (
        run.status == status
        and receipt is not None
        and receipt.get("expected_revision") == expected_revision
        and run.revision == expected_revision + 1
    ):
        return LocalRunTerminalReceipt(
            status=run.status,
            revision=run.revision,
            late_terminal=bool(receipt.get("late_terminal")),
            upload_state="synced",
        )
    if run.status in {"cancel_requested", "cancelled"} and status in {"completed", "failed"}:
        return await _converge_late_terminal(db, run, expected_revision)
    if status == "cancelled" and run.status in {"cancel_requested", "cancelled"}:
        return await _confirm_cancelled(db, run)
    if run.status not in _ACTIVE or run.revision != expected_revision:
        raise LocalRunProtocolError(
            409,
            "LOCAL_RUN_REVISION_CONFLICT",
            "Run revision changed; the terminal update was not applied",
        )
    now = datetime.now(UTC)
    snapshot = dict(run.authorization_snapshot)
    snapshot["terminal_receipt"] = {
        "expected_revision": expected_revision,
        "status": status,
        "late_terminal": False,
    }
    run.authorization_snapshot = snapshot
    run.status = status
    run.error = safe_error
    run.completed_at = now
    run.updated_at = now
    run.revision = expected_revision + 1
    await db.commit()
    await db.refresh(run)
    return LocalRunTerminalReceipt(
        status=run.status,
        revision=run.revision,
        late_terminal=False,
        upload_state="synced",
    )


async def stop_local_run(
    db: AsyncSession,
    *,
    run: AgentRunAuthorityModel,
    conversation: Conversation,
    user_id: str,
    surface: str | None,
    expected_revision: int,
    execution_machine_id: str,
) -> LocalRunTerminalReceipt:
    """Record stop. A later completion cannot replace the cancellation."""

    require_desktop_surface(surface)
    _require_owner(conversation, user_id)
    _require_local_machine(run, execution_machine_id)
    await db.refresh(run)
    receipt = dict(run.authorization_snapshot).get("local_execution")
    same_stop = (
        isinstance(receipt, dict)
        and receipt.get("stop_requested") is True
        and receipt.get("expected_revision") == expected_revision
    )
    if run.status == "cancelled" and same_stop and run.revision >= expected_revision + 1:
        return LocalRunTerminalReceipt(
            status="cancelled",
            revision=run.revision,
            late_terminal=False,
            upload_state="synced",
        )
    if run.status == "cancel_requested" and same_stop:
        return LocalRunTerminalReceipt(
            status="cancel_requested",
            revision=run.revision,
            late_terminal=False,
            upload_state="events_accepted",
        )
    if run.status in _TERMINAL or run.revision != expected_revision:
        raise LocalRunProtocolError(
            409,
            "LOCAL_RUN_REVISION_CONFLICT",
            "Run revision changed; stop was not applied",
        )
    snapshot = dict(run.authorization_snapshot)
    snapshot["local_execution"] = {
        "stop_requested": True,
        "expected_revision": expected_revision,
    }
    run.authorization_snapshot = snapshot
    run.status = "cancel_requested"
    run.revision = expected_revision + 1
    run.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(run)
    return LocalRunTerminalReceipt(
        status="cancel_requested",
        revision=run.revision,
        late_terminal=False,
        upload_state="events_accepted",
    )


async def list_local_run_events(
    db: AsyncSession,
    *,
    run: AgentRunAuthorityModel,
    conversation: Conversation,
    user_id: str,
) -> list[dict[str, Any]]:
    """Replay the redacted seq log. Reading does not require the desktop surface."""

    _require_owner(conversation, user_id)
    if run.execution_target != ExecutionTarget.LOCAL.value:
        raise LocalRunProtocolError(404, "LOCAL_RUN_NOT_FOUND", "Local run not found")
    rows = (
        await db.scalars(
            select(AgentLocalRunEventModel)
            .where(AgentLocalRunEventModel.run_id == run.id)
            .order_by(AgentLocalRunEventModel.seq.asc())
        )
    ).all()
    return [
        {
            "seq": row.seq,
            "kind": row.kind,
            "payload": row.payload,
            "artifact_id": row.artifact_id,
            "execution_target": "local",
            "local_root_label": run.local_root_label,
        }
        for row in rows
    ]


def _rewrite_absolute_paths(value: str) -> str:
    held: list[str] = []

    def _hold(match: re.Match[str]) -> str:
        held.append(match.group(0))
        return f"\u0000{len(held) - 1}\u0000"

    parked = _HELD_TOKEN.sub(_hold, value)
    parked = _POSIX_PATH.sub(lambda match: _basename_token(match.group(1)), parked)
    parked = _WINDOWS_PATH.sub(lambda match: _basename_token(match.group(1)), parked)
    for index, token in enumerate(held):
        parked = parked.replace(f"\u0000{index}\u0000", token)
    return parked


def _basename_token(path: str) -> str:
    normalized = path.replace("\\", "/").rstrip("/")
    base = normalized.rsplit("/", 1)[-1]
    if not base or base in {".", ".."}:
        return f"{LOCAL_ROOT_TOKEN}/redacted-path"
    return f"{LOCAL_ROOT_TOKEN}/{base}"


def _idempotency_key(value: str) -> str:
    text = value.strip()
    if not _IDEMPOTENCY_KEY.fullmatch(text) or contains_secret_like_text(text):
        raise LocalRunProtocolError(
            422,
            "LOCAL_RUN_IDEMPOTENCY_REJECTED",
            "Idempotency key is missing or not usable",
        )
    return text


def _require_owner(conversation: Conversation, user_id: str) -> None:
    if conversation.user_id != user_id:
        raise LocalRunProtocolError(403, "LOCAL_RUN_FORBIDDEN", "Agent run access denied")


def _require_local_machine(run: AgentRunAuthorityModel, machine_id: str) -> None:
    if run.execution_target != ExecutionTarget.LOCAL.value:
        raise LocalRunProtocolError(404, "LOCAL_RUN_NOT_FOUND", "Local run not found")
    if validate_machine_id(machine_id) != run.execution_machine_id:
        raise LocalRunProtocolError(
            403,
            "LOCAL_RUN_MACHINE_MISMATCH",
            "Execution machine does not match the frozen run",
        )


def _registration(run: AgentRunAuthorityModel) -> LocalRunRegistration:
    upload_state = "synced" if run.status in _TERMINAL else "pending"
    return LocalRunRegistration(
        run_id=run.id,
        revision=run.revision,
        status=run.status,
        permission_profile=run.permission_profile,
        execution_machine_id=str(run.execution_machine_id),
        local_root_label=str(run.local_root_label),
        upload_state=upload_state,
    )


def _assert_same_registration(
    run: AgentRunAuthorityModel,
    *,
    message: str,
    machine_id: str,
    label: str,
    permission_mode: str | None,
) -> None:
    snapshot = run.authorization_snapshot
    same = (
        run.execution_target == ExecutionTarget.LOCAL.value
        and run.request_message == message
        and run.execution_machine_id == machine_id
        and run.local_root_label == label
        and snapshot.get("requested_permission_mode") == permission_mode
    )
    if not same:
        raise LocalRunProtocolError(
            409,
            "LOCAL_RUN_IDEMPOTENCY_CONFLICT",
            "Idempotency key is already bound to a different local run",
        )


def _reject_absolute_snapshot(snapshot: dict[str, Any], message: str, label: str) -> None:
    blob = json.dumps({"snapshot": snapshot, "message": message, "label": label}, default=str)
    parked = _HELD_TOKEN.sub(" ", blob)
    if _POSIX_PATH.search(parked) or _WINDOWS_PATH.search(parked):
        raise LocalRunProtocolError(
            422,
            "LOCAL_ROOT_LABEL_REJECTED",
            "An absolute path was still present after redaction",
        )


async def _run_by_idempotency(
    db: AsyncSession,
    conversation_id: str,
    key: str,
) -> AgentRunAuthorityModel | None:
    found: AgentRunAuthorityModel | None = await db.scalar(
        select(AgentRunAuthorityModel).where(
            AgentRunAuthorityModel.conversation_id == conversation_id,
            AgentRunAuthorityModel.idempotency_key == key,
        )
    )
    return found


def _prepare_event(event: Mapping[str, Any]) -> tuple[int, str, Any, str]:
    seq = event.get("seq")
    kind = event.get("kind")
    payload = event.get("payload")
    if isinstance(seq, bool) or not isinstance(seq, int) or seq < 1:
        raise LocalRunProtocolError(422, "LOCAL_RUN_EVENT_REJECTED", "Event seq is invalid")
    if not isinstance(kind, str) or kind not in _EVENT_KINDS:
        raise LocalRunProtocolError(422, "LOCAL_RUN_EVENT_REJECTED", "Event kind is invalid")
    if not isinstance(payload, dict):
        raise LocalRunProtocolError(422, "LOCAL_RUN_EVENT_REJECTED", "Event payload is invalid")
    redacted, digest = canonical_payload(payload)
    if kind == "artifact" and isinstance(redacted, dict):
        redacted = _sanitize_artifact_payload(redacted)
        encoded = json.dumps(redacted, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return seq, kind, redacted, digest


def _sanitize_artifact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(payload)
    encoded = cleaned.get("content_base64")
    if not isinstance(encoded, str):
        cleaned.pop("content_base64", None)
        return cleaned
    try:
        content = base64.b64decode(encoded, validate=True)
    except ValueError:
        cleaned.pop("content_base64", None)
        cleaned["artifact_rejected"] = "invalid_content"
        return cleaned
    if len(content) > MAX_ARTIFACT_BYTES:
        cleaned.pop("content_base64", None)
        cleaned["artifact_rejected"] = "too_large"
        return cleaned
    text = content.decode("utf-8", errors="replace")
    if contains_secret_like_text(text):
        cleaned.pop("content_base64", None)
        cleaned["artifact_rejected"] = "secret_like"
        return cleaned
    return cleaned


async def _last_seq(db: AsyncSession, run_id: str) -> int:
    value = await db.scalar(
        select(func.max(AgentLocalRunEventModel.seq)).where(
            AgentLocalRunEventModel.run_id == run_id
        )
    )
    return int(value or 0)


async def _batch_is_idempotent(
    db: AsyncSession,
    run_id: str,
    prepared: Sequence[tuple[int, str, Any, str]],
) -> bool:
    for seq, _kind, _payload, digest in prepared:
        row = await _event_row(db, run_id, seq)
        if row is None or row.payload_sha256 != digest:
            return False
    return True


async def _batch_has_conflict(
    db: AsyncSession,
    run_id: str,
    prepared: Sequence[tuple[int, str, Any, str]],
) -> bool:
    for seq, _kind, _payload, digest in prepared:
        row = await _event_row(db, run_id, seq)
        if row is not None and row.payload_sha256 != digest:
            return True
    return False


async def _event_row(db: AsyncSession, run_id: str, seq: int) -> AgentLocalRunEventModel | None:
    found: AgentLocalRunEventModel | None = await db.scalar(
        select(AgentLocalRunEventModel).where(
            AgentLocalRunEventModel.run_id == run_id,
            AgentLocalRunEventModel.seq == seq,
        )
    )
    return found


async def _insert_events(
    db: AsyncSession,
    run: AgentRunAuthorityModel,
    prepared: Sequence[tuple[int, str, Any, str]],
    artifacts: LocalArtifactWriter | None,
) -> None:
    created_at = run.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    event_time_us = int(created_at.timestamp() * 1_000_000)
    for seq, kind, payload, digest in prepared:
        artifact_id = None
        stored = payload
        if kind == "artifact" and isinstance(payload, dict):
            artifact_id, stored = await _store_artifact(run, payload, artifacts)
        row = AgentLocalRunEventModel(
            id=str(uuid.uuid4()),
            run_id=run.id,
            tenant_id=run.tenant_id,
            project_id=run.project_id,
            conversation_id=run.conversation_id,
            seq=seq,
            kind=kind,
            payload=stored,
            payload_sha256=digest,
            artifact_id=artifact_id,
        )
        db.add(row)
        db.add(
            AgentExecutionEvent(
                id=str(uuid.uuid4()),
                conversation_id=run.conversation_id,
                message_id=run.id,
                event_type=kind,
                event_data={
                    "seq": seq,
                    "payload": stored,
                    "run_id": run.id,
                    "execution_target": "local",
                    "local_root_label": run.local_root_label,
                    "artifact_id": artifact_id,
                },
                event_time_us=event_time_us,
                event_counter=seq,
                correlation_id=run.id,
            )
        )


async def _store_artifact(
    run: AgentRunAuthorityModel,
    payload: dict[str, Any],
    artifacts: LocalArtifactWriter | None,
) -> tuple[str | None, dict[str, Any]]:
    if payload.get("artifact_rejected"):
        return None, payload
    encoded = payload.get("content_base64")
    filename = payload.get("filename")
    if not isinstance(encoded, str) or not isinstance(filename, str):
        rejected = dict(payload)
        rejected["artifact_rejected"] = "invalid_content"
        rejected.pop("content_base64", None)
        return None, rejected
    if artifacts is None:
        raise LocalRunProtocolError(
            503,
            "LOCAL_RUN_ARTIFACT_STORE_UNAVAILABLE",
            "Artifact storage is unavailable; the event was not stored",
        )
    content = base64.b64decode(encoded)
    source_path = payload.get("source_path")
    artifact_id = await artifacts.create_artifact(
        file_content=content,
        filename=filename,
        project_id=run.project_id,
        tenant_id=run.tenant_id,
        conversation_id=run.conversation_id,
        source_tool=payload.get("source_tool")
        if isinstance(payload.get("source_tool"), str)
        else None,
        source_path=source_path if isinstance(source_path, str) else None,
        metadata={"execution_target": "local", "origin": "local_run_upload"},
    )
    return artifact_id, payload


def _terminal_receipt(run: AgentRunAuthorityModel) -> dict[str, Any] | None:
    receipt = run.authorization_snapshot.get("terminal_receipt")
    if isinstance(receipt, dict):
        return receipt
    return None


async def _confirm_cancelled(
    db: AsyncSession,
    run: AgentRunAuthorityModel,
) -> LocalRunTerminalReceipt:
    """The executor observed stop and confirms cancellation without a second run."""

    if run.status == "cancelled":
        receipt = _terminal_receipt(run) or {}
        return LocalRunTerminalReceipt(
            status="cancelled",
            revision=run.revision,
            late_terminal=bool(receipt.get("late_terminal")),
            upload_state="synced",
        )

    now = datetime.now(UTC)
    snapshot = dict(run.authorization_snapshot)
    snapshot["terminal_receipt"] = {
        "expected_revision": run.revision,
        "status": "cancelled",
        "late_terminal": False,
    }
    run.authorization_snapshot = snapshot
    run.status = "cancelled"
    run.completed_at = run.completed_at or now
    run.updated_at = now
    await db.commit()
    await db.refresh(run)
    return LocalRunTerminalReceipt(
        status="cancelled",
        revision=run.revision,
        late_terminal=False,
        upload_state="synced",
    )


async def _converge_late_terminal(
    db: AsyncSession,
    run: AgentRunAuthorityModel,
    expected_revision: int,
) -> LocalRunTerminalReceipt:
    """Stop wins. The late completion is acknowledged and not applied."""

    now = datetime.now(UTC)
    snapshot = dict(run.authorization_snapshot)
    snapshot["terminal_receipt"] = {
        "expected_revision": expected_revision,
        "status": "cancelled",
        "late_terminal": True,
    }
    run.authorization_snapshot = snapshot
    run.status = "cancelled"
    run.error = None
    run.completed_at = run.completed_at or now
    run.updated_at = now
    if run.revision == expected_revision:
        run.revision = expected_revision + 1
    await db.commit()
    await db.refresh(run)
    return LocalRunTerminalReceipt(
        status="cancelled",
        revision=run.revision,
        late_terminal=True,
        upload_state="synced",
    )
