from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "sdk" / "python"))

MemStackAsyncClient = pytest.importorskip("memstack.async_client").MemStackAsyncClient
MemStackClient = pytest.importorskip("memstack.client").MemStackClient


_API_KEY_RESPONSE = [
    {
        "key_id": "key-1",
        "key": "*****************",
        "name": "Paged Key",
        "created_at": "2026-01-01T00:00:00Z",
        "expires_at": None,
        "permissions": ["read"],
    }
]


def test_sync_client_list_api_keys_passes_pagination_params() -> None:
    client = MemStackClient(api_key="ms_sk_" + "0" * 64)
    calls: list[dict[str, Any]] = []

    def fake_request(
        method: str,
        endpoint: str,
        json_data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        calls.append(
            {
                "method": method,
                "endpoint": endpoint,
                "json_data": json_data,
                "params": params,
            }
        )
        return _API_KEY_RESPONSE

    try:
        client._make_request = fake_request  # type: ignore[method-assign]
        keys = client.list_api_keys(limit=10, offset=20)
    finally:
        client.close()

    assert calls == [
        {
            "method": "GET",
            "endpoint": "/api/v1/auth/keys",
            "json_data": None,
            "params": {"limit": 10, "offset": 20},
        }
    ]
    assert keys[0].key_id == "key-1"


@pytest.mark.asyncio
async def test_async_client_list_api_keys_passes_pagination_params() -> None:
    client = MemStackAsyncClient(api_key="ms_sk_" + "0" * 64)
    request = AsyncMock(return_value=_API_KEY_RESPONSE)

    try:
        client._make_request = request  # type: ignore[method-assign]
        keys = await client.list_api_keys(limit=15, offset=30)
    finally:
        await client.close()

    request.assert_awaited_once_with(
        "GET",
        "/api/v1/auth/keys",
        params={"limit": 15, "offset": 30},
    )
    assert keys[0].key_id == "key-1"
