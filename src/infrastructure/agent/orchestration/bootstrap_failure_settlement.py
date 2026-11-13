"""Settle a child that failed before a plugin operation could be pinned.

The only authority is the spawn relationship ``spawn_agent`` already registered.
This module does not pin an operation, open a generation Redis client, or start
execution. A repeated or late call keeps the first terminal record.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

if TYPE_CHECKING:
    from src.infrastructure.agent.orchestration.orchestrator import AgentOrchestrator


@dataclass(frozen=True)
class _SpawnBootstrapOwner:
    orchestrator: AgentOrchestrator
    run_conversation_id: str | None
    detached: bool


_owners: dict[str, _SpawnBootstrapOwner] = {}
_receipts: dict[str, str] = {}
_locks: dict[str, asyncio.Lock] = {}


def bind_spawn_bootstrap_owner(
    *,
    child_session_id: str,
    orchestrator: AgentOrchestrator,
    run_conversation_id: str | None,
    detached: bool,
) -> None:
    """Remember the orchestrator that registered this child."""
    _owners[child_session_id] = _SpawnBootstrapOwner(
        orchestrator=orchestrator,
        run_conversation_id=run_conversation_id,
        detached=detached,
    )


def unbind_spawn_bootstrap_owner(child_session_id: str) -> None:
    """Drop the owner when spawn itself already settled the child."""
    _ = _owners.pop(child_session_id, None)


async def settle_unpinned_child_bootstrap_failure(
    *,
    child_session_id: str,
    child_agent_id: str,
    parent_session_id: str,
    project_id: str,
    request_message_id: str,
    error_message: str,
) -> None:
    """Write the failure onto the registered spawn, or reject a mismatched one."""
    lock = _locks.setdefault(child_session_id, asyncio.Lock())
    async with lock:
        if child_session_id in _receipts:
            return
        owner = _owners.get(child_session_id)
        if owner is None:
            raise RuntimeV2Error(
                "child_bootstrap_owner_missing",
                "no registered spawn owns this child bootstrap failure",
            )
        outcome = await owner.orchestrator.record_unadmitted_child_failure(
            child_session_id=child_session_id,
            child_agent_id=child_agent_id,
            parent_session_id=parent_session_id,
            project_id=project_id,
            request_message_id=request_message_id,
            error_message=error_message,
            detached=owner.detached,
            run_conversation_id=owner.run_conversation_id,
        )
        _receipts[child_session_id] = outcome
        unbind_spawn_bootstrap_owner(child_session_id)
