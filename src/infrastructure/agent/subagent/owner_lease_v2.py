"""Database-fenced execution authority; expiry revokes permission, never replays work."""

import asyncio
from collections.abc import Mapping
from contextlib import suppress
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import TracebackType
from typing import Self
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.infrastructure.adapters.secondary.persistence.subagent_owner_model_v2 import (
    SubAgentOwnerLeaseV2,
)
from src.infrastructure.adapters.secondary.persistence.subagent_run_snapshot_model_v2 import (
    SubAgentRunSnapshotV2,
)
from src.infrastructure.plugins.v2.runtime_context import RuntimeV2Error

OWNER_PROTOCOL_V2 = "detached-owner-v1"
REGISTRY_LOCK_ID_V2 = 0x4D535352
LEASE_DURATION_V2 = timedelta(seconds=30)
_INSTANCE_ID = uuid4().hex


@dataclass(frozen=True)
class SubAgentOwnerAuthorityV2:
    sessions: async_sessionmaker[AsyncSession]
    conversation_id: str
    run_id: str
    token: str


current_owner_v2: ContextVar[SubAgentOwnerAuthorityV2 | None] = ContextVar(
    "subagent_owner_v2", default=None
)


async def database_now_v2(db: AsyncSession) -> datetime:
    clock = (
        func.clock_timestamp()
        if db.get_bind().dialect.name == "postgresql"
        else func.current_timestamp()
    )
    value = await db.scalar(select(clock))
    assert isinstance(value, datetime)
    return value


async def registry_lock_v2(db: AsyncSession) -> None:
    if db.get_bind().dialect.name == "postgresql":
        await db.execute(text("SET LOCAL lock_timeout = '5s'"))
        await db.execute(text("SET LOCAL statement_timeout = '10s'"))
        await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": REGISTRY_LOCK_ID_V2})


async def assert_owner_v2(
    db: AsyncSession, authority: SubAgentOwnerAuthorityV2, *, allow_closed: bool = False
) -> SubAgentOwnerLeaseV2:
    row = await db.get(
        SubAgentOwnerLeaseV2, (authority.conversation_id, authority.run_id), populate_existing=True
    )
    if (
        row is not None
        and allow_closed
        and row.state == "closed"
        and row.owner_token == authority.token
    ):
        return row
    now = await database_now_v2(db)
    if (
        row is None
        or row.state != "active"
        or row.owner_token != authority.token
        or row.expires_at <= now
    ):
        raise RuntimeV2Error(
            "subagent_owner_revoked",
            "SubAgent execution ownership is no longer valid; prior in-flight outcomes are unknown",
        )
    return row


async def fence_subagent_owner_v2(*, child_run_id: str | None = None) -> None:
    """Revalidate immediately before model/tool dispatch, including durable cancellation."""
    authority = current_owner_v2.get()
    if authority is None and child_run_id is not None:
        raise RuntimeV2Error(
            "subagent_owner_missing", "Child execution requires its own owner lease"
        )
    if authority is not None and child_run_id is not None and authority.run_id != child_run_id:
        raise RuntimeV2Error(
            "subagent_owner_mismatch", "Child run differs from the execution owner"
        )
    if authority is None:
        from src.infrastructure.plugins.v2.boundary import (
            OPERATION_METADATA_SERVICE_V2,
            current_operation_context_v2,
        )

        try:
            operation = current_operation_context_v2()
        except RuntimeV2Error as exc:
            if exc.code == "operation_context_not_pinned":
                return
            raise
        metadata = operation.require(OPERATION_METADATA_SERVICE_V2)
        if isinstance(metadata, Mapping) and metadata.get("kind") == "detached-subagent":
            raise RuntimeV2Error(
                "subagent_owner_missing", "Detached SubAgent execution requires an owner lease"
            )
        return
    async with authority.sessions() as db, db.begin():
        await assert_owner_v2(db, authority)
        snapshot = await db.get(SubAgentRunSnapshotV2, authority.conversation_id)
        payload = snapshot.runs.get(authority.run_id) if snapshot else None
        if payload is None or payload.get("status") not in {"pending", "running"}:
            raise RuntimeV2Error("subagent_owner_revoked", "SubAgent run is no longer active")
        if payload.get("metadata", {}).get("cancel_requested") is True:
            raise asyncio.CancelledError("SubAgent cancellation requested")


class SubAgentExecutionOwnerV2:
    """Claim one admitted reservation and renew it for the lifetime of its owning task.

    Heartbeat failure cancels the actual owner. Renewal after expiry is forbidden;
    recovery and state writes serialize on the same database lock. No observer may
    infer a process died: an expired lease only proves dispatch authority revoked.
    """

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        conversation_id: str,
        run_id: str,
        *,
        lease_duration: timedelta = LEASE_DURATION_V2,
    ) -> None:
        if lease_duration.total_seconds() <= 0:
            raise ValueError("owner lease duration must be positive")
        self._lease_duration = lease_duration
        self.authority = SubAgentOwnerAuthorityV2(sessions, conversation_id, run_id, uuid4().hex)
        self.failure: Exception | None = None
        self._context_token: Token[SubAgentOwnerAuthorityV2 | None] | None = None
        self._heartbeat: asyncio.Task[None] | None = None

    async def __aenter__(self) -> Self:
        authority = self.authority
        async with authority.sessions() as db, db.begin():
            await registry_lock_v2(db)
            row = await db.get(SubAgentOwnerLeaseV2, (authority.conversation_id, authority.run_id))
            now = await database_now_v2(db)
            if row is None or row.state != "reserved" or row.expires_at <= now:
                raise RuntimeV2Error(
                    "subagent_owner_claim_rejected",
                    "SubAgent admission lease is absent, expired, or already owned",
                )
            snapshot = await db.get(SubAgentRunSnapshotV2, authority.conversation_id)
            run = snapshot.runs.get(authority.run_id) if snapshot else None
            if run is None or run.get("status") not in {"pending", "running"}:
                raise RuntimeV2Error(
                    "subagent_owner_claim_rejected", "SubAgent reservation is no longer active"
                )
            row.state = "active"
            row.owner_token = authority.token
            row.instance_id = _INSTANCE_ID
            row.expires_at = now + self._lease_duration
            row.heartbeat_at = now
        self._context_token = current_owner_v2.set(authority)
        owner = asyncio.current_task()
        assert owner is not None
        self._heartbeat = asyncio.create_task(
            self._renew(owner), name=f"subagent-owner-{authority.run_id}"
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._heartbeat is not None:
            _ = self._heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await self._heartbeat
        if self._context_token is not None:
            current_owner_v2.reset(self._context_token)
        async with self.authority.sessions() as db, db.begin():
            await registry_lock_v2(db)
            row = await db.get(
                SubAgentOwnerLeaseV2, (self.authority.conversation_id, self.authority.run_id)
            )
            if (
                row is not None
                and row.state == "active"
                and row.owner_token == self.authority.token
            ):
                row.expires_at = await database_now_v2(db)
        # Exiting the owner's resource revokes dispatch even before TTL expiration.
        # Terminal writes already close the lease in their own atomic transaction.

    async def _renew(self, owner: asyncio.Task[object]) -> None:
        try:
            while True:
                await asyncio.sleep(self._lease_duration.total_seconds() / 6)
                async with self.authority.sessions() as db, db.begin():
                    await registry_lock_v2(db)
                    row = await assert_owner_v2(db, self.authority, allow_closed=True)
                    if row.state == "closed":
                        return
                    now = await database_now_v2(db)
                    row.expires_at = now + self._lease_duration
                    row.heartbeat_at = now
        except Exception as exc:
            self.failure = exc
            if not owner.cancelling():
                _ = owner.cancel()
