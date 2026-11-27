"""Process-local admission for host routes called by an agent command guest.

The guest never receives the caller's bearer token. A route running on the same
task can see this admission; an external request cannot set it.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from src.host.identity.application_scope import application_actor_scope

_actor: ContextVar[tuple[str, str] | None] = ContextVar("agent_command_actor", default=None)
ADMITTED_KEY_PREFIX = "ms_sk_admitted:"


def admitted_actor() -> tuple[str, str] | None:
    return _actor.get()


@contextmanager
def admit(user_id: str, tenant_id: str) -> Iterator[None]:
    token = _actor.set((str(user_id), tenant_id))
    try:
        with application_actor_scope(str(user_id), tenant_id):
            yield
    finally:
        _actor.reset(token)


def admitted_api_key() -> str | None:
    actor = _actor.get()
    if actor is None:
        return None
    return ADMITTED_KEY_PREFIX + actor[0]


def actor_for_admitted_key(api_key: str) -> str | None:
    actor = _actor.get()
    if actor is None or not api_key.startswith(ADMITTED_KEY_PREFIX):
        return None
    user_id = api_key.removeprefix(ADMITTED_KEY_PREFIX)
    if user_id != actor[0]:
        return None
    return user_id
