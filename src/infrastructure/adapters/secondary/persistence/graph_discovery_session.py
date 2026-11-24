"""Collect schema discovery until the graph admission has committed and released its fence."""

from asyncio import Task, current_task
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession, AsyncSessionTransaction

from src.domain.model.knowledge_sync.contracts import KnowledgeSyncError


@dataclass(kw_only=True)
class _Discovery:
    project: str
    tenant: str
    session: AsyncSession
    transaction: AsyncSessionTransaction
    task: Task[object] | None
    writes: list[Callable[[], Awaitable[None]]] = field(default_factory=list)

    async def persist(self) -> None:
        for write in self.writes:
            await write()


_admission: ContextVar[_Discovery | None] = ContextVar("graph_schema_admission", default=None)


@contextmanager
def bind_discovery(session: AsyncSession, *, project: str, tenant: str) -> Iterator[_Discovery]:
    transaction = session.get_transaction()
    if transaction is None:
        raise RuntimeError("Graph discovery requires an active transaction")
    discovery = _Discovery(
        project=project,
        tenant=tenant,
        session=session,
        transaction=transaction,
        task=current_task(),
    )
    token = _admission.set(discovery)
    try:
        yield discovery
    finally:
        _admission.reset(token)


async def persist_after_graph_commit(
    project: str, tenant: str | None, write: Callable[[], Awaitable[None]]
) -> None:
    admission = _admission.get()
    if admission is None:
        await write()
        return
    if (
        (project, tenant) != (admission.project, admission.tenant)
        or current_task() is not admission.task
        or admission.session.get_transaction() is not admission.transaction
        or not admission.transaction.is_active
    ):
        raise KnowledgeSyncError("knowledge_sync_forbidden")
    admission.writes.append(write)
