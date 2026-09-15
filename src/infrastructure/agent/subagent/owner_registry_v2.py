"""Transactional owner reservation, terminal acknowledgement, and revoked-run settlement."""

from copy import deepcopy

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.subagent_run import SubAgentRun, SubAgentRunStatus
from src.infrastructure.adapters.secondary.persistence.subagent_owner_model_v2 import (
    SubAgentOwnerLeaseV2,
)
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.runtime_context import RuntimeV2Error

from .owner_lease_v2 import (
    LEASE_DURATION_V2,
    OWNER_PROTOCOL_V2,
    assert_owner_v2,
    current_owner_v2,
    database_now_v2,
)
from .run_registry import SubAgentRunRegistry

_ACTIVE = [SubAgentRunStatus.PENDING, SubAgentRunStatus.RUNNING]


async def reconcile_revoked_owners_v2(
    db: AsyncSession, memory: SubAgentRunRegistry
) -> set[tuple[str, str]]:
    """Lease expiry revokes dispatch authority; never infer completion or replay work."""
    changed: set[tuple[str, str]] = set()
    now = await database_now_v2(db)
    rows = await db.scalars(
        select(SubAgentOwnerLeaseV2).where(
            SubAgentOwnerLeaseV2.conversation_id.in_(memory._runs_by_conversation),
            SubAgentOwnerLeaseV2.state.in_(["reserved", "active"]),
            SubAgentOwnerLeaseV2.expires_at <= now,
        )
    )
    for row in rows:
        run = memory.get_run(row.conversation_id, row.run_id)
        if run is not None and run.status in _ACTIVE:
            outcome = "not_started" if row.state == "reserved" else "unknown"
            events = deepcopy(run.metadata.get("announce_events", []))
            if not isinstance(events, list):
                events = []
            events.append(
                {
                    "type": "subagent_interrupted",
                    "run_id": row.run_id,
                    "timestamp": now.isoformat(),
                    "reason": "execution_authority_revoked",
                    "prior_tool_outcome": outcome,
                    "automatic_replay": False,
                }
            )
            memory.mark_failed(
                row.conversation_id,
                row.run_id,
                error=_(
                    "SubAgent execution interrupted: owner authority revoked; prior in-flight tool outcomes may be unknown. Work was not replayed."
                ),
                metadata={
                    "recovery_status": "interrupted",
                    "prior_tool_outcome": outcome,
                    "automatic_replay": False,
                    "announce_events": events[-20:],
                    "announce_events_dropped": int(run.metadata.get("announce_events_dropped", 0))
                    + max(0, len(events) - 20),
                },
                expected_statuses=_ACTIVE,
            )
            changed.add((row.conversation_id, row.run_id))
        row.state = "revoked"
    return changed


async def validate_owned_write_v2(
    db: AsyncSession,
    run: SubAgentRun,
    previous: dict[str, object] | None,
    recovered: set[tuple[str, str]],
) -> None:
    key = (run.conversation_id, run.run_id)
    if key in recovered:
        return
    lease = await db.get(SubAgentOwnerLeaseV2, key)
    if previous is None and run.metadata.get("execution_protocol") == OWNER_PROTOCOL_V2:
        if lease is not None:
            raise RuntimeV2Error(
                "subagent_owner_conflict", "SubAgent owner reservation already exists"
            )
        now = await database_now_v2(db)
        db.add(
            SubAgentOwnerLeaseV2(
                conversation_id=run.conversation_id,
                run_id=run.run_id,
                state="reserved",
                expires_at=now + LEASE_DURATION_V2,
            )
        )
        return
    if lease is None:
        return  # Retained pre-protocol records have no invented ownership evidence.
    authority = current_owner_v2.get()
    if authority is not None and authority.run_id == run.run_id:
        _ = await assert_owner_v2(db, authority, allow_closed=True)
    state_changed = previous is not None and previous.get("status") != run.status.value
    if not state_changed or run.status in _ACTIVE:
        return
    if lease.state == "reserved" and run.status in {
        SubAgentRunStatus.FAILED,
        SubAgentRunStatus.CANCELLED,
    }:
        lease.state = "closed"  # Admission failed before any owner could execute.
        return
    if (
        authority is None
        or authority.run_id != run.run_id
        or authority.conversation_id != run.conversation_id
    ):
        raise RuntimeV2Error(
            "subagent_owner_ack_required",
            "Only the execution owner may acknowledge terminal status",
        )
    _ = await assert_owner_v2(db, authority)
    lease.state = "closed"
