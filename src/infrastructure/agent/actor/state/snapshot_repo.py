"""Snapshot persistence for Actor-based HITL recovery."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.adapters.secondary.persistence.models import AgentSessionSnapshot
from src.infrastructure.adapters.secondary.persistence.sql_agent_session_snapshot_repository import (
    SqlAgentSessionSnapshotRepository,
)
from src.infrastructure.agent.hitl.state_store import HITLAgentState


async def save_hitl_snapshot(
    state: HITLAgentState,
    agent_mode: str,
    snapshot_type: str = "hitl",
) -> None:
    """Persist HITL state snapshot to Postgres."""
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=state.timeout_seconds + 60)

    snapshot = AgentSessionSnapshot(
        id=str(uuid.uuid4()),
        tenant_id=state.tenant_id,
        project_id=state.project_id,
        agent_mode=agent_mode,
        request_id=state.hitl_request_id,
        snapshot_type=snapshot_type,
        snapshot_data=state.to_dict(),
        created_at=datetime.now(timezone.utc),
        expires_at=expires_at,
    )

    async with async_session_factory() as session:
        repo = SqlAgentSessionSnapshotRepository(session)
        await repo.save_snapshot(snapshot)
        await session.commit()


async def load_hitl_snapshot(request_id: str) -> Optional[HITLAgentState]:
    """Load latest HITL state snapshot for a request."""
    async with async_session_factory() as session:
        repo = SqlAgentSessionSnapshotRepository(session)
        snapshot = await repo.get_latest_by_request_id(request_id)
        if not snapshot:
            return None
        return HITLAgentState.from_dict(snapshot.snapshot_data or {})


async def delete_hitl_snapshot(request_id: str) -> int:
    """Delete HITL snapshots for a request."""
    async with async_session_factory() as session:
        repo = SqlAgentSessionSnapshotRepository(session)
        deleted = await repo.delete_by_request_id(request_id)
        await session.commit()
        return deleted
