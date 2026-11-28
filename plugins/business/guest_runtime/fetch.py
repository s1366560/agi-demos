"""HTTP helpers for a business guest. Status stays visible so the child can shape errors."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from plugins.business.guest_runtime.binding import current


async def exchange(
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, Any]:
    result = await current().http(method, path, body=body, query=query, headers=headers)
    return int(result["status"]), result.get("body")


def object_body(status: int, body: object, failure: str) -> dict[str, object]:
    if status >= 400:
        raise HTTPException(status, failure)
    if not isinstance(body, dict):
        raise HTTPException(502, failure)
    return body
