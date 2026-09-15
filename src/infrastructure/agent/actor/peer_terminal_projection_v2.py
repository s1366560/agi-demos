"""Publish scoped peer terminal observations independently of parent model polling."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable
from datetime import UTC
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import select

from src.infrastructure.adapters.secondary.persistence.models import (
    AgentRunAuthorityModel,
    Conversation,
    User,
    UserProject,
    UserTenant,
)
from src.infrastructure.plugins.v2.boundary import OPERATION_IDENTITY_SERVICE_V2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from src.domain.model.agent.spawn_record import SpawnRecord
    from src.infrastructure.plugins.v2.runtime import OperationContextV2
    from src.infrastructure.plugins.v2.session_event_log import SessionEventLogServiceV2

# One delivery identity per canonical child turn, not per reusable child session.
# SQL retains the authoritative event; repeated delivery preserves its exact cursor.
_PUBLISH_ONCE = """
if redis.call('EXISTS', KEYS[1]) == 1 then return 0 end
redis.call('XADD', KEYS[2], 'MAXLEN', '~', 1000, '*', 'data', ARGV[1])
if KEYS[3] then redis.call('XADD', KEYS[3], 'MAXLEN', '~', 1000, '*', 'data', ARGV[2]) end
redis.call('SET', KEYS[1], '1')
return 1
"""


def _denied() -> RuntimeV2Error:
    return RuntimeV2Error("peer_terminal_scope_denied", "Peer terminal observation scope mismatch")


async def project_peer_terminal_v2(
    *,
    run_id: str,
    operation: OperationContextV2,
    spawn: SpawnRecord,
    event_log: SessionEventLogServiceV2,
    redis_client: Redis,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Project only an owned canonical terminal through its actual spawn relationship."""
    scope = operation.context.scope
    raw_identity = operation.require(OPERATION_IDENTITY_SERVICE_V2)
    if not isinstance(raw_identity, dict):
        raise _denied()
    identity = cast(dict[str, Any], raw_identity)
    tenant, project, child_id = scope.tenant_id, scope.project_id, scope.session_id
    user = identity.get("user_id")
    if not user or identity.get("tenant_id") != tenant or identity.get("project_id") != project:
        raise _denied()
    async with sessions() as db:
        found = (
            await db.execute(
                select(AgentRunAuthorityModel, Conversation)
                .join(Conversation, Conversation.id == AgentRunAuthorityModel.conversation_id)
                .join(User, User.id == Conversation.user_id)
                .join(
                    UserProject, (UserProject.user_id == user) & (UserProject.project_id == project)
                )
                .join(UserTenant, (UserTenant.user_id == user) & (UserTenant.tenant_id == tenant))
                .where(
                    AgentRunAuthorityModel.id == run_id,
                    AgentRunAuthorityModel.tenant_id == tenant,
                    AgentRunAuthorityModel.project_id == project,
                    AgentRunAuthorityModel.conversation_id == child_id,
                    Conversation.tenant_id == tenant,
                    Conversation.project_id == project,
                    Conversation.user_id == user,
                    User.is_active.is_(True),
                )
            )
        ).first()
        if found is None:
            raise _denied()
        run, child = found
        if not child.parent_conversation_id:
            return
        parent = await db.get(Conversation, child.parent_conversation_id)
        child_metadata = cast(dict[str, Any], child.meta or {})
        if (
            parent is None
            or parent.tenant_id != tenant
            or parent.project_id != project
            or parent.user_id != user
            or parent.id == child.id
            or spawn.child_session_id != child.id
            or spawn.project_id != project
            or child_metadata.get("spawned_agent_id") != spawn.child_agent_id
            or child_metadata.get("spawned_by_agent_id") != spawn.parent_agent_id
            or not spawn.id
            or not spawn.child_agent_id
        ):
            raise _denied()
        if run.status not in {"completed", "failed", "cancelled"} or run.completed_at is None:
            return
        completed_at = run.completed_at
        if completed_at.tzinfo is None:
            completed_at = completed_at.replace(tzinfo=UTC)
        timestamp_us = int(completed_at.timestamp() * 1_000_000)
        counter = int.from_bytes(hashlib.sha256(run.id.encode()).digest()[:4], "big") & 0x7FFFFFFF
        data: dict[str, Any] = {
            "agent_id": spawn.child_agent_id,
            "agent_name": spawn.child_agent_id,
            "parent_agent_id": spawn.parent_agent_id,
            "session_id": child.id,
            "child_session_id": child.id,
            "parent_session_id": parent.id,
            "spawn_id": spawn.id,
            "child_run_id": run.id,
            "status": run.status,
            "success": run.status == "completed",
            "result": "",
            "artifacts": [],
            "source": "canonical_peer_terminal",
            "lifecycle_event_id": f"peer-terminal:{run.id}",
        }
        event: dict[str, Any] = {
            "type": "agent_stopped" if run.status == "cancelled" else "agent_completed",
            "data": data,
            "event_time_us": timestamp_us,
            "event_counter": counter,
            "timestamp": completed_at.isoformat(),
        }
        parent_id, message_id = parent.id, f"peer-terminal:{run.id}"
    await event_log.append(conversation_id=parent_id, message_id=message_id, events=[event])
    frame = {
        **event,
        "conversation_id": parent_id,
        "message_id": message_id,
        "data": {**data, "message_id": message_id},
    }
    from src.domain.events.envelope import EventEnvelope
    from src.infrastructure.plugins.v2.agent_worker_lifecycle_transport_v2 import (
        lifecycle_routing_key_v2,
    )

    lifecycle_message = {
        "type": "agent_lifecycle",
        "tenant_id": tenant,
        "project_id": project,
        "conversation_id": parent_id,
        "data": event,
    }
    envelope = EventEnvelope(
        event_id=f"peer-terminal:{run_id}",
        event_type="agent_lifecycle",
        payload=lifecycle_message,
        metadata={"tenant_id": tenant, "project_id": project},
    )
    _ = await cast(
        Awaitable[object],
        redis_client.eval(
            _PUBLISH_ONCE,
            3,
            f"agent:peer:terminal-delivered:{run_id}",
            f"agent:events:{parent_id}",
            "events:" + lifecycle_routing_key_v2(str(tenant), str(project)),
            json.dumps(frame),
            envelope.to_json(),
        ),
    )


async def publish_settled_peer_terminal_v2(run_id: str) -> None:
    """Resolve production authorities after settlement; ordinary conversations are unchanged."""
    from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
    from src.infrastructure.agent.actor.execution import (
        _get_redis_client,
        _session_event_log_service_v2,
    )
    from src.infrastructure.plugins.v2.agent_worker_runtime import current_agent_orchestrator_v2
    from src.infrastructure.plugins.v2.boundary import current_operation_context_v2

    async with async_session_factory() as db:
        run = await db.get(AgentRunAuthorityModel, run_id)
        child = await db.get(Conversation, run.conversation_id) if run is not None else None
        if child is None or not child.parent_conversation_id:
            return
    spawn = await current_agent_orchestrator_v2().get_spawn_record(child.id)
    if spawn is None:
        raise _denied()
    await project_peer_terminal_v2(
        run_id=run_id,
        operation=current_operation_context_v2(),
        spawn=spawn,
        event_log=_session_event_log_service_v2(),
        redis_client=await _get_redis_client(),
        sessions=async_session_factory,
    )
