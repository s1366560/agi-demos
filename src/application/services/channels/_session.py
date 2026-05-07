"""Shared session-acquisition helper for channel handlers.

Channel handlers repeatedly open short-lived database sessions for
binding lookups, HITL persistence, and similar one-shot reads/writes.
Centralising the open/close protocol here eliminates the import noise
of pulling ``async_session_factory`` into every local function scope
and ensures all channel paths share the exact same lifecycle (no
implicit commits — callers must commit explicitly).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession


@asynccontextmanager
async def with_session() -> AsyncIterator[AsyncSession]:
    """Open a fresh ``AsyncSession`` bound to the global session factory.

    Usage::

        async with with_session() as session:
            ...

    The factory is imported lazily so this module stays cheap to import
    at module-load time and so test environments that monkeypatch the
    factory still take effect.
    """
    from src.infrastructure.adapters.secondary.persistence.database import (
        async_session_factory,
    )

    async with async_session_factory() as session:
        yield session


__all__ = ("with_session",)
