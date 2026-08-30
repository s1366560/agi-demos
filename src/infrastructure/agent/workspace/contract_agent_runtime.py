"""Shared helpers for builtin workspace contract-agent runtime turns."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from src.infrastructure.plugins.v2.agent_event_query_services import (
    AGENT_EVENT_QUERY_SERVICE_V2,
    AgentEventQueryResolverProtocolV2,
)
from src.infrastructure.plugins.v2.agent_turn_projection import current_agent_turn_service_v2
from src.infrastructure.plugins.v2.agent_turn_services import AgentTurnStreamProtocolV2
from src.infrastructure.plugins.v2.artifact_content_gc_runtime import (
    ASYNC_SESSION_FACTORY_SERVICE_V2,
)
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    pin_agent_turn_operation_v2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

ContractEventExtractor = Callable[[Mapping[str, Any]], dict[str, Any] | None]
type WorkspaceContractSessionFactoryV2 = Callable[[], AbstractAsyncContextManager["AsyncSession"]]


@runtime_checkable
class WorkspaceContractSessionFactoryProviderProtocolV2(Protocol):
    """Structural contract for the generation-selected persistence session factory."""

    @property
    def factory(self) -> WorkspaceContractSessionFactoryV2: ...


@dataclass(frozen=True, kw_only=True)
class WorkspaceContractAgentTurnAuthorityV2:
    """Exact generation and service retained for one workspace contract turn."""

    operation: OperationContextV2
    service: AgentTurnStreamProtocolV2


async def resolve_workspace_actor_user_id(
    *,
    workspace_id: str,
    actor_user_id: str | None = None,
) -> str | None:
    """Return the real user id that owns a workspace contract-agent conversation."""
    if isinstance(actor_user_id, str) and actor_user_id.strip():
        return actor_user_id.strip()

    from src.infrastructure.workspace_core.legacy_runtime import legacy_workspace_runtime_retired

    return legacy_workspace_runtime_retired("contract agent Workspace owner lookup")


def workspace_contract_conversation_id(
    kind: str,
    *parts: object,
) -> str:
    """Return a deterministic conversation id for idempotent contract-agent turns."""
    normalized_parts = [str(part or "").strip() for part in parts]
    raw = json.dumps(
        {"kind": kind, "parts": normalized_parts},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    readable = ":".join(
        item
        for item in (
            _slug(kind),
            *(_slug(part) for part in normalized_parts[:4]),
        )
        if item
    )
    return f"workspace-contract:{readable}:{digest}"


def workspace_contract_input_fingerprint(*parts: object) -> str:
    """Return a short stable fingerprint for contract-agent input recovery."""
    raw = json.dumps(
        {"parts": parts},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def contract_tool_payload_from_event(
    event: Mapping[str, Any],
    *,
    tool_name: str,
    payload_key: str,
) -> dict[str, Any] | None:
    """Extract a contract-tool payload from live or persisted event shapes."""
    data = event.get("data")
    if not isinstance(data, Mapping):
        return None
    event_tool_name = data.get("tool_name") or data.get("name")
    if event_tool_name != tool_name:
        return None

    event_data = dict(data)
    for key in ("observation", "result", "metadata"):
        payload = _contract_payload_from_value(event_data.get(key), payload_key=payload_key)
        if payload is not None:
            return payload
    return _contract_payload_from_value(event_data, payload_key=payload_key)


def _contract_payload_from_value(
    value: object,
    *,
    payload_key: str,
) -> dict[str, Any] | None:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None
    if not isinstance(value, Mapping):
        return None

    payload = value.get(payload_key)
    if not isinstance(payload, Mapping):
        metadata = value.get("metadata")
        if isinstance(metadata, Mapping):
            payload = metadata.get(payload_key)
    return dict(payload) if isinstance(payload, Mapping) else None


async def recover_workspace_contract_payload(
    *,
    conversation_id: str,
    tenant_id: str,
    project_id: str,
    extract_payload: ContractEventExtractor,
    limit: int = 1000,
) -> dict[str, Any] | None:
    """Recover a submitted contract payload through one leased V2 query authority."""
    try:
        async with pin_agent_turn_operation_v2(
            operation_id=f"workspace-contract-recovery:{uuid.uuid4()}",
            tenant_id=tenant_id,
            project_id=project_id,
            session_id=conversation_id,
            services={
                OPERATION_IDENTITY_SERVICE_V2: {
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                },
                OPERATION_METADATA_SERVICE_V2: {
                    "kind": "workspace-contract-event-recovery",
                    "conversation_id": conversation_id,
                },
            },
            force_process_host_lease=True,
        ) as operation:
            sessions = operation.require(ASYNC_SESSION_FACTORY_SERVICE_V2)
            if not isinstance(sessions, WorkspaceContractSessionFactoryProviderProtocolV2):
                raise RuntimeV2Error(
                    "invalid_workspace_contract_session_factory",
                    "Workspace contract recovery session Provider is invalid",
                )
            resolver = operation.require(AGENT_EVENT_QUERY_SERVICE_V2)
            if not isinstance(resolver, AgentEventQueryResolverProtocolV2):
                raise RuntimeV2Error(
                    "invalid_workspace_contract_event_query",
                    "Workspace contract recovery event query Provider is invalid",
                )
            async with sessions.factory() as db:
                _ = operation.provide(
                    OPERATION_DB_SESSION_SERVICE_V2,
                    db,
                    label="workspace-contract-recovery-db-session",
                )
                events = await resolver.resolve(operation).get_events(
                    conversation_id=conversation_id,
                    from_time_us=0,
                    from_counter=0,
                    limit=limit,
                )
    except RuntimeV2Error:
        raise
    except Exception:
        logger.warning(
            "workspace_contract_runtime.recover_payload_failed",
            extra={"conversation_id": conversation_id},
            exc_info=True,
        )
        return None

    for event in reversed(events):
        event_type = getattr(event.event_type, "value", event.event_type)
        payload = extract_payload({"type": str(event_type), "data": event.event_data})
        if payload is not None:
            return payload
    return None


@asynccontextmanager
async def workspace_contract_agent_turn_authority_v2(
    *,
    db: AsyncSession,
    tenant_id: str,
    project_id: str,
    user_id: str,
    conversation_id: str,
    workspace_id: str,
    agent_id: str,
    contract_kind: str,
) -> AsyncIterator[WorkspaceContractAgentTurnAuthorityV2]:
    """Resolve a workspace contract turn solely from one leased V2 generation."""
    async with pin_agent_turn_operation_v2(
        operation_id=f"workspace-contract-turn:{contract_kind}:{uuid.uuid4()}",
        tenant_id=tenant_id,
        project_id=project_id,
        session_id=conversation_id,
        services={
            OPERATION_DB_SESSION_SERVICE_V2: db,
            OPERATION_IDENTITY_SERVICE_V2: {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "project_id": project_id,
            },
            OPERATION_METADATA_SERVICE_V2: {
                "kind": "workspace-contract-agent-turn",
                "contract_kind": contract_kind,
                "workspace_id": workspace_id,
                "conversation_id": conversation_id,
                "agent_id": agent_id,
            },
        },
        force_process_host_lease=True,
    ) as operation:
        yield WorkspaceContractAgentTurnAuthorityV2(
            operation=operation,
            service=await current_agent_turn_service_v2(),
        )


async def cancel_workspace_contract_chat(conversation_id: str) -> None:
    """Best-effort cancellation for local contract-agent turns that already reached terminal state."""
    try:
        from src.application.services.agent.runtime_bootstrapper import AgentRuntimeBootstrapper

        _ = await AgentRuntimeBootstrapper.cancel_local_chat(conversation_id)
    except Exception:
        logger.debug(
            "workspace_contract_runtime.cancel_chat_failed",
            extra={"conversation_id": conversation_id},
            exc_info=True,
        )
    try:
        from src.infrastructure.agent.actor.state.running_state import clear_agent_running

        await clear_agent_running(conversation_id)
    except Exception:
        logger.debug(
            "workspace_contract_runtime.clear_running_failed",
            extra={"conversation_id": conversation_id},
            exc_info=True,
        )


def _slug(value: str, *, limit: int = 48) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    return normalized.strip("-")[:limit]


__all__ = [
    "WorkspaceContractAgentTurnAuthorityV2",
    "cancel_workspace_contract_chat",
    "contract_tool_payload_from_event",
    "recover_workspace_contract_payload",
    "resolve_workspace_actor_user_id",
    "workspace_contract_agent_turn_authority_v2",
    "workspace_contract_conversation_id",
    "workspace_contract_input_fingerprint",
]
