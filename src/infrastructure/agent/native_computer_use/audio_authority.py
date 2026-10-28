"""Current run and authenticated device provenance for automatic audio inputs."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any, cast

from src.application.services.approved_run_tool_permission_v2 import (
    ApprovedRunToolPermissionV2,
    _identity,
    _read_run,
    current_approved_run_guard_v2,
)
from src.application.services.chat_run_tool_permission_v2 import current_chat_run_guard_v2
from src.infrastructure.agent.native_computer_use.store import (
    identifier,
    request_key,
    run_key,
    string,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

if TYPE_CHECKING:
    from src.domain.llm_providers.models import ProviderConfig
    from src.domain.model.artifact.artifact import Artifact
    from src.infrastructure.agent.native_computer_use.broker import NativeComputerBroker
    from src.infrastructure.agent.tools.result import ToolAttachment

_ORIGIN_FIELDS = (
    "request_id",
    "user_id",
    "tenant_id",
    "project_id",
    "conversation_id",
    "run_id",
    "child_run_id",
    "session_id",
    "device_id",
    "connection_id",
    "authorization_revision",
    "permission_profile",
    "plan_version_id",
    "agent_id",
    "child_owner_digest",
)


def _denied() -> RuntimeV2Error:
    return RuntimeV2Error(
        "computer_use_audio_scope_denied", "Native audio authority is unavailable"
    )


async def require_audio_authority(
    scope: dict[str, Any],
    origin: dict[str, Any],
) -> tuple[NativeComputerBroker, dict[str, Any]]:
    """Re-read canonical membership, run, device and native pause/stop state."""
    from src.infrastructure.agent.tools.native_computer_use import (
        current_native_computer_broker,
        native_session_id,
    )

    guard = current_approved_run_guard_v2() or current_chat_run_guard_v2()
    identity = tuple(
        scope.get(key)
        for key in (
            "tenant_id",
            "project_id",
            "conversation_id",
            "user_id",
        )
    )
    if (
        guard is None
        or guard.identity != identity
        or _identity(guard.operation) != identity
        or not isinstance(scope.get("session_id"), str)
        or not scope["session_id"]
    ):
        raise _denied()
    if isinstance(guard, ApprovedRunToolPermissionV2):
        await guard.require("conversation_progress")
    else:
        await guard.revalidate_current_authority("conversation_progress")
    row = await _read_run(guard.sessions, guard.run_id, guard.identity, guard.child_run_id)
    if guard.child_run_id is None and row.status != "running":
        raise _denied()
    child_owner_digest = None
    if guard.child_run_id is not None:
        from src.infrastructure.agent.subagent.owner_lease_v2 import current_owner_v2

        owner = current_owner_v2.get()
        if owner is None:
            raise _denied()
        child_owner_digest = hashlib.sha256(owner.token.encode("utf-8")).hexdigest()
    broker = current_native_computer_broker()
    if broker is None:
        raise _denied()
    request_id = identifier(origin.get("request_id"))
    request = await broker.read(request_key(request_id))
    expected = {
        **{
            key: scope.get(key) for key in ("user_id", "tenant_id", "project_id", "conversation_id")
        },
        "run_id": guard.run_id,
        "child_run_id": guard.child_run_id,
        "child_owner_digest": child_owner_digest,
        "session_id": native_session_id(scope["session_id"], guard.child_run_id or guard.run_id),
        "authorization_revision": row.revision,
        "permission_profile": row.permission_profile,
        "plan_version_id": row.plan_version_id,
    }
    if (
        request is None
        or request.get("status") != "completed"
        or request.get("cancelled")
        or request.get("is_error") is not False
        or any(request.get(key) != value for key, value in expected.items())
        or any(request.get(key) != value for key, value in origin.items() if key in _ORIGIN_FIELDS)
    ):
        raise _denied()
    await broker.require_live_control_device(request)
    from src.infrastructure.adapters.primary.web.routers.agent.computer_use_steps import (
        current_agent_servers,
    )

    async with guard.sessions() as db:
        current_servers = await current_agent_servers(db, request, request["tool_name"])
        if current_servers != tuple(request.get("allowed_mcp_servers", ())):
            raise _denied()
    # Any outstanding native pause/stop in this exact engine session fences media.
    for member in await broker.members(
        run_key(
            scope["user_id"],
            scope["tenant_id"],
            scope["project_id"],
            guard.run_id,
        )
    ):
        state = await broker.read(request_key(string(member)))
        if state is None or state.get("session_id") != request["session_id"]:
            continue
        outcome = state.get("control_outcome")
        resumed = state.get("control_notification") == {
            "generation": state.get("control_generation"),
            "state": "resumed",
        }
        if (
            state.get("cancelled")
            or outcome == "user_stopped"
            or (outcome == "user_paused" and not resumed)
        ):
            raise _denied()
    return broker, request


async def capture_audio_origin(
    attachment: ToolAttachment,
    scope: dict[str, Any],
) -> dict[str, Any] | None:
    """Bind stored audio to bytes actually received over the owned device transport."""
    if attachment.native_request_id is None:
        return None
    broker, request = await require_audio_authority(
        scope,
        {"request_id": attachment.native_request_id},
    )
    raw_descriptor = request.get("media", {}).get(attachment.name)
    if not isinstance(raw_descriptor, dict):
        raise _denied()
    descriptor = cast(dict[str, Any], raw_descriptor)
    if (
        descriptor.get("eof") is not True
        or descriptor.get("mime_type") != attachment.mime_type
        or descriptor.get("size_bytes") != len(attachment.content)
        or not isinstance(attachment.content, bytes)
    ):
        raise _denied()
    parts = await broker.redis.mget(descriptor["parts"])
    if any(part is None for part in parts):
        raise _denied()
    received = b"".join(bytes.fromhex(string(part)) for part in parts)
    if received != attachment.content:
        raise _denied()
    origin = {key: request.get(key) for key in _ORIGIN_FIELDS}
    origin.update(
        native_attachment_id=attachment.name,
        sha256=hashlib.sha256(received).hexdigest(),
    )
    _ = await require_audio_authority(scope, origin)
    return origin


async def bind_audio_artifact(
    artifact: Artifact,
    scope: dict[str, Any],
    origin: dict[str, Any],
) -> None:
    """Store the exact resulting artifact ID in the private host request receipt."""
    broker, request = await require_audio_authority(scope, origin)
    binding = {
        "native_attachment_id": origin["native_attachment_id"],
        "sha256": origin["sha256"],
        "mime_type": artifact.mime_type,
        "size_bytes": artifact.size_bytes,
    }

    def change(current: dict[str, Any] | None) -> dict[str, Any]:
        if current is None or current.get("status") != "completed" or current.get("cancelled"):
            raise _denied()
        if any(current.get(key) != request.get(key) for key in _ORIGIN_FIELDS):
            raise _denied()
        bindings = dict(current.get("audio_artifacts", {}))
        if artifact.id in bindings and bindings[artifact.id] != binding:
            raise _denied()
        bindings[artifact.id] = binding
        return {**current, "audio_artifacts": bindings}

    _ = await broker.update(request_key(request["request_id"]), change)


async def require_current_audio_provider(provider: ProviderConfig) -> None:
    """A cached client cannot retain audio permission after a Provider edit/deletion."""
    from src.domain.llm_providers.models import provider_revision
    from src.infrastructure.persistence.llm_providers_models import LLMProvider

    guard = current_approved_run_guard_v2() or current_chat_run_guard_v2()
    if guard is None:
        raise _denied()
    async with guard.sessions() as db:
        current = await db.get(LLMProvider, provider.id)
        if (
            current is None
            or not current.is_active
            or not current.is_enabled
            or provider_revision(current.updated_at) != provider_revision(provider.updated_at)
            or current.provider_type != provider.provider_type.value
            or current.base_url != provider.base_url
            or current.config.get("audio_input_models", [])
            != provider.config.get("audio_input_models", [])
        ):
            raise _denied()
