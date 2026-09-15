"""Awaited PostgreSQL registry transactions with pure in-memory domain mutations.

No connection, DDL, or background persistence occurs at construction. Each call
loads current authoritative state, applies the existing registry domain rules,
and commits before returning. Worker startup never expires another owner's runs.
"""

from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from copy import deepcopy
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.model.plugins.generated_v2 import ScopeV2
from src.infrastructure.adapters.secondary.persistence.models import Conversation
from src.infrastructure.adapters.secondary.persistence.subagent_run_snapshot_model_v2 import (
    SubAgentRunSnapshotV2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

from .owner_lease_v2 import (
    SubAgentExecutionOwnerV2,
    assert_owner_v2,
    current_owner_v2,
    registry_lock_v2,
)
from .owner_registry_v2 import reconcile_revoked_owners_v2, validate_owned_write_v2
from .run_registry import SubAgentRunRegistry
from .run_repository import _deserialize_run

_RESULT = TypeVar("_RESULT")
_WRITE_METHODS = frozenset(
    {
        "create_run",
        "bind_approved_plan_authority",
        "bind_chat_permission_authority",
        "mark_running",
        "mark_completed",
        "mark_failed",
        "mark_cancelled",
        "mark_timed_out",
        "attach_metadata",
        "set_trace_context",
    }
)
_READ_METHODS = frozenset(
    {
        "get_run",
        "list_runs",
        "list_trace_runs",
        "list_runs_for_conversations",
        "list_runs_for_requester",
        "list_descendant_runs",
        "count_active_runs",
        "count_all_active_runs",
        "count_active_runs_for_conversations",
        "count_active_runs_for_lineage",
        "count_active_runs_for_requester",
    }
)


def _operation_scope() -> ScopeV2 | None:
    from src.infrastructure.plugins.v2.boundary import current_operation_context_v2

    try:
        return current_operation_context_v2().context.scope
    except RuntimeV2Error as error:
        if error.code == "operation_context_not_pinned":
            return None
        raise


class AsyncSubAgentRunRegistryV2(SubAgentRunRegistry):
    """Production facade: synchronous registry access fails instead of losing writes."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        terminal_retention_seconds: int = 86400,
        scope_provider: Callable[[], ScopeV2 | None] = _operation_scope,
    ) -> None:
        super().__init__(
            terminal_retention_seconds=terminal_retention_seconds,
            recover_inflight_on_boot=False,
            sync_across_processes=False,
        )
        self._sessions = sessions
        self._scope_provider = scope_provider

    @contextmanager
    def _with_registry_lock(self, *, exclusive: bool) -> Iterator[None]:
        self._sync_from_disk()
        yield

    def _sync_from_disk(self) -> None:
        raise RuntimeV2Error("async_registry_required", "SubAgent registry access must be awaited")

    async def transaction(
        self, operation: Callable[[SubAgentRunRegistry], _RESULT], *, write: bool = False
    ) -> _RESULT:
        scope = self._scope_provider()
        async with self._sessions() as db, db.begin():
            await registry_lock_v2(db)
            authority = current_owner_v2.get()
            if authority is not None:
                _ = await assert_owner_v2(db, authority, allow_closed=True)
            query = (
                select(SubAgentRunSnapshotV2)
                .join(Conversation, Conversation.id == SubAgentRunSnapshotV2.conversation_id)
                .where(
                    Conversation.tenant_id == SubAgentRunSnapshotV2.tenant_id,
                    Conversation.project_id == SubAgentRunSnapshotV2.project_id,
                )
            )
            if scope is not None:
                for field in ("tenant_id", "project_id"):
                    value = getattr(scope, field)
                    if value is not None:
                        query = query.where(getattr(SubAgentRunSnapshotV2, field) == value)
                if scope.session_id is not None:
                    query = query.where(SubAgentRunSnapshotV2.conversation_id == scope.session_id)
            rows = {row.conversation_id: row for row in (await db.scalars(query)).all()}
            memory = SubAgentRunRegistry(
                terminal_retention_seconds=self.terminal_retention_seconds,
                recover_inflight_on_boot=False,
                sync_across_processes=False,
            )
            for conversation_id, row in rows.items():
                bucket = {}
                for run_id, payload in row.runs.items():
                    run = _deserialize_run(deepcopy(payload))
                    if (
                        run is None
                        or run.run_id != run_id
                        or run.conversation_id != conversation_id
                    ):
                        raise RuntimeV2Error(
                            "invalid_persisted_run", "Stored SubAgent identity differs"
                        )
                    bucket[run_id] = run
                memory._runs_by_conversation[conversation_id] = bucket
            recovered = await reconcile_revoked_owners_v2(db, memory)
            result = operation(memory)
            if write or recovered:
                await self._save(db, memory, rows, scope, recovered)
            return result

    @asynccontextmanager
    async def own_execution(
        self, conversation_id: str, run_id: str
    ) -> AsyncIterator[SubAgentExecutionOwnerV2]:
        run = await registry_call_v2(self, "get_run", conversation_id, run_id)
        if run is None:
            raise RuntimeV2Error(
                "subagent_owner_claim_rejected", "SubAgent run is outside the admitted scope"
            )
        try:
            async with SubAgentExecutionOwnerV2(self._sessions, conversation_id, run_id) as owner:
                yield owner
        finally:
            # This read reconciles a revoked lease after the owner ContextVar resets.
            _ = await registry_call_v2(self, "get_run", conversation_id, run_id)

    @staticmethod
    async def _save(
        db: AsyncSession,
        memory: SubAgentRunRegistry,
        rows: dict[str, SubAgentRunSnapshotV2],
        scope: ScopeV2 | None,
        recovered: set[tuple[str, str]],
    ) -> None:
        for conversation_id, bucket in memory._runs_by_conversation.items():
            conversation = await db.get(Conversation, conversation_id)
            if conversation is None:
                raise RuntimeV2Error(
                    "subagent_conversation_missing", "SubAgent conversation is absent"
                )
            if scope is not None and any(
                expected is not None and expected != actual
                for expected, actual in (
                    (scope.tenant_id, conversation.tenant_id),
                    (scope.project_id, conversation.project_id),
                    (scope.session_id, conversation.id),
                )
            ):
                raise RuntimeV2Error(
                    "subagent_scope_mismatch", "SubAgent conversation is outside scope"
                )
            for run in bucket.values():
                if any(
                    run.metadata.get(field) not in (None, value)
                    for field, value in (
                        ("tenant_id", conversation.tenant_id),
                        ("project_id", conversation.project_id),
                    )
                ):
                    raise RuntimeV2Error(
                        "subagent_scope_mismatch", "SubAgent metadata ownership differs"
                    )
            for run_id, run in bucket.items():
                previous_row = rows.get(conversation_id)
                previous = previous_row.runs.get(run_id) if previous_row else None
                if previous != run.to_event_data():
                    await validate_owned_write_v2(db, run, previous, recovered)
            payload = {run_id: run.to_event_data() for run_id, run in bucket.items()}
            row = rows.get(conversation_id)
            if row is None:
                db.add(
                    SubAgentRunSnapshotV2(
                        conversation_id=conversation_id,
                        tenant_id=conversation.tenant_id,
                        project_id=conversation.project_id,
                        runs=payload,
                    )
                )
            elif row.runs != payload:
                row.runs = payload
        await db.flush()


async def registry_transaction_v2[T](
    registry: SubAgentRunRegistry,
    operation: Callable[[SubAgentRunRegistry], T],
    *,
    write: bool = False,
) -> T:
    if isinstance(registry, AsyncSubAgentRunRegistryV2):
        return await registry.transaction(operation, write=write)
    return operation(registry)


async def registry_call_v2(
    registry: SubAgentRunRegistry, method: str, *args: object, **kwargs: object
) -> Any:  # noqa: ANN401
    """Await production persistence; preserve the legacy in-memory test/domain adapter."""
    if method not in _READ_METHODS | _WRITE_METHODS:
        raise ValueError("Unsupported SubAgent registry operation")
    return await registry_transaction_v2(
        registry,
        lambda memory: getattr(memory, method)(*args, **kwargs),
        write=method in _WRITE_METHODS,
    )
