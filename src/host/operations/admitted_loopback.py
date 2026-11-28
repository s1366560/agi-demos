"""Call this process's own routes as the already-admitted actor.

The caller bearer is not copied onto the ASGI request. Routes that read the
process-local admission see the actor; an external client cannot set it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol

import httpx

from src.host.operations.agent_package.admission import admit


class _User(Protocol):
    id: object


class _Scope(Protocol):
    tenant_id: str


class _Request(Protocol):
    app: object


class AdmittedCall(Protocol):
    user: _User
    scope: _Scope
    request: _Request


@asynccontextmanager
async def admitted_client(ctx: AdmittedCall) -> AsyncIterator[httpx.AsyncClient]:
    with admit(str(ctx.user.id), ctx.scope.tenant_id):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=ctx.request.app),
            base_url="http://localhost",
            trust_env=False,
            follow_redirects=False,
        ) as client:
            yield client
