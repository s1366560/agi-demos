"""Bind schema discovery to the transaction that admitted an episode."""

from asyncio import Task, current_task
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, AsyncSessionTransaction

from src.domain.model.knowledge_sync.contracts import KnowledgeSyncError


@dataclass(frozen=True)
class _Admission:
    session: AsyncSession
    transaction: AsyncSessionTransaction
    task: Task[object] | None
    project: str
    tenant: str


_admission: ContextVar[_Admission | None] = ContextVar("graph_schema_admission", default=None)


@contextmanager
def bind_discovery(session: AsyncSession, *, project: str, tenant: str) -> Iterator[None]:
    transaction = session.get_transaction()
    if transaction is None:
        raise RuntimeError("Graph discovery requires an active transaction")
    token = _admission.set(_Admission(session, transaction, current_task(), project, tenant))
    try:
        yield
    finally:
        _admission.reset(token)


def discovery_session(project: str, tenant: str | None) -> AsyncSession | None:
    admission = _admission.get()
    if admission is None:
        return None
    if (
        (project, tenant) != (admission.project, admission.tenant)
        or current_task() is not admission.task
        or admission.session.get_transaction() is not admission.transaction
        or not admission.transaction.is_active
    ):
        raise KnowledgeSyncError("knowledge_sync_forbidden")
    return admission.session
