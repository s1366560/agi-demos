"""Starlette middleware that pins the current request to a negotiated locale.

Order of preference (highest first):

1. ``X-Language`` request header — explicit override sent by the frontend after
   the user clicks the language switcher.
2. ``lang`` query parameter — handy for share-able localized links.
3. ``Accept-Language`` header — RFC 9110 weighted negotiation.
4. ``DEFAULT_LOCALE`` — fallback when none of the above resolves.

The middleware also writes ``Content-Language`` on the outbound response so any
intermediate cache / CDN can vary on it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src.infrastructure.i18n.locale import (
    reset_current_locale,
    resolve_locale,
    set_current_locale,
)


class LocaleMiddleware(BaseHTTPMiddleware):
    """Resolve and pin the request locale for downstream handlers."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        explicit = request.headers.get("x-language") or request.query_params.get("lang")
        accept_language = request.headers.get("accept-language")
        locale = resolve_locale(accept_language=accept_language, explicit=explicit)

        token = set_current_locale(locale)
        try:
            response = await call_next(request)
        finally:
            reset_current_locale(token)

        # Surface the resolved locale to clients and any intermediate cache.
        response.headers.setdefault("Content-Language", locale.replace("_", "-"))
        return response
