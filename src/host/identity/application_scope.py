"""Select the authenticated tenant for an in-process application capability call."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_current: ContextVar[tuple[str, str] | None] = ContextVar("application_actor_tenant", default=None)


@contextmanager
def application_actor_scope(user_id: str, tenant_id: str) -> Iterator[None]:
    token = _current.set((user_id, tenant_id))
    try:
        yield
    finally:
        _current.reset(token)


def application_tenant_for(user_id: str) -> str | None:
    current = _current.get()
    return current[1] if current and current[0] == user_id else None
