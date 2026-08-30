"""Shared helpers for builtin workspace contract-agent runtime turns."""

from __future__ import annotations

import hashlib
import json
import logging
import re
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
from src.infrastructure.plugins.v2.workspace_contract_actor_services import (
    WORKSPACE_CONTRACT_ACTOR_RESOLVER_SERVICE_V2,
    WorkspaceContractActorResolverProtocolV2,
)
from src.infrastructure.workspace_core.client import (
    WorkspaceContractActorPurpose,
    WorkspaceContractActorResolveRequest,
    WorkspaceContractActorResolveResponse,
)

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
    actor: WorkspaceContractActorResolveResponse
    service: AgentTurnStreamProtocolV2


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


def workspace_contract_operation_id_v2(
    *,
    purpose: WorkspaceContractActorPurpose,
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    conversation_id: str,
) -> str:
    """Return the stable idempotency key for one audited contract-agent turn."""
    raw = json.dumps(
        {
            "conversation_id": conversation_id,
            "project_id": project_id,
            "purpose": purpose,
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    return f"workspace-contract-turn:{purpose}:{digest}"


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
    operation: OperationContextV2 | None = None,
) -> dict[str, Any] | None:
    """Recover a submitted contract payload through one leased V2 query authority."""
    try:
        if operation is not None:
            events = await _workspace_contract_events_v2(
                operation,
                conversation_id=conversation_id,
                limit=limit,
            )
        else:
            recovery_digest = hashlib.sha256(conversation_id.encode("utf-8")).hexdigest()[:32]
            async with pin_agent_turn_operation_v2(
                operation_id=f"workspace-contract-recovery:{recovery_digest}",
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
            ) as recovery_operation:
                sessions = recovery_operation.require(ASYNC_SESSION_FACTORY_SERVICE_V2)
                if not isinstance(sessions, WorkspaceContractSessionFactoryProviderProtocolV2):
                    raise RuntimeV2Error(
                        "invalid_workspace_contract_session_factory",
                        "Workspace contract recovery session Provider is invalid",
                    )
                async with sessions.factory() as db:
                    _ = recovery_operation.provide(
                        OPERATION_DB_SESSION_SERVICE_V2,
                        db,
                        label="workspace-contract-recovery-db-session",
                    )
                    events = await _workspace_contract_events_v2(
                        recovery_operation,
                        conversation_id=conversation_id,
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


async def _workspace_contract_events_v2(
    operation: OperationContextV2,
    *,
    conversation_id: str,
    limit: int,
) -> list[Any]:
    resolver = operation.require(AGENT_EVENT_QUERY_SERVICE_V2)
    if not isinstance(resolver, AgentEventQueryResolverProtocolV2):
        raise RuntimeV2Error(
            "invalid_workspace_contract_event_query",
            "Workspace contract recovery event query Provider is invalid",
        )
    return await resolver.resolve(operation).get_events(
        conversation_id=conversation_id,
        from_time_us=0,
        from_counter=0,
        limit=limit,
    )


@asynccontextmanager
async def workspace_contract_agent_turn_authority_v2(
    *,
    tenant_id: str,
    project_id: str,
    conversation_id: str,
    workspace_id: str,
    agent_id: str,
    contract_kind: str,
    actor_purpose: WorkspaceContractActorPurpose,
) -> AsyncIterator[WorkspaceContractAgentTurnAuthorityV2]:
    """Resolve actor, persistence, and Agent turn from one leased V2 operation."""
    operation_id = workspace_contract_operation_id_v2(
        purpose=actor_purpose,
        tenant_id=tenant_id,
        project_id=project_id,
        workspace_id=workspace_id,
        conversation_id=conversation_id,
    )
    identity = {
        "tenant_id": tenant_id,
        "project_id": project_id,
    }
    metadata: dict[str, object] = {
        "kind": "workspace-contract-agent-turn",
        "contract_kind": contract_kind,
        "actor_purpose": actor_purpose,
        "workspace_id": workspace_id,
        "conversation_id": conversation_id,
        "agent_id": agent_id,
    }
    async with pin_agent_turn_operation_v2(
        operation_id=operation_id,
        tenant_id=tenant_id,
        project_id=project_id,
        session_id=conversation_id,
        services={
            OPERATION_IDENTITY_SERVICE_V2: identity,
            OPERATION_METADATA_SERVICE_V2: metadata,
        },
        force_process_host_lease=True,
    ) as operation:
        resolver = operation.require(WORKSPACE_CONTRACT_ACTOR_RESOLVER_SERVICE_V2)
        if not isinstance(resolver, WorkspaceContractActorResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_workspace_contract_actor_resolver",
                "Workspace contract turn actor resolver Provider is invalid",
            )
        actor = await resolver.resolve(
            WorkspaceContractActorResolveRequest(
                tenant_id=tenant_id,
                project_id=project_id,
                workspace_id=workspace_id,
                purpose=actor_purpose,
                operation_id=operation_id,
            )
        )
        actor_user_id = actor.actor_user_id.strip()
        if not actor_user_id:
            raise RuntimeV2Error(
                "invalid_workspace_contract_actor",
                "Workspace contract actor authority returned an empty actor identity",
            )
        identity["user_id"] = actor_user_id
        metadata.update(
            {
                "actor_participant_id": actor.participant_actor_id,
                "actor_authority_revision": actor.authority_revision,
                "actor_policy_version": actor.policy_version,
                "actor_resolution_duplicate": actor.duplicate,
            }
        )

        sessions = operation.require(ASYNC_SESSION_FACTORY_SERVICE_V2)
        if not isinstance(sessions, WorkspaceContractSessionFactoryProviderProtocolV2):
            raise RuntimeV2Error(
                "invalid_workspace_contract_session_factory",
                "Workspace contract turn session Provider is invalid",
            )
        async with sessions.factory() as db:
            _ = operation.provide(
                OPERATION_DB_SESSION_SERVICE_V2,
                db,
                label="workspace-contract-turn-db-session",
            )
            yield WorkspaceContractAgentTurnAuthorityV2(
                operation=operation,
                actor=actor,
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
    "workspace_contract_agent_turn_authority_v2",
    "workspace_contract_conversation_id",
    "workspace_contract_input_fingerprint",
    "workspace_contract_operation_id_v2",
]
