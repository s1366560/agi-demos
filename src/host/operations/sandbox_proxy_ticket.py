"""One-time tickets for host-to-sandbox-proxy sockets.

The command guest never sees a caller bearer. A real WebSocket to the sandbox
proxy cannot see process-local admission, so the host mints a ticket that only
this process will honor.
"""

from __future__ import annotations

import secrets
import time

_TTL_SECONDS = 30.0


def issue_sandbox_proxy_ticket(app: object, user_id: str) -> str:
    token = "ms_sk_" + secrets.token_hex(32)
    store: dict[str, tuple[str, float]] = getattr(app.state, "sandbox_proxy_tickets", None)
    if store is None:
        store = {}
        app.state.sandbox_proxy_tickets = store
    store[token] = (str(user_id), time.monotonic() + _TTL_SECONDS)
    return token


def user_for_sandbox_proxy_ticket(app: object, token: str) -> str | None:
    store: dict[str, tuple[str, float]] | None = getattr(app.state, "sandbox_proxy_tickets", None)
    if not store or token not in store:
        return None
    user_id, expires_at = store[token]
    if time.monotonic() > expires_at:
        del store[token]
        return None
    return user_id
