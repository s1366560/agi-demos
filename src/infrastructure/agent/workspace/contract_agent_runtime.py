"""Shared helpers for builtin workspace contract-agent runtime turns."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.application.services.agent_service import AgentService
    from src.domain.llm_providers.llm_types import LLMClient

ContractEventExtractor = Callable[[Mapping[str, Any]], dict[str, Any] | None]


async def resolve_workspace_actor_user_id(
    *,
    workspace_id: str,
    actor_user_id: str | None = None,
) -> str | None:
    """Return the real user id that owns a workspace contract-agent conversation."""
    if isinstance(actor_user_id, str) and actor_user_id.strip():
        return actor_user_id.strip()

    from src.infrastructure.adapters.secondary.persistence.database import (
        async_session_factory,
    )
    from src.infrastructure.adapters.secondary.persistence.sql_workspace_repository import (
        SqlWorkspaceRepository,
    )

    async with async_session_factory() as session:
        workspace = await SqlWorkspaceRepository(session).find_by_id(workspace_id)
        if workspace is None:
            return None
        created_by = getattr(workspace, "created_by", None)
        return created_by.strip() if isinstance(created_by, str) and created_by.strip() else None


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
    extract_payload: ContractEventExtractor,
    limit: int = 1000,
) -> dict[str, Any] | None:
    """Recover a submitted contract payload from persisted agent execution events."""
    try:
        from src.infrastructure.adapters.secondary.persistence.database import (
            async_session_factory,
        )
        from src.infrastructure.adapters.secondary.persistence.sql_agent_execution_event_repository import (
            SqlAgentExecutionEventRepository,
        )

        async with async_session_factory() as db:
            events = await SqlAgentExecutionEventRepository(db).list_by_conversation(
                conversation_id=conversation_id,
                limit=limit,
            )
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


async def create_workspace_contract_agent_service(
    *,
    db: AsyncSession,
    llm: LLMClient,
) -> AgentService:
    """Create an AgentService while preserving app-level infra wiring."""
    from src.infrastructure.adapters.primary.web.startup.container import (
        get_app_container,
    )

    app_container = get_app_container()
    if app_container is not None:
        return app_container.with_db(db).agent_service(llm)

    from src.configuration.di_container import DIContainer
    from src.infrastructure.agent.state.agent_worker_state import get_redis_client

    redis_client = await get_redis_client()
    return DIContainer(db=db, redis_client=redis_client).agent_service(llm)


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
    "cancel_workspace_contract_chat",
    "contract_tool_payload_from_event",
    "create_workspace_contract_agent_service",
    "recover_workspace_contract_payload",
    "resolve_workspace_actor_user_id",
    "workspace_contract_conversation_id",
    "workspace_contract_input_fingerprint",
]
