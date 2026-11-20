"""HTTP client wrapping httpx with a consistent error shape."""

from __future__ import annotations

import json as _json
import os
import sys
from collections.abc import Iterator
from typing import Any, NoReturn

import httpx

from .auth import AuthError, load_refresh_token, resolve_api_key, save_login_session

DEFAULT_TIMEOUT = 60.0
_REFRESH_SKIP_PREFIXES = ("/auth/refresh", "/auth/token", "/auth/device/")


def base_url() -> str:
    return os.environ.get("MEMSTACK_API_URL", "http://localhost:8000").rstrip("/")


class ApiError(RuntimeError):
    def __init__(self, status_code: int, detail: str):
        super().__init__(f"HTTP {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


def _build_headers(api_key: str | None, *, stream: bool = False) -> dict[str, str]:
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if stream:
        headers["Accept"] = "text/event-stream"
    return headers


def request(
    method: str,
    path: str,
    *,
    api_key: str | None = None,
    json: Any = None,
    params: dict[str, Any] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    _refresh: bool = True,
) -> Any:
    """Synchronous JSON request. Returns parsed body (or {} on empty)."""
    url = f"{base_url()}/api/v1{path}"
    headers = _build_headers(api_key)
    try:
        resp = httpx.request(
            method, url, headers=headers, json=json, params=params, timeout=timeout
        )
    except httpx.HTTPError as e:  # pragma: no cover - network failure path
        raise ApiError(-1, str(e)) from e
    if (
        resp.status_code == 401
        and _refresh
        and api_key
        and not path.startswith(_REFRESH_SKIP_PREFIXES)
    ):
        rotated = _rotate_stored_session(api_key, timeout=timeout)
        if rotated:
            return request(
                method,
                path,
                api_key=rotated,
                json=json,
                params=params,
                timeout=timeout,
                _refresh=False,
            )
    if resp.status_code >= 400:
        raise ApiError(resp.status_code, resp.text)
    if not resp.content:
        return {}
    return resp.json()


def _rotate_stored_session(api_key: str, *, timeout: float) -> str | None:
    """Rotate the stored login when this request used that exact access token."""
    try:
        stored = resolve_api_key(None)
    except AuthError:
        return None
    refresh_token = load_refresh_token()
    if stored != api_key or not refresh_token:
        return None
    try:
        body = request(
            "POST",
            "/auth/refresh",
            json={"refresh_token": refresh_token},
            timeout=timeout,
            _refresh=False,
        )
    except ApiError:
        return None
    access_token = body.get("access_token") if isinstance(body, dict) else None
    next_refresh = body.get("refresh_token") if isinstance(body, dict) else None
    if not isinstance(access_token, str) or not access_token:
        return None
    if not isinstance(next_refresh, str):
        next_refresh = None
    save_login_session(access_token, next_refresh)
    return access_token


def stream_sse(
    method: str,
    path: str,
    *,
    api_key: str | None = None,
    json: Any = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Iterator[tuple[str, str]]:
    """Iterate over SSE lines; yields (event_name, data) tuples.

    `event_name` defaults to "message" when no `event:` header is present.
    """
    url = f"{base_url()}/api/v1{path}"
    headers = _build_headers(api_key, stream=True)
    try:
        with httpx.stream(
            method, url, headers=headers, json=json, timeout=timeout
        ) as resp:
            if resp.status_code >= 400:
                raise ApiError(resp.status_code, resp.read().decode("utf-8", "replace"))
            event_name = "message"
            for raw_line in resp.iter_lines():
                line = raw_line.rstrip("\r")
                if not line:
                    event_name = "message"
                    continue
                if line.startswith("event: "):
                    event_name = line[7:]
                elif line.startswith("data: "):
                    yield event_name, line[6:]
    except httpx.HTTPError as e:  # pragma: no cover
        raise ApiError(-1, str(e)) from e


def emit(data: Any, *, as_json: bool, human: str | None = None) -> None:
    """Unified output helper for commands."""
    if as_json:
        print(_json.dumps(data, ensure_ascii=False))
        return
    if human is not None:
        print(human)
    else:
        print(_json.dumps(data, indent=2, ensure_ascii=False))


def die(message: str, code: int = 1) -> NoReturn:
    print(f"error: {message}", file=sys.stderr)
    sys.exit(code)
