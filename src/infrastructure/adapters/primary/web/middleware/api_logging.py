from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request, Response

logger = logging.getLogger("src.infrastructure.adapters.primary.web.api_access")

_REQUEST_ID_HEADER = "X-Request-ID"
_NO_ROUTE = "-"


def _client_host(request: Request) -> str:
    client = request.client
    return client.host if client is not None else _NO_ROUTE


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    return route_path if isinstance(route_path, str) else _NO_ROUTE


def _request_id(request: Request) -> str:
    value = request.headers.get(_REQUEST_ID_HEADER)
    return value if value else uuid4().hex


def _serialize_api_log(fields: dict[str, object]) -> str:
    return json.dumps(fields, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _log_api_request(fields: dict[str, object], *, exc_info: bool = False) -> None:
    status_code = fields.get("status_code")
    if exc_info:
        logger.exception("api_request %s", _serialize_api_log(fields))
        return
    if isinstance(status_code, int) and status_code >= 500:
        logger.warning("api_request %s", _serialize_api_log(fields))
        return
    logger.info("api_request %s", _serialize_api_log(fields))


def install_api_access_log_middleware(app: FastAPI) -> None:
    """Install a single structured access log line for every HTTP API request."""

    @app.middleware("http")
    async def _api_access_log_middleware(  # pyright: ignore[reportUnusedFunction]
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        started_at = perf_counter()
        request_id = _request_id(request)
        response: Response | None = None
        status_code = 500

        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception:
            duration_ms = round((perf_counter() - started_at) * 1000, 2)
            _log_api_request(
                {
                    "client_ip": _client_host(request),
                    "duration_ms": duration_ms,
                    "method": request.method,
                    "path": request.url.path,
                    "request_id": request_id,
                    "route": _route_template(request),
                    "status_code": status_code,
                    "user_agent": request.headers.get("user-agent", ""),
                },
                exc_info=True,
            )
            raise
        finally:
            if response is not None:
                response.headers[_REQUEST_ID_HEADER] = request_id
                duration_ms = round((perf_counter() - started_at) * 1000, 2)
                _log_api_request(
                    {
                        "client_ip": _client_host(request),
                        "duration_ms": duration_ms,
                        "method": request.method,
                        "path": request.url.path,
                        "request_id": request_id,
                        "route": _route_template(request),
                        "status_code": status_code,
                        "user_agent": request.headers.get("user-agent", ""),
                    }
                )
