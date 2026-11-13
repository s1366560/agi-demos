"""Settle a child bootstrap failure from shared spawn and session records.

The child process does not receive an orchestrator or an operation pin. It may
record a failure only when the conversation row, the Redis spawn record, and
the existing request on the agent message bus all name the same parent, child,
and project. Caller-supplied ids are compared with those records and never
become the source of identity.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import select

from src.domain.model.agent.spawn_record import SpawnRecord
from src.domain.ports.services.agent_message_bus_port import (
    AgentMessageBusPort,
    AgentMessageType,
)
from src.infrastructure.adapters.secondary.messaging.redis_agent_message_bus import (
    RedisAgentMessageBusAdapter,
    redis_client_for_agent_bus,
)
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentRunAuthorityModel,
    Conversation,
    ToolExecutionRecord,
)
from src.infrastructure.agent.orchestration.redis_spawn_manager import RedisSpawnManager
from src.infrastructure.plugins.v2.agent_worker_runtime import (
    agent_worker_redis_runtime_factory_v2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

_PRESERVED = frozenset({"stopped", "cancelled", "completed"})
_OPEN_RUNS = frozenset({"queued", "running"})


@dataclass(frozen=True)
class _RegisteredSpawn:
    project_id: str
    tenant_id: str
    parent_session_id: str
    child_agent_id: str
    parent_agent_id: str
    detached: bool


def _terminal_message_id(child_session_id: str, request_message_id: str) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"{child_session_id}:{request_message_id}:bootstrap-failure",
        )
    )


async def mirror_shared_spawn(
    bus: AgentMessageBusPort,
    *,
    parent_agent_id: str,
    child_agent_id: str,
    child_session_id: str,
    project_id: str,
    parent_session_id: str,
    mode_value: str,
    task_summary: str,
) -> None:
    """Copy a new spawn into the shared Redis record when the bus is Redis."""
    client = redis_client_for_agent_bus(bus)
    if client is None:
        return
    from src.domain.model.agent.spawn_mode import SpawnMode

    await RedisSpawnManager(client).register_spawn(
        parent_agent_id=parent_agent_id,
        child_agent_id=child_agent_id,
        child_session_id=child_session_id,
        project_id=project_id,
        mode=SpawnMode(mode_value),
        task_summary=task_summary,
        parent_session_id=parent_session_id,
    )


async def mirror_shared_status(
    bus: AgentMessageBusPort,
    *,
    child_session_id: str,
    status: str,
) -> None:
    """Project a local status change into Redis without replacing a cancellation."""
    client = redis_client_for_agent_bus(bus)
    if client is None:
        return
    manager = RedisSpawnManager(client)
    current = await manager.get_record(child_session_id)
    if current is None:
        return
    if current.status in {"cancelled", "stopped"} and status not in {"cancelled", "stopped"}:
        return
    await manager.update_status(child_session_id, status)


async def read_shared_spawn(bus: AgentMessageBusPort, child_session_id: str) -> SpawnRecord | None:
    """Return the Redis spawn record visible to every process using this bus."""
    client = redis_client_for_agent_bus(bus)
    if client is None:
        return None
    return await RedisSpawnManager(client).get_record(child_session_id)


def prefer_spawn_status(
    local: SpawnRecord | None,
    shared: SpawnRecord | None,
) -> SpawnRecord | None:
    """Let cancellation win, then any shared terminal status over a stale running copy."""
    if local is None:
        return shared
    if shared is None:
        return local
    rank = {"running": 0, "failed": 1, "completed": 2, "stopped": 3, "cancelled": 4}
    if rank.get(shared.status, 0) > rank.get(local.status, 0):
        return shared
    return local


async def settle_durable_child_bootstrap_failure(
    *,
    child_session_id: str,
    child_agent_id: str,
    parent_session_id: str,
    project_id: str,
    tenant_id: str,
    request_message_id: str,
    error_message: str,
) -> None:
    """Record one authenticated failure. This does not start the child."""
    registered = await _load_authorized_relationship(
        child_session_id=child_session_id,
        child_agent_id=child_agent_id,
        parent_session_id=parent_session_id,
        project_id=project_id,
        tenant_id=tenant_id,
    )
    client = await agent_worker_redis_runtime_factory_v2()
    lock_key = f"agent:spawn:{child_session_id}:bootstrap-lock"
    token = str(uuid.uuid4())
    try:
        acquired = bool(await client.set(lock_key, token, ex=30, nx=True))
        if not acquired:
            current = await RedisSpawnManager(client).get_record(child_session_id)
            if current is not None and current.status in _PRESERVED | {"failed"}:
                return
            raise RuntimeV2Error(
                "child_bootstrap_busy",
                "another process is settling this child bootstrap failure",
            )
        await _settle_locked(
            client,
            registered=registered,
            child_session_id=child_session_id,
            child_agent_id=child_agent_id,
            parent_session_id=parent_session_id,
            project_id=project_id,
            request_message_id=request_message_id,
            error_message=error_message,
        )
    finally:
        current_lock = await client.get(lock_key)
        if current_lock == token:
            await client.delete(lock_key)
        await client.aclose()


async def _load_authorized_relationship(
    *,
    child_session_id: str,
    child_agent_id: str,
    parent_session_id: str,
    project_id: str,
    tenant_id: str,
) -> _RegisteredSpawn:
    async with async_session_factory() as session:
        child = await session.get(Conversation, child_session_id)
        if child is None:
            raise RuntimeV2Error(
                "child_bootstrap_record_missing",
                "spawned conversation is not registered",
            )
        if (
            child.project_id != project_id
            or child.tenant_id != tenant_id
            or child.parent_conversation_id != parent_session_id
        ):
            raise RuntimeV2Error(
                "child_bootstrap_scope_rejected",
                "bootstrap failure does not match the registered conversation",
            )
        meta = child.meta if isinstance(child.meta, dict) else {}
        parent_agent_id = meta.get("spawned_by_agent_id")
        if meta.get("spawned_agent_id") != child_agent_id or not isinstance(parent_agent_id, str):
            raise RuntimeV2Error(
                "child_bootstrap_scope_rejected",
                "bootstrap failure does not match the registered child agent",
            )
        parent = await session.get(Conversation, parent_session_id)
        if (
            parent is None
            or parent.status in {"deleted", "archived"}
            or parent.project_id != child.project_id
            or parent.tenant_id != child.tenant_id
        ):
            raise RuntimeV2Error(
                "child_bootstrap_parent_missing",
                "parent conversation is gone for this spawn",
            )
        return _RegisteredSpawn(
            project_id=child.project_id,
            tenant_id=child.tenant_id,
            parent_session_id=parent_session_id,
            child_agent_id=child_agent_id,
            parent_agent_id=parent_agent_id,
            detached=meta.get("detached") is True,
        )


async def _settle_locked(
    client: Redis,
    *,
    registered: _RegisteredSpawn,
    child_session_id: str,
    child_agent_id: str,
    parent_session_id: str,
    project_id: str,
    request_message_id: str,
    error_message: str,
) -> None:
    manager = RedisSpawnManager(client)
    record = await manager.get_record(child_session_id)
    if record is None:
        raise RuntimeV2Error(
            "child_spawn_record_missing",
            "shared spawn record is not registered",
        )
    children = await manager.find_children(parent_session_id)
    owned = any(item.child_session_id == child_session_id for item in children)
    if (
        not owned
        or record.project_id != project_id
        or record.child_agent_id != child_agent_id
        or record.parent_agent_id != registered.parent_agent_id
    ):
        raise RuntimeV2Error(
            "child_bootstrap_scope_rejected",
            "shared spawn record does not match the registered relationship",
        )
    bus = RedisAgentMessageBusAdapter(client)
    history = await bus.get_message_history(session_id=child_session_id, limit=50)
    request_seen = any(
        message.message_type is AgentMessageType.REQUEST
        and message.from_agent_id == registered.parent_agent_id
        and message.session_id == child_session_id
        for message in history
    )
    if not request_seen:
        raise RuntimeV2Error(
            "child_bootstrap_bus_missing",
            "parent request is not on the shared agent bus",
        )
    if record.status in _PRESERVED:
        return
    terminal_id = _terminal_message_id(child_session_id, request_message_id)
    already = any(
        message.metadata is not None
        and message.metadata.get("terminal_message_id") == terminal_id
        and message.content == error_message
        for message in history
    )
    if record.status != "failed":
        updated = await manager.update_status(child_session_id, "failed")
        if updated is None or updated.status != "failed":
            raise RuntimeV2Error(
                "child_spawn_record_missing",
                "shared spawn status was not recorded",
            )
    await _fail_child_run_and_tools(
        child_session_id=child_session_id,
        project_id=project_id,
        error_message=error_message,
    )
    if already:
        return
    await bus.send_message(
        from_agent_id=child_agent_id,
        to_agent_id="",
        session_id=child_session_id,
        content=error_message,
        message_type=AgentMessageType.RESPONSE,
        metadata={
            "source": "child_bootstrap_failure",
            "parent_session_id": parent_session_id,
            "project_id": project_id,
            "success": False,
            "detached": registered.detached,
            "failure_class": "backend",
            "error_message": error_message,
            "source_message_id": request_message_id,
            "terminal_message_id": terminal_id,
        },
    )


async def _fail_child_run_and_tools(
    *,
    child_session_id: str,
    project_id: str,
    error_message: str,
) -> None:
    now = datetime.now(UTC)
    async with async_session_factory() as session:
        runs = (
            await session.scalars(
                select(AgentRunAuthorityModel).where(
                    AgentRunAuthorityModel.conversation_id == child_session_id,
                    AgentRunAuthorityModel.project_id == project_id,
                    AgentRunAuthorityModel.status.in_(tuple(_OPEN_RUNS)),
                )
            )
        ).all()
        for run in runs:
            run.status = "failed"
            run.error = error_message
            run.completed_at = now
            run.updated_at = now
        tools = (
            await session.scalars(
                select(ToolExecutionRecord).where(
                    ToolExecutionRecord.conversation_id == child_session_id,
                    ToolExecutionRecord.status == "running",
                )
            )
        ).all()
        for tool in tools:
            tool.status = "failed"
            tool.error = error_message
            tool.completed_at = now
        await session.commit()
